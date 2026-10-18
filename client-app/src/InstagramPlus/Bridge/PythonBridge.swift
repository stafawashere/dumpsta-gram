import Foundation
import os
@preconcurrency import PythonKit

// The one owner of Python in the app (docs/bridge/threading-and-gil.md, rule 1). Every
// PythonObject is created, read and released on this actor, inside PythonRuntime.withGIL, and
// every method returns Swift values only. Exceptions are mapped here, onto EngineResult and
// EngineError, and never travel outward. Nothing here retries or paces: the engine does both.
//
// The actor runs on its own serial dispatch queue, so the short Python steps it takes never park
// a thread of Swift's cooperative pool.
//
// Engine calls do not block it. Each one is started with dumpstagram.pending.submit and polled
// (see Calling and mapping), so a write waiting in the engine's pacer, about 30 s under PARITY,
// leaves every other call and every other account free to run.
actor PythonBridge {
   static let shared = PythonBridge()

   struct Handle: Hashable, Sendable {
      fileprivate let rawValue: Int
   }

   struct CookieMaterial: Sendable {
      let sessionID: String
      let userID: String
      let csrfToken: String
      let extraCookies: [String: String]
   }

   struct OpenedSession: Sendable {
      let handle: Handle
      let viewerID: String
   }

   private enum Outcome<Value: Sendable>: Sendable {
      case value(Value)
      case checkpoint(Checkpoint)
      case failure(EngineError)
   }

   private let queue = DispatchSerialQueue(label: "io.github.stafawashere.instagramplus.python")
   private let logger = Logger(subsystem: "io.github.stafawashere.instagramplus", category: "bridge")

   private var dumpstagram: PythonObject?
   private var pendingModule: PythonObject?
   private var clients: [Handle: PythonObject] = [:]

   // The client each handle was opened as. clients holds a client scoped to the person's Behavior
   // choice when they changed it, which shares this one's session and pacer, and closing this one
   // stops both. Scoped clients a later choice replaced wait in retiredClients until the handle
   // closes, because a call started on one may still be running.
   private var openedClients: [Handle: PythonObject] = [:]
   private var retiredClients: [Handle: [PythonObject]] = [:]
   private var searchClients: [Handle: PythonObject] = [:]
   private var scopedHandles: Set<Handle> = []

   // Calls started with pending.submit and not collected yet, by call id.
   private var inFlight: [Int: PythonObject] = [:]
   private var nextCallID = 0
   private var warmHandles: Set<Handle> = []
   private var coldCalls: Set<Handle> = []
   private var listeners: [Handle: PythonObject] = [:]

   // stories.mark_seen takes the StoryItem and the StoryReel it was read in, so the reels read in
   // a session stay here, keyed by reel id, until the client closes.
   private var storyReels: [Handle: [String: PythonObject]] = [:]
   private var nextHandle = 0

   nonisolated var unownedExecutor: UnownedSerialExecutor {
      queue.asUnownedSerialExecutor()
   }

   // MARK: Runtime

   func bootstrap() throws(PythonRuntime.Failure) -> PythonRuntime.Report {
      let report = try PythonRuntime.bootstrap(on: self)

      if dumpstagram == nil {
         PythonRuntime.withGIL(on: self) {
            dumpstagram = Python.import("dumpstagram")
            pendingModule = Python.import("dumpstagram.pending")
         }
      }

      return report
   }

   // MARK: Sessions

   // Builds a Session from browser cookie material (ADR-0008) and saves it owner-only with
   // Session.save, then opens it the same way a later launch does, so the write budget and the
   // write stop live in the ledger beside the file from the first call.
   func adopt(_ material: CookieMaterial, savingTo sessionFile: URL) throws(EngineError) -> EngineResult<OpenedSession> {
      let saved: Outcome<Bool> = PythonRuntime.withGIL(on: self) {
         capture { module in
            let session = try module.Session.throwing.dynamicallyCall(withKeywordArguments: [
               "sessionid": material.sessionID,
               "ds_user_id": material.userID,
               "csrftoken": material.csrfToken,
               "extra_cookies": material.extraCookies,
            ])

            try session.save.throwing.dynamicallyCall(withArguments: [sessionFile.path])
            return true
         }
      }

      _ = try resolve(saved)

      return try open(sessionFile: sessionFile)
   }

   func open(sessionFile: URL) throws(EngineError) -> EngineResult<OpenedSession> {
      let opened: Outcome<OpenedSession> = PythonRuntime.withGIL(on: self) {
         capture { module in
            let client = try module.SyncClient.from_session_file.throwing.dynamicallyCall(withArguments: [sessionFile.path])
            let viewerID = try client.field("session").string("ds_user_id")
            let handle = Handle(rawValue: nextHandle)

            nextHandle += 1
            clients[handle] = client
            openedClients[handle] = client

            return OpenedSession(handle: handle, viewerID: viewerID)
         }
      }

      return try resolve(opened)
   }

   // Session.bootstrapped_at off the open client. Nothing is sent and no cookie is read.
   func sessionRefreshedAt(_ handle: Handle) -> Date? {
      let outcome: Outcome<Date?> = PythonRuntime.withGIL(on: self) {
         guard let client = clients[handle] else {
            return .value(nil)
         }

         return capture { _ in try client.field("session").optionalDate("bootstrapped_at") }
      }

      if case .value(let refreshedAt) = outcome {
         return refreshedAt
      }

      return nil
   }

   func close(_ handle: Handle) {
      stopEvents(handle)

      PythonRuntime.withGIL(on: self) {
         storyReels[handle] = nil
         warmHandles.remove(handle)

         let opened = openedClients.removeValue(forKey: handle)
         let current = clients.removeValue(forKey: handle)
         var scoped = retiredClients.removeValue(forKey: handle) ?? []

         if let search = searchClients.removeValue(forKey: handle) {
            scoped.append(search)
         }

         if scopedHandles.remove(handle) != nil, let current {
            scoped.append(current)
         }

         // Scoped clients first, then the client they share a pool with.
         for client in scoped {
            _ = try? client.close.throwing.dynamicallyCall(withArguments: [])
         }

         if let opened {
            _ = try? opened.close.throwing.dynamicallyCall(withArguments: [])
         }
      }
   }

   // MARK: Behavior and the write stop

   // Replaces the handle's client with one scoped to the person's Behavior choice, through
   // SyncClient.with_behavior, which keeps the session, the pool and the pacer. The choice
   // covers the two switches that send something a person sees: the read receipt a thread open
   // sends and the seen mark a story read sends. Nothing is sent here.
   func setBehavior(_ handle: Handle, _ choice: Engine.BehaviorChoice) throws(EngineError) -> EngineResult<Void> {
      let outcome: Outcome<Void> = PythonRuntime.withGIL(on: self) {
         guard let opened = openedClients[handle] else {
            return .failure(.authenticationFailed)
         }

         return capture { _ in
            let behavior = try Python.import("dataclasses").replace.throwing.dynamicallyCall(withKeywordArguments: [
               "": opened.field("behavior"),
               "mark_threads_read": choice.markThreadsRead,
               "mark_stories_seen": choice.markStoriesSeen,
            ])
            let scoped = try opened.with_behavior.throwing.dynamicallyCall(withArguments: [behavior])

            if scopedHandles.contains(handle), let current = clients[handle] {
               retiredClients[handle, default: []].append(current)
            }

            if let search = searchClients.removeValue(forKey: handle) {
               retiredClients[handle, default: []].append(search)
            }

            clients[handle] = scoped
            scopedHandles.insert(handle)
         }
      }

      return try resolve(outcome)
   }

   // session.clear_write_stop lifts the stop kept in the ledger beside the session file and says
   // whether one was set. An open client keeps its own stop for as long as it lives, so the
   // caller reopens the session after this. It reads and writes a local file only.
   func clearWriteStop(sessionFile: URL) throws(EngineError) -> EngineResult<Bool> {
      let outcome: Outcome<Bool> = PythonRuntime.withGIL(on: self) {
         capture { _ in
            let wasStopped = try Python.import("dumpstagram.session").clear_write_stop.throwing.dynamicallyCall(withArguments: [sessionFile.path])

            guard let wasStopped = Bool(wasStopped) else {
               throw DecodeFailure(path: "clear_write_stop")
            }

            return wasStopped
         }
      }

      return try resolve(outcome)
   }

   // MARK: Reads

   func profile(_ handle: Handle, username: String) async throws(EngineError) -> EngineResult<Engine.Profile> {
      try await submit(handle, "profile", [username]) { profile in
         return try decodeProfile(profile)
      }
   }

   func profile(_ handle: Handle, id userID: String) async throws(EngineError) -> EngineResult<Engine.Profile> {
      try await submit(handle, "profile_by_id", [userID]) { profile in
         return try decodeProfile(profile)
      }
   }

   func feed(_ handle: Handle, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.FeedItem>> {
      try await submit(handle, "feed", keywords: ["after": cursor]) { page in
         var skippedKinds: [String] = []

         let decoded = try decodePage(page) { item -> Engine.FeedItem? in
            let kindValue = try item.field("kind").string("value")

            guard let kind = Engine.FeedItemKind(rawValue: kindValue) else {
               skippedKinds.append(kindValue)
               return nil
            }

            let post = try item.field("post")
            return Engine.FeedItem(kind: kind, post: post.isNone ? nil : try decodePost(post))
         }

         // A kind newer than Engine.FeedItemKind carries no post the app can show. The count is
         // logged rather than dropped unseen.
         if !skippedKinds.isEmpty {
            logger.log("feed page skipped \(skippedKinds.count) items of kinds the Swift mirror lacks: \(skippedKinds.joined(separator: ","), privacy: .public)")
         }

         return decoded
      }
   }

   func comments(_ handle: Handle, postPK: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.Comment>> {
      try await submit(handle, "media.comments", keywords: ["": postPK, "after": cursor]) { page in
         return try decodePage(page, decodeComment)
      }
   }

   // media.by_code answers a PostDetail, which has every Post field the app reads except
   // is_seen. Six requests under the default Behavior.
   func post(_ handle: Handle, code: String) async throws(EngineError) -> EngineResult<Engine.Post> {
      try await submit(handle, "media.by_code", [code]) { detail in
         return try decodePost(detail, carriesSeenFlag: false)
      }
   }

   // media.download takes the engine's own MediaImage. The rendition is rebuilt from the values
   // the engine gave when the post was read, and the engine fetches its URL from the CDN. The
   // person already chose to replace a file at the destination in the save panel.
   func download(_ handle: Handle, image: Engine.MediaImage, to destination: URL) async throws(EngineError) -> EngineResult<URL> {
      try await submitWithModule(handle, "media.download") { module in
         let rendition = try module.MediaImage.throwing.dynamicallyCall(withKeywordArguments: [
            "url": image.url,
            "width": image.width,
            "height": image.height,
         ])

         return [("", rendition), ("", destination.path), ("overwrite", true)]
      } decode: { written, _ in
         guard let path = String(Python.str(written)) else {
            throw DecodeFailure(path: "download.path")
         }

         return URL(fileURLWithPath: path)
      }
   }

   func inbox(_ handle: Handle, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.DirectThread>> {
      try await submit(handle, "direct.inbox", keywords: ["after": cursor]) { page in
         return try decodePage(page, decodeThread)
      }
   }

   func messages(_ handle: Handle, threadFBID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.Message>> {
      try await submit(handle, "direct.messages", keywords: ["": threadFBID, "after": cursor]) { page in
         return try decodePage(page, decodeMessage)
      }
   }

   func messageRequests(_ handle: Handle) async throws(EngineError) -> EngineResult<Engine.MessageRequests> {
      try await submit(handle, "direct.message_requests", []) { requests in
         return Engine.MessageRequests(
            pending: try Array(requests.field("pending")).map(decodeThread),
            spam: try Array(requests.field("spam")).map(decodeThread)
         )
      }
   }

   func unreadCounts(_ handle: Handle) async throws(EngineError) -> EngineResult<Engine.UnreadCounts> {
      try await submit(handle, "direct.unread_counts", []) { counts in
         return Engine.UnreadCounts(inbox: try counts.int("inbox"), pending: try counts.int("pending"))
      }
   }

   func inboxLoad(_ handle: Handle) async throws(EngineError) -> EngineResult<Engine.InboxLoad> {
      try await submit(handle, "direct.inbox_load", []) { load in
         let counts = try load.field("unread_counts")

         return Engine.InboxLoad(
            threads: try decodePage(load.field("threads"), decodeThread),
            notes: try decodeNotes(load.field("notes")),
            unreadCounts: Engine.UnreadCounts(inbox: try counts.int("inbox"), pending: try counts.int("pending"))
         )
      }
   }

   func notes(_ handle: Handle) async throws(EngineError) -> EngineResult<[Engine.Note]> {
      try await submit(handle, "direct.notes") { notes in
         try decodeNotes(notes)
      }
   }

   private func decodeNotes(_ notes: PythonObject) throws -> [Engine.Note] {
      var unknownAudiences: [Int] = []

      let decoded = try Array(notes).compactMap { note -> Engine.Note? in
         let audienceValue = try note.int("audience")

         guard let audience = Engine.NoteAudience(rawValue: audienceValue) else {
            unknownAudiences.append(audienceValue)
            return nil
         }

         return try decodeNote(note, audience: audience)
      }

      // A note whose audience the Swift mirror lacks cannot be shown with the right label, so
      // it is left out and counted rather than dropped unseen.
      if !unknownAudiences.isEmpty {
         logger.log("notes skipped \(unknownAudiences.count) notes with audiences the Swift mirror lacks: \(unknownAudiences.map(String.init).joined(separator: ","), privacy: .public)")
      }

      return decoded
   }

   func storiesTray(_ handle: Handle) async throws(EngineError) -> EngineResult<[Engine.StoryTrayEntry]> {
      try await submit(handle, "stories.tray", []) { tray in
         return try Array(tray).map { row in
            Engine.StoryTrayEntry(
               user: try decodeStoryOwner(row.field("owner")),
               itemCount: nil,
               latestAt: try row.date("latest_item_at"),
               hasUnseen: nil,
               seenAt: try row.optionalDate("seen_at")
            )
         }
      }
   }

   // Under the default Behavior the engine marks the first item seen inside this read.
   func storyReel(_ handle: Handle, userID: String) async throws(EngineError) -> EngineResult<Engine.StoryReel?> {
      try await submit(handle, "stories.reel", [userID]) { reel in
         guard !reel.isNone else {
            return nil
         }

         return try keepStoryReel(reel, for: handle)
      }
   }

   func highlightReel(_ handle: Handle, highlightID: String) async throws(EngineError) -> EngineResult<Engine.StoryReel> {
      try await submit(handle, "stories.highlight", [highlightID]) { reel in
         return try keepStoryReel(reel, for: handle)
      }
   }

   func highlights(_ handle: Handle, userID: String) async throws(EngineError) -> EngineResult<[Engine.Highlight]> {
      try await submit(handle, "profiles.highlights", [userID]) { tray in
         return try Array(tray.field("highlights")).map { highlight in
            Engine.Highlight(id: try highlight.string("id"), title: try highlight.string("title"), itemCount: nil)
         }
      }
   }

   func profilePosts(_ handle: Handle, username: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try await submit(handle, "profiles.posts", keywords: ["": username, "after": cursor]) { page in
         return try decodePage(page, decodeTile)
      }
   }

   // The reels, tagged and saved reads answer one page with has_more and take no cursor, so a
   // page from them never has an end cursor.
   func profileReelsPage(_ handle: Handle, userID: String) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try await submit(handle, "profiles.reels", [userID]) { reels in
         return Engine.Page(items: try Array(reels.field("reels")).map(decodeTile), hasNextPage: try reels.bool("has_more"), endCursor: nil)
      }
   }

   func taggedPostsPage(_ handle: Handle, userID: String) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try await submit(handle, "profiles.tagged", [userID]) { tagged in
         return Engine.Page(items: try Array(tagged.field("posts")).map(decodeTile), hasNextPage: try tagged.bool("has_more"), endCursor: nil)
      }
   }

   // SavedPost has no comment_count, so its tiles carry nil rather than a zero.
   func savedPostsPage(_ handle: Handle) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try await submit(handle, "account.saved", []) { saved in
         let tiles = try Array(saved.field("posts")).map { post in
            Engine.GridTile(
               pk: try post.string("pk"),
               code: try post.string("code"),
               kind: try decodeMediaKind(post),
               likeCount: try post.int("like_count"),
               commentCount: nil,
               images: try Array(post.field("images")).map(decodeImage)
            )
         }

         return Engine.Page(items: tiles, hasNextPage: try saved.bool("has_more"), endCursor: nil)
      }
   }

   func profileReels(_ handle: Handle, userID: String) async throws(EngineError) -> EngineResult<[Engine.GridTile]> {
      Self.items(of: try await profileReelsPage(handle, userID: userID))
   }

   func taggedPosts(_ handle: Handle, userID: String) async throws(EngineError) -> EngineResult<[Engine.GridTile]> {
      Self.items(of: try await taggedPostsPage(handle, userID: userID))
   }

   func savedPosts(_ handle: Handle) async throws(EngineError) -> EngineResult<[Engine.GridTile]> {
      Self.items(of: try await savedPostsPage(handle))
   }

   private static func items<Item: Sendable>(of result: EngineResult<Engine.Page<Item>>) -> EngineResult<[Item]> {
      switch result {
         case .value(let page): .value(page.items)
         case .checkpoint(let checkpoint): .checkpoint(checkpoint)
      }
   }

   func followers(_ handle: Handle, userID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.UserSummary>> {
      try await submit(handle, "profiles.followers", keywords: ["": userID, "after": cursor]) { page in
         return try decodePage(page, decodeProfileSummary)
      }
   }

   func following(_ handle: Handle, userID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.UserSummary>> {
      try await submit(handle, "profiles.following", keywords: ["": userID, "after": cursor]) { page in
         return try decodePage(page, decodeProfileSummary)
      }
   }

   // Close friends and blocked accounts are two engine reads, the second sent once the first
   // answered. The engine has no muted list.
   func relationships(_ handle: Handle) async throws(EngineError) -> EngineResult<Engine.Relationships> {
      let closeFriendsRead = try await submit(handle, "account.close_friends") { accounts in
         try Array(accounts).map(decodeProfileSummary)
      }

      let closeFriends: [Engine.UserSummary]
      switch closeFriendsRead {
         case .value(let accounts): closeFriends = accounts
         case .checkpoint(let checkpoint): return .checkpoint(checkpoint)
      }

      let blockedRead = try await submit(handle, "account.blocked") { accounts in
         try Array(accounts).map { account in
            Engine.UserSummary(
               id: try account.string("id"),
               username: try account.string("username"),
               fullName: "",
               isVerified: try account.bool("is_verified"),
               isPrivate: false,
               profilePicURL: try account.string("profile_pic_url")
            )
         }
      }

      let blocked: [Engine.UserSummary]
      switch blockedRead {
         case .value(let accounts): blocked = accounts
         case .checkpoint(let checkpoint): return .checkpoint(checkpoint)
      }

      return .value(Engine.Relationships(
         closeFriendIDs: closeFriends.map(\.id),
         blockedIDs: blocked.map(\.id),
         mutedIDs: [],
         closeFriends: closeFriends,
         blocked: blocked,
         isMutedListKnown: false
      ))
   }

   // search.accounts sends the typeahead the client's Behavior names. With personalised false
   // the call goes through a client scoped to the non-personalised route, which shares this
   // client's session and pacer. It is kept for the handle and closed with it.
   func searchAccounts(_ handle: Handle, query: String, personalised: Bool) async throws(EngineError) -> EngineResult<[Engine.UserSummary]> {
      try await submit(handle, "search.accounts", [query], through: personalised ? .primary : .nonPersonalisedSearch) { accounts in
         try Array(accounts).map(decodeProfileSummary)
      }
   }

   func recentSearches(_ handle: Handle) async throws(EngineError) -> EngineResult<[Engine.RecentSearch]> {
      try await submit(handle, "search.recent", []) { entries in
         var unknownKinds: [String] = []

         let decoded = try Array(entries).compactMap { entry -> Engine.RecentSearch? in
            let kindValue = try entry.field("kind").string("value")

            guard let kind = Engine.RecentSearch.Kind(rawValue: kindValue) else {
               unknownKinds.append(kindValue)
               return nil
            }

            let account = try entry.optionalField("account")

            return Engine.RecentSearch(
               kind: kind,
               account: try account.map(decodeProfileSummary),
               keyword: try entry.optionalString("keyword")
            )
         }

         if !unknownKinds.isEmpty {
            logger.log("recent searches skipped \(unknownKinds.count) entries of kinds the Swift mirror lacks: \(unknownKinds.joined(separator: ","), privacy: .public)")
         }

         return decoded
      }
   }

   // ExploreGrid.posts joins its sections in the engine's order. The cursor is passed on as it came.
   func explore(_ handle: Handle, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try await submit(handle, "feeds.explore", keywords: ["after": cursor]) { grid in
         return Engine.Page(
            items: try Array(grid.field("posts")).map(decodeTile),
            hasNextPage: try grid.bool("more_available"),
            endCursor: try grid.optionalString("end_cursor")
         )
      }
   }

   // feeds.location reads the first grid page of a place by its Location.id. It returns no
   // cursor, so the page says whether more exist and nothing reads them.
   func placePosts(_ handle: Handle, placeID: String) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try await submit(handle, "feeds.location", [placeID]) { posts in
         return Engine.Page(
            items: try Array(posts.field("posts")).map(decodeTile),
            hasNextPage: try posts.bool("has_more"),
            endCursor: nil
         )
      }
   }

   // The reels feed carries no play count, and its audio title is absent where a reel has no
   // audio model.
   func reels(_ handle: Handle, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.Reel>> {
      try await submit(handle, "feeds.reels", keywords: ["after": cursor]) { page in
         return try decodePage(page) { post in
            let decoded = try decodePost(post)

            return Engine.Reel(
               post: decoded,
               audioTitle: decoded.audioTitle ?? "",
               playCount: 0,
               isPlayCountKnown: false,
               audioID: decoded.audioID
            )
         }
      }
   }

   // Every row stays untyped: ActivityItem.kind is the upstream's own string and the engine
   // offers no typed kind to map it to. hasUnseen comes from new_items, the rows the engine
   // says the viewer has not seen.
   func activityFeed(_ handle: Handle) async throws(EngineError) -> EngineResult<Engine.ActivityFeed> {
      try await submit(handle, "account.activity", []) { feed in
         let untyped = try Array(feed.field("items")).map { item in
            let firstMedia = try Array(item.field("media")).first

            return Engine.UntypedActivityEntry(
               id: try item.string("id"),
               rawKind: try item.string("kind"),
               text: try item.string("text"),
               accountID: try item.optionalString("account_id"),
               accountUsername: try item.optionalString("account_username"),
               occurredAt: try item.date("created_at"),
               mediaCode: try firstMedia?.string("shortcode")
            )
         }

         let hasUnseen = !Array(try feed.field("new_items")).isEmpty
         return Engine.ActivityFeed(entries: [], untyped: untyped, hasUnseen: hasUnseen)
      }
   }

   // The first page only. FollowRequests.has_more is not carried, because nothing reads a next page.
   func followRequests(_ handle: Handle) async throws(EngineError) -> EngineResult<[Engine.UserSummary]> {
      try await submit(handle, "account.follow_requests", []) { requests in
         return try Array(requests.field("accounts")).map(decodeProfileSummary)
      }
   }

   // SuggestedAccount.reason is dropped, since the rail has no place for it yet.
   func suggestedUsers(_ handle: Handle) async throws(EngineError) -> EngineResult<[Engine.UserSummary]> {
      try await submit(handle, "profiles.suggested_for_you", []) { suggested in
         return try Array(suggested).map { try decodeProfileSummary($0.field("account")) }
      }
   }

   // MARK: Reads added after 1.1.0

   // media.page loads the post page as a browser does, six requests under the default Behavior.
   func postPage(_ handle: Handle, code: String) async throws(EngineError) -> EngineResult<Engine.PostPage> {
      try await submit(handle, "media.page", [code]) { page in
         return Engine.PostPage(
            post: try decodePost(page.field("post"), carriesSeenFlag: false),
            comments: try decodePage(page.field("comments"), decodeComment),
            authorGrid: try Array(page.field("author_grid")).map(decodeTile)
         )
      }
   }

   // media.by_id answers a thinner PostDetail than by_code, one request.
   func post(_ handle: Handle, pk: String) async throws(EngineError) -> EngineResult<Engine.Post> {
      try await submit(handle, "media.by_id", [pk]) { detail in
         return try decodePost(detail, carriesSeenFlag: false)
      }
   }

   // A sample of the likers. The engine offers no cursor.
   func likers(_ handle: Handle, postPK: String) async throws(EngineError) -> EngineResult<[Engine.UserSummary]> {
      try await submit(handle, "media.likers", [postPK]) { likers in
         try Array(likers).map(decodeProfileSummary)
      }
   }

   func moreFromAuthor(_ handle: Handle, authorID: String) async throws(EngineError) -> EngineResult<[Engine.GridTile]> {
      try await submit(handle, "media.more_from_author", [authorID]) { posts in
         try Array(posts).map(decodeTile)
      }
   }

   func replies(_ handle: Handle, postPK: String, commentID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.Comment>> {
      try await submit(handle, "media.replies", keywords: ["": postPK, "": commentID, "after": cursor]) { page in
         return try decodePage(page, decodeComment)
      }
   }

   func mutualFollowers(_ handle: Handle, userID: String) async throws(EngineError) -> EngineResult<Engine.MutualFollowers> {
      try await submit(handle, "profiles.mutual_followers", [userID]) { mutual in
         return Engine.MutualFollowers(
            accounts: try Array(mutual.field("accounts")).map(decodeProfileSummary),
            hasMore: try mutual.bool("has_more")
         )
      }
   }

   // profiles.suggested, the accounts shown beside one profile.
   func similarAccounts(_ handle: Handle, userID: String) async throws(EngineError) -> EngineResult<[Engine.UserSummary]> {
      try await submit(handle, "profiles.suggested", [userID]) { accounts in
         try Array(accounts).map(decodeProfileSummary)
      }
   }

   func savedCollections(_ handle: Handle) async throws(EngineError) -> EngineResult<Engine.SavedCollections> {
      try await submit(handle, "account.collections", []) { saved in
         var unknownKinds: [String] = []

         let collections = try Array(saved.field("collections")).compactMap { collection -> Engine.SavedCollection? in
            let kindValue = try collection.field("kind").string("value")

            guard let kind = Engine.SavedCollection.Kind(rawValue: kindValue) else {
               unknownKinds.append(kindValue)
               return nil
            }

            let coverURLs = try Array(collection.field("covers")).flatMap { cover in
               Array(try cover.field("image_urls")).compactMap { String($0) }
            }

            return Engine.SavedCollection(
               id: try collection.string("id"),
               name: try collection.string("name"),
               kind: kind,
               mediaCount: try collection.optionalInt("media_count"),
               coverURLs: coverURLs
            )
         }

         if !unknownKinds.isEmpty {
            logger.log("collections skipped \(unknownKinds.count) of kinds the Swift mirror lacks: \(unknownKinds.joined(separator: ","), privacy: .public)")
         }

         return Engine.SavedCollections(collections: collections, hasMore: try saved.bool("has_more"))
      }
   }

   func hasNewPosts(_ handle: Handle) async throws(EngineError) -> EngineResult<Bool> {
      try await submit(handle, "feeds.has_new_posts", []) { answer in
         guard let hasNew = Bool(answer) else {
            throw DecodeFailure(path: "has_new_posts")
         }

         return hasNew
      }
   }

   func searchTop(_ handle: Handle, query: String) async throws(EngineError) -> EngineResult<[Engine.SearchResult]> {
      try await submit(handle, "search.top", [query]) { top in
         var unknownKinds: [String] = []

         let decoded = try Array(top.field("results")).compactMap { row -> Engine.SearchResult? in
            let kindValue = try row.field("kind").string("value")

            guard let kind = Engine.SearchResult.Kind(rawValue: kindValue) else {
               unknownKinds.append(kindValue)
               return nil
            }

            return Engine.SearchResult(
               kind: kind,
               account: try row.optionalField("account").map(decodeProfileSummary),
               keyword: try row.optionalString("keyword"),
               position: try row.optionalInt("position")
            )
         }

         if !unknownKinds.isEmpty {
            logger.log("top search skipped \(unknownKinds.count) rows of kinds the Swift mirror lacks: \(unknownKinds.joined(separator: ","), privacy: .public)")
         }

         return decoded
      }
   }

   // SearchPost carries the same five tile fields as Post, under the same names.
   func searchKeyword(_ handle: Handle, query: String) async throws(EngineError) -> EngineResult<Engine.KeywordResults> {
      try await submit(handle, "search.keyword", [query]) { results in
         return Engine.KeywordResults(posts: try Array(results.field("posts")).map(decodeTile), hasMore: try results.bool("has_more"))
      }
   }

   func hashtag(_ handle: Handle, name: String) async throws(EngineError) -> EngineResult<Engine.HashtagHeader> {
      try await submit(handle, "search.hashtag", [name]) { header in
         return Engine.HashtagHeader(id: try header.string("id"), name: try header.string("name"))
      }
   }

   func explorePosts(_ handle: Handle, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.Post>> {
      try await submit(handle, "feeds.explore_posts", keywords: ["after": cursor]) { page in
         return try decodePage(page) { try decodePost($0) }
      }
   }

   func audio(_ handle: Handle, audioID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.AudioPage> {
      try await submit(handle, "feeds.audio", keywords: ["": audioID, "after": cursor]) { page in
         let audio = try page.optionalField("audio")

         return Engine.AudioPage(
            audio: try audio.map { model in
               Engine.MediaAudio(
                  audioID: try model.string("audio_id"),
                  title: try model.string("title"),
                  artist: try model.string("artist"),
                  isExplicit: try model.bool("is_explicit")
               )
            },
            clips: try Array(page.field("clips")).map { try decodePost($0) },
            clipsCount: try page.int("clips_count"),
            isRestricted: try page.bool("is_restricted"),
            hasNextPage: try page.bool("more_available"),
            endCursor: try page.optionalString("end_cursor")
         )
      }
   }

   func audioClips(_ handle: Handle, audioID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.Post>> {
      try await submit(handle, "feeds.audio_clips", keywords: ["": audioID, "after": cursor]) { page in
         return try decodePage(page) { try decodePost($0) }
      }
   }

   // MARK: Writes
   // A write that returns was accepted by the engine. Every refusal, the write stop, a
   // checkpoint and a revoked session arrive as the engine's exceptions and are mapped below.

   func like(_ handle: Handle, postPK: String) async throws(EngineError) -> EngineResult<Void> {
      try await submit(handle, "media.like", [postPK]) { _ in }
   }

   func unlike(_ handle: Handle, postPK: String) async throws(EngineError) -> EngineResult<Void> {
      try await submit(handle, "media.unlike", [postPK]) { _ in }
   }

   func comment(_ handle: Handle, postPK: String, text: String) async throws(EngineError) -> EngineResult<Engine.Comment> {
      try await submit(handle, "media.comment", [postPK, text]) { created in
         return try decodeComment(created)
      }
   }

   func deleteComment(_ handle: Handle, postPK: String, commentID: String) async throws(EngineError) -> EngineResult<Void> {
      try await submit(handle, "media.delete_comment", [postPK, commentID]) { _ in }
   }

   func deletePost(_ handle: Handle, postPK: String, code: String) async throws(EngineError) -> EngineResult<Void> {
      try await submit(handle, "media.delete_post", [postPK, code]) { _ in }
   }

   func publishPhoto(_ handle: Handle, imagePath: String, caption: String) async throws(EngineError) -> EngineResult<Engine.PublishedPost> {
      try await submit(handle, "media.publish_photo", keywords: ["": imagePath, "caption": caption]) { published in
         return try decodePublishedPost(published)
      }
   }

   func publishCarousel(_ handle: Handle, imagePaths: [String], caption: String) async throws(EngineError) -> EngineResult<Engine.PublishedPost> {
      try await submit(handle, "media.publish_carousel", keywords: ["": imagePaths, "caption": caption]) { published in
         return try decodePublishedPost(published)
      }
   }

   func follow(_ handle: Handle, userID: String) async throws(EngineError) -> EngineResult<Void> {
      try await submit(handle, "social.follow", [userID]) { _ in }
   }

   func unfollow(_ handle: Handle, userID: String) async throws(EngineError) -> EngineResult<Void> {
      try await submit(handle, "social.unfollow", [userID]) { _ in }
   }

   func send(_ handle: Handle, threadFBID: String, text: String) async throws(EngineError) -> EngineResult<Engine.SentMessage> {
      try await submit(handle, "direct.send", [threadFBID, text]) { sent in
         return Engine.SentMessage(
            id: try sent.string("id"),
            offlineThreadingID: try sent.string("offline_threading_id"),
            threadFBID: try sent.string("thread_fbid"),
            sentAt: try sent.date("sent_at")
         )
      }
   }

   func unsend(_ handle: Handle, threadFBID: String, messageID: String) async throws(EngineError) -> EngineResult<Void> {
      try await submit(handle, "direct.unsend", [threadFBID, messageID]) { _ in }
   }

   func setNote(_ handle: Handle, text: String, audience: Engine.NoteAudience) async throws(EngineError) -> EngineResult<Engine.Note> {
      try await submitWithModule(handle, "direct.set_note") { module in
         let engineAudience = try module.NoteAudience.throwing.dynamicallyCall(withArguments: [audience.rawValue])
         return [("", text), ("audience", engineAudience)]
      } decode: { note, _ in
         let noteAudience = try note.int("audience")

         guard let decodedAudience = Engine.NoteAudience(rawValue: noteAudience) else {
            throw DecodeFailure(path: "Note.audience")
         }

         return try decodeNote(note, audience: decodedAudience)
      }
   }

   func deleteNote(_ handle: Handle, noteID: String) async throws(EngineError) -> EngineResult<Void> {
      try await submit(handle, "direct.delete_note", [noteID]) { _ in }
   }

   // Marks one item of a reel read earlier in this session. The engine refuses an item that is
   // not in the reel before sending anything.
   func markStorySeen(_ handle: Handle, reelID: String, itemID: String) async throws(EngineError) -> EngineResult<Void> {
      try await submitWithModule(handle, "stories.mark_seen") { _ in
         guard let reel = storyReels[handle]?[reelID] else {
            throw StoryReelNotRead()
         }

         let items = try Array(reel.field("items"))

         guard let item = try items.first(where: { try $0.string("id") == itemID }) else {
            throw StoryReelNotRead()
         }

         return [("", item), ("reel", reel)]
      } decode: { _, _ in }
   }

   // MARK: Events

   // client.events() without on_event, then start(). Swift drains the listener's buffer and
   // never hands Python a closure (rule 3).
   func startEvents(_ handle: Handle, since messageID: String?) throws(EngineError) -> EngineResult<Bool> {
      stopEvents(handle)

      let started: Outcome<Bool> = PythonRuntime.withGIL(on: self) {
         guard let client = clients[handle] else {
            return .failure(.authenticationFailed)
         }

         return capture { _ in
            let listener = try client.events.throwing.dynamicallyCall(withKeywordArguments: ["since": messageID])
            try listener.start.throwing.dynamicallyCall(withArguments: [])
            listeners[handle] = listener
            return true
         }
      }

      return try resolve(started)
   }

   func drainEvents(_ handle: Handle) -> [Engine.Event] {
      PythonRuntime.withGIL(on: self) {
         guard let listener = listeners[handle] else {
            return []
         }

         let drained: Outcome<[Engine.Event]> = capture { _ in
            let batch = try listener.drain.throwing.dynamicallyCall(withArguments: [])
            return try Array(batch).map(decodeEvent)
         }

         switch drained {
            case .value(let events):
               return events

            case .checkpoint(let checkpoint):
               return [.listenerStopped(.checkpoint(checkpoint))]

            case .failure(let error):
               return [.listenerStopped(.error(error))]
         }
      }
   }

   // stop() is idempotent and must run even after a failure, to release the loop thread.
   func stopEvents(_ handle: Handle) {
      PythonRuntime.withGIL(on: self) {
         if let listener = listeners.removeValue(forKey: handle) {
            _ = try? listener.stop.throwing.dynamicallyCall(withArguments: [])
         }
      }
   }

   // MARK: Calling and mapping

   // Every SyncClient call goes through dumpstagram.pending.submit, which starts it on the
   // engine's loop thread and returns at once. The call is then polled with done() and
   // collected with result(), each step a short hold of the GIL, and between polls this actor is
   // free. So a write waiting out the engine's write spacing, about 30 s under PARITY, no longer
   // holds every other account's calls behind it. Calls on one account still depart one at a
   // time in the order the engine's pacer admits them. Nothing here cancels a call, so a write
   // is never abandoned half known, and nothing retries one.
   private typealias Arguments = [(key: String, value: PythonConvertible)]

   enum ClientRoute: Sendable {
      case primary
      case nonPersonalisedSearch
   }

   private func submit<Value: Sendable>(
      _ handle: Handle,
      _ operation: String,
      _ arguments: [PythonConvertible] = [],
      through route: ClientRoute = .primary,
      _ decode: (PythonObject) throws -> Value
   ) async throws(EngineError) -> EngineResult<Value> {
      try await submitted(handle, operation, route: route) { _ in
         arguments.map { (key: "", value: $0) }
      } decode: { answer, _ in
         try decode(answer)
      }
   }

   private func submit<Value: Sendable>(
      _ handle: Handle,
      _ operation: String,
      keywords: KeyValuePairs<String, PythonConvertible>,
      _ decode: (PythonObject) throws -> Value
   ) async throws(EngineError) -> EngineResult<Value> {
      try await submitted(handle, operation, route: .primary) { _ in
         keywords.map { (key: $0.key, value: $0.value) }
      } decode: { answer, _ in
         try decode(answer)
      }
   }

   // For a call whose arguments are engine values built from the module, such as a NoteAudience.
   private func submitWithModule<Value: Sendable>(
      _ handle: Handle,
      _ operation: String,
      arguments: (PythonObject) throws -> Arguments,
      decode: (PythonObject, PythonObject) throws -> Value
   ) async throws(EngineError) -> EngineResult<Value> {
      try await submitted(handle, operation, route: .primary, arguments: arguments, decode: decode)
   }

   private func submitted<Value: Sendable>(
      _ handle: Handle,
      _ operation: String,
      route: ClientRoute,
      arguments: (PythonObject) throws -> Arguments,
      decode: (PythonObject, PythonObject) throws -> Value
   ) async throws(EngineError) -> EngineResult<Value> {
      // Calls that start together on a session with no page token each load the bootstrap
      // document (dumpstagram.pending). Until one call on this client has answered, the next
      // waits for it instead of starting beside it.
      while coldCalls.contains(handle) {
         await Self.pause(milliseconds: 20)
      }

      let isCold = !warmHandles.contains(handle)
      if isCold {
         coldCalls.insert(handle)
      }

      defer {
         if isCold {
            coldCalls.remove(handle)
         }
      }

      let callID = nextCallID
      nextCallID += 1

      let started: Outcome<Bool> = PythonRuntime.withGIL(on: self) {
         guard let client = clients[handle] else {
            return .failure(.authenticationFailed)
         }

         return capture { module in
            guard let pending = pendingModule else {
               throw DecodeFailure(path: "dumpstagram.pending")
            }

            let target = try target(of: client, for: handle, route: route, module: module)
            let callArguments: Arguments = [(key: "", value: target), (key: "", value: operation)] + (try arguments(module))
            inFlight[callID] = try pending.submit.throwing.dynamicallyCall(withKeywordArguments: callArguments)
            return true
         }
      }

      if case .checkpoint(let checkpoint) = try resolve(started) {
         return .checkpoint(checkpoint)
      }

      var interval = 5
      while !isFinished(callID) {
         await Self.pause(milliseconds: interval)
         interval = min(interval * 2, 100)
      }

      let outcome: Outcome<Value> = PythonRuntime.withGIL(on: self) {
         guard let call = inFlight.removeValue(forKey: callID) else {
            return .failure(.upstreamRejected(code: EngineError.bridgeFailureCode))
         }

         return capture { module in
            try decode(try call.result.throwing.dynamicallyCall(withArguments: []), module)
         }
      }

      if isCold, case .value = outcome {
         warmHandles.insert(handle)
      }

      return try resolve(outcome)
   }

   // done() never blocks. A call that can no longer be asked counts as finished, so result()
   // reports what happened to it.
   private func isFinished(_ callID: Int) -> Bool {
      PythonRuntime.withGIL(on: self) {
         guard let call = inFlight[callID], let isDone = try? call.done.throwing.dynamicallyCall(withArguments: []) else {
            return true
         }

         return Bool(isDone) ?? true
      }
   }

   private func target(of client: PythonObject, for handle: Handle, route: ClientRoute, module: PythonObject) throws -> PythonObject {
      switch route {
         case .primary:
            return client

         case .nonPersonalisedSearch:
            if let scoped = searchClients[handle] {
               return scoped
            }

            let behavior = try Python.import("dataclasses").replace.throwing.dynamicallyCall(withKeywordArguments: [
               "": client.field("behavior"),
               "typeahead_route": module.field("TypeaheadRoute").field("NON_PERSONALISED"),
            ])
            let scoped = try client.with_behavior.throwing.dynamicallyCall(withArguments: [behavior])

            searchClients[handle] = scoped
            return scoped
      }
   }

   // A wait that ignores task cancellation, because a call already started is always collected.
   private nonisolated static func pause(milliseconds: Int) async {
      await withCheckedContinuation { continuation in
         DispatchQueue.global().asyncAfter(deadline: .now() + .milliseconds(milliseconds)) {
            continuation.resume()
         }
      }
   }

   private func resolve<Value: Sendable>(_ outcome: Outcome<Value>) throws(EngineError) -> EngineResult<Value> {
      switch outcome {
         case .value(let value): return .value(value)
         case .checkpoint(let checkpoint): return .checkpoint(checkpoint)
         case .failure(let error): throw error
      }
   }

   // Runs a Python body with the GIL already held and turns whatever it raises into an
   // Outcome, so the exception object is released before the GIL is.
   private func capture<Value: Sendable>(_ body: (PythonObject) throws -> Value) -> Outcome<Value> {
      guard let module = dumpstagram else {
         return .failure(.upstreamRejected(code: EngineError.bridgeFailureCode))
      }

      do {
         return .value(try body(module))
      } catch let failure as DecodeFailure {
         logger.error("bridge could not decode \(failure.path, privacy: .public)")
         return .failure(.schemaChanged(path: "bridge:\(failure.path)"))
      } catch is StoryReelNotRead {
         return .failure(.notFound)
      } catch let failure as PythonError {
         return map(failure, module: module)
      } catch {
         logger.error("bridge failure outside Python, \(String(describing: type(of: error)), privacy: .public)")
         return .failure(.upstreamRejected(code: EngineError.bridgeFailureCode))
      }
   }

   private func map<Value: Sendable>(_ failure: PythonError, module: PythonObject) -> Outcome<Value> {
      guard case .exception(let exception, _) = failure else {
         logger.error("bridge call failed before reaching Python, \(String(describing: failure), privacy: .public)")
         return .failure(.upstreamRejected(code: EngineError.bridgeFailureCode))
      }

      return classify(exception, module: module)
   }

   private func classify<Value: Sendable>(_ exception: PythonObject, module: PythonObject) -> Outcome<Value> {
      let typeName = String(Python.type(exception).__name__) ?? "unknown"
      logTraceback(of: exception, typeName: typeName)

      func isInstance(_ className: String) -> Bool {
         guard let cls = module.checking[dynamicMember: className] else {
            return false
         }

         return Bool(Python.isinstance(exception, cls)) ?? false
      }

      func optionalString(_ name: String) -> String? {
         try? exception.optionalString(name)
      }

      if isInstance("CheckpointRequired") {
         return .checkpoint(Checkpoint(requiredAction: optionalString("required_action")))
      }

      if isInstance("AuthenticationFailed") {
         return .failure(.authenticationFailed)
      }

      if isInstance("RateLimited") {
         let retryAfter = exception.checking[dynamicMember: "retry_after"].flatMap { Double($0) }
         return .failure(.rateLimited(retryAfter: retryAfter))
      }

      if isInstance("OutcomeUnknown") {
         return .failure(.outcomeUnknown(operation: optionalString("operation")))
      }

      if isInstance("UpstreamRejected") {
         return .failure(.upstreamRejected(code: optionalString("code")))
      }

      if isInstance("NotFound") {
         return .failure(.notFound)
      }

      if isInstance("SchemaChanged") {
         return .failure(.schemaChanged(path: optionalString("path")))
      }

      if isInstance("TransportFailure") {
         return .failure(.transportFailure)
      }

      if isInstance("OperationCancelled") {
         return .failure(.operationCancelled)
      }

      return .failure(.upstreamRejected(code: EngineError.bridgeFailureCode))
   }

   // The engine redacts its own messages. The traceback still names internal paths, so it is
   // kept private in the unified log and never printed.
   private func logTraceback(of exception: PythonObject, typeName: String) {
      let formatted = (try? Python.import("traceback").format_exception.throwing.dynamicallyCall(withArguments: [exception]))
         .map { Array($0).compactMap { String($0) }.joined() } ?? ""

      logger.error("engine raised \(typeName, privacy: .public)\n\(formatted, privacy: .private)")
   }

   // MARK: Decoding

   private func decodePage<Item: Sendable>(_ page: PythonObject, _ decodeItem: (PythonObject) throws -> Item?) throws -> Engine.Page<Item> {
      let items = try Array(page.field("items")).compactMap(decodeItem)

      return Engine.Page(
         items: items,
         hasNextPage: try page.bool("has_next_page"),
         endCursor: try page.optionalString("end_cursor")
      )
   }

   private func keepStoryReel(_ reel: PythonObject, for handle: Handle) throws -> Engine.StoryReel {
      let decoded = try decodeStoryReel(reel)
      storyReels[handle, default: [:]][decoded.id] = reel
      return decoded
   }

   private func decodeStoryReel(_ reel: PythonObject) throws -> Engine.StoryReel {
      let owner = try reel.field("owner")

      return Engine.StoryReel(
         id: try reel.string("id"),
         ownerID: try owner.string("id"),
         ownerUsername: try owner.string("username"),
         title: try reel.optionalString("title"),
         latestItemAt: try reel.date("latest_item_at"),
         items: try Array(reel.field("items")).map { item in
            Engine.StoryItem(
               id: try item.string("id"),
               pk: try item.string("pk"),
               ownerID: try item.string("owner_id"),
               mediaKind: try decodeMediaKind(item),
               takenAt: try item.date("taken_at"),
               expiringAt: try item.date("expiring_at"),
               images: try Array(item.field("images")).map(decodeImage),
               videoDuration: try item.optionalDouble("video_duration"),
               canReply: try item.bool("can_reply")
            )
         }
      )
   }

   // StoryOwner has no full name, and its verified and private flags may be absent.
   private func decodeStoryOwner(_ owner: PythonObject) throws -> Engine.UserSummary {
      Engine.UserSummary(
         id: try owner.string("id"),
         username: try owner.string("username"),
         fullName: "",
         isVerified: try owner.optionalBool("is_verified") ?? false,
         isPrivate: try owner.optionalBool("is_private") ?? false,
         profilePicURL: try owner.string("profile_pic_url")
      )
   }

   private func decodeProfileSummary(_ summary: PythonObject) throws -> Engine.UserSummary {
      Engine.UserSummary(
         id: try summary.string("id"),
         username: try summary.string("username"),
         fullName: try summary.string("full_name"),
         isVerified: try summary.bool("is_verified"),
         isPrivate: try summary.optionalBool("is_private") ?? false,
         profilePicURL: try summary.string("profile_pic_url")
      )
   }

   // Post, ReelThumbnail, PostThumbnail and SearchPost all carry these fields under the same names.
   private func decodeTile(_ post: PythonObject) throws -> Engine.GridTile {
      Engine.GridTile(
         pk: try post.string("pk"),
         code: try post.string("code"),
         kind: try decodeMediaKind(post),
         likeCount: try post.int("like_count"),
         commentCount: try post.int("comment_count"),
         images: try Array(post.field("images")).map(decodeImage)
      )
   }

   private func decodeImage(_ image: PythonObject) throws -> Engine.MediaImage {
      Engine.MediaImage(url: try image.string("url"), width: try image.int("width"), height: try image.int("height"))
   }

   private func decodeProfile(_ profile: PythonObject) throws -> Engine.Profile {
      let friendship = try profile.field("friendship_status")

      return Engine.Profile(
         id: try profile.string("id"),
         username: try profile.string("username"),
         fullName: try profile.string("full_name"),
         biography: try profile.string("biography"),
         category: try profile.optionalString("category"),
         externalURL: try profile.optionalString("external_url"),
         followerCount: try profile.int("follower_count"),
         followingCount: try profile.int("following_count"),
         mediaCount: try profile.int("media_count"),
         totalClipsCount: try profile.int("total_clips_count"),
         isPrivate: try profile.bool("is_private"),
         isVerified: try profile.bool("is_verified"),
         profilePicURL: try profile.string("profile_pic_url"),
         friendshipStatus: friendship.isNone ? nil : try decodeFriendship(friendship)
      )
   }

   private func decodeFriendship(_ status: PythonObject) throws -> Engine.FriendshipStatus {
      Engine.FriendshipStatus(
         following: try status.bool("following"),
         followedBy: try status.bool("followed_by"),
         outgoingRequest: try status.bool("outgoing_request"),
         incomingRequest: try status.bool("incoming_request"),
         blocking: try status.bool("blocking"),
         muting: try status.bool("muting"),
         isBestie: try status.bool("is_bestie"),
         isRestricted: try status.bool("is_restricted")
      )
   }

   // Post and PostDetail share every field read here except is_seen, which PostDetail lacks.
   private func decodePost(_ post: PythonObject, carriesSeenFlag: Bool = true) throws -> Engine.Post {
      let author = try post.field("author")
      let location = try post.optionalField("location")
      let audio = try post.optionalField("audio")

      // Post carries audio_id beside its audio model, PostDetail only the model.
      let bareAudioID = carriesSeenFlag ? try post.optionalString("audio_id") : nil
      let audioID = try audio?.string("audio_id") ?? bareAudioID

      return Engine.Post(
         id: try post.string("id"),
         pk: try post.string("pk"),
         code: try post.string("code"),
         author: Engine.PostAuthor(
            id: try author.string("id"),
            username: try author.string("username"),
            fullName: try author.string("full_name"),
            profilePicURL: try author.string("profile_pic_url"),
            isPrivate: try author.bool("is_private"),
            isVerified: try author.bool("is_verified"),
            isFollowing: try author.optionalBool("is_following")
         ),
         caption: try post.optionalString("caption"),
         takenAt: try post.date("taken_at"),
         likeCount: try post.int("like_count"),
         commentCount: try post.int("comment_count"),
         hasLiked: try post.bool("has_liked"),
         isSeen: carriesSeenFlag ? try post.bool("is_seen") : nil,
         mediaKind: try decodeMediaKind(post),
         images: try Array(post.field("images")).map(decodeImage),
         carouselMediaCount: try post.optionalInt("carousel_media_count"),
         accessibilityCaption: try post.optionalString("accessibility_caption"),
         likeAndViewCountsDisabled: try post.bool("like_and_view_counts_disabled"),
         location: try location.map { Engine.Location(id: try $0.string("id"), name: try $0.string("name")) },
         hasSaved: nil,
         commentsDisabled: nil,
         videos: try Array(post.field("videos")).map(decodeVideo),
         videoDuration: try post.optionalDouble("video_duration"),
         carouselChildren: try Array(post.field("carousel_children")).map { child in
            Engine.CarouselChild(
               id: try child.string("id"),
               pk: try child.string("pk"),
               mediaKind: try decodeMediaKind(child),
               images: try Array(child.field("images")).map(decodeImage),
               videos: try Array(child.field("videos")).map(decodeVideo),
               videoDuration: try child.optionalDouble("video_duration")
            )
         },
         audioID: audioID,
         audioTitle: try audio?.string("title")
      )
   }

   private func decodeVideo(_ video: PythonObject) throws -> Engine.VideoRendition {
      Engine.VideoRendition(
         url: try video.string("url"),
         width: try video.int("width"),
         height: try video.int("height"),
         versionType: try video.int("version_type")
      )
   }

   private func decodeComment(_ comment: PythonObject) throws -> Engine.Comment {
      let author = try comment.field("author")

      return Engine.Comment(
         id: try comment.string("id"),
         author: Engine.CommentAuthor(
            id: try author.string("id"),
            username: try author.string("username"),
            isVerified: try author.bool("is_verified"),
            profilePicURL: try author.string("profile_pic_url")
         ),
         text: try comment.string("text"),
         createdAt: try comment.date("created_at"),
         likeCount: try comment.optionalInt("like_count"),
         hasLiked: try comment.optionalBool("has_liked"),
         parentCommentID: try comment.optionalString("parent_comment_id"),
         replyCount: try comment.optionalInt("reply_count")
      )
   }

   private func decodePublishedPost(_ published: PythonObject) throws -> Engine.PublishedPost {
      Engine.PublishedPost(
         id: try published.string("id"),
         pk: try published.string("pk"),
         code: try published.string("code"),
         takenAt: try published.date("taken_at")
      )
   }

   private func decodeMessage(_ message: PythonObject) throws -> Engine.Message {
      let sender = try message.field("sender")

      return Engine.Message(
         id: try message.string("id"),
         threadFBID: try message.string("thread_fbid"),
         sender: Engine.MessageSender(
            fbid: try sender.string("fbid"),
            igid: try sender.optionalString("igid"),
            name: try sender.optionalString("name")
         ),
         text: try message.optionalString("text"),
         sentAt: try message.date("sent_at"),
         contentType: try message.string("content_type"),
         reactions: try Array(message.field("reactions")).map { reaction in
            Engine.Reaction(
               emoji: try reaction.string("emoji"),
               senderFBID: try reaction.string("sender_fbid"),
               senderIGID: try reaction.optionalString("sender_igid"),
               isFromViewer: try reaction.optionalBool("is_from_viewer")
            )
         },
         repliedToMessageID: try message.optionalString("replied_to_message_id"),
         offlineThreadingID: try message.optionalString("offline_threading_id"),
         isFromViewer: try message.optionalBool("is_from_viewer"),
         kind: try message.field("kind").string("value"),
         media: try Array(message.field("media")).map(decodeMessageMedia)
      )
   }

   // Every model that carries media_type has the engine's media_kind beside it.
   private func decodeMediaKind(_ media: PythonObject) throws -> Engine.MediaKind {
      let kindValue = try media.field("media_kind").string("value")

      guard let kind = Engine.MediaKind(rawValue: kindValue) else {
         throw DecodeFailure(path: "media_kind \(kindValue)")
      }

      return kind
   }

   private func decodeMessageMedia(_ item: PythonObject) throws -> Engine.MessageMedia {
      let kindValue = try item.field("kind").string("value")

      guard let kind = Engine.MessageMedia.Kind(rawValue: kindValue) else {
         throw DecodeFailure(path: "MessageMedia.kind \(kindValue)")
      }

      return Engine.MessageMedia(
         kind: kind,
         url: try item.string("url"),
         previewURL: try item.optionalString("preview_url"),
         width: try item.optionalInt("width"),
         height: try item.optionalInt("height"),
         durationMS: try item.optionalInt("duration_ms")
      )
   }

   private func decodeThread(_ thread: PythonObject) throws -> Engine.DirectThread {
      Engine.DirectThread(
         threadFBID: try thread.string("thread_fbid"),
         title: try thread.string("title"),
         participants: try Array(thread.field("participants")).map { participant in
            Engine.ThreadParticipant(
               userID: try participant.string("user_id"),
               username: try participant.string("username"),
               fullName: try participant.string("full_name"),
               isVerified: try participant.bool("is_verified")
            )
         },
         isGroup: try thread.bool("is_group"),
         isUnread: try thread.bool("is_unread"),
         isMarkedUnread: try thread.bool("is_marked_unread"),
         isMuted: try thread.bool("is_muted"),
         isPinned: try thread.bool("is_pinned"),
         lastActivityAt: try thread.date("last_activity_at"),
         lastMessageID: try thread.optionalString("last_message_id"),
         snippet: try thread.optionalString("snippet")
      )
   }

   private func decodeNote(_ note: PythonObject, audience: Engine.NoteAudience) throws -> Engine.Note {
      Engine.Note(
         id: try note.string("id"),
         authorID: try note.string("author_id"),
         authorUsername: try note.optionalString("author_username"),
         text: try note.string("text"),
         audience: audience,
         createdAt: try note.date("created_at")
      )
   }

   private func decodeEvent(_ event: PythonObject) throws -> Engine.Event {
      guard let module = dumpstagram else {
         throw DecodeFailure(path: "dumpstagram")
      }

      func isInstance(_ className: String) throws -> Bool {
         let cls = try module.field(className)
         return Bool(Python.isinstance(event, cls)) ?? false
      }

      if try isInstance("NewMessage") {
         return .newMessage(try decodeMessage(event.field("message")))
      }

      if try isInstance("EventsDropped") {
         return .eventsDropped(count: try event.optionalInt("count"), threadFBID: try event.optionalString("thread_fbid"))
      }

      if try isInstance("ListenerStopped") {
         let stoppedBy: Outcome<Bool> = classify(try event.field("error"), module: module)

         switch stoppedBy {
            case .checkpoint(let checkpoint):
               return .listenerStopped(.checkpoint(checkpoint))

            case .failure(let error):
               return .listenerStopped(.error(error))

            case .value:
               return .listenerStopped(.error(.upstreamRejected(code: EngineError.bridgeFailureCode)))
         }
      }

      throw DecodeFailure(path: "Event.\(String(Python.type(event).__name__) ?? "unknown")")
   }
}

private struct DecodeFailure: Error {
   let path: String
}

private struct StoryReelNotRead: Error {}

private extension PythonObject {
   var isNone: Bool {
      Bool(Python.isinstance(self, Python.type(Python.None))) ?? false
   }

   func field(_ name: String) throws -> PythonObject {
      guard let value = checking[dynamicMember: name] else {
         throw DecodeFailure(path: name)
      }

      return value
   }

   func optionalField(_ name: String) throws -> PythonObject? {
      let value = try field(name)
      return value.isNone ? nil : value
   }

   func string(_ name: String) throws -> String {
      guard let value = String(try field(name)) else {
         throw DecodeFailure(path: name)
      }

      return value
   }

   func optionalString(_ name: String) throws -> String? {
      guard let value = try optionalField(name) else {
         return nil
      }

      guard let decoded = String(value) else {
         throw DecodeFailure(path: name)
      }

      return decoded
   }

   func int(_ name: String) throws -> Int {
      guard let value = Int(try field(name)) else {
         throw DecodeFailure(path: name)
      }

      return value
   }

   func optionalInt(_ name: String) throws -> Int? {
      guard let value = try optionalField(name) else {
         return nil
      }

      guard let decoded = Int(value) else {
         throw DecodeFailure(path: name)
      }

      return decoded
   }

   func optionalDouble(_ name: String) throws -> Double? {
      guard let value = try optionalField(name) else {
         return nil
      }

      guard let decoded = Double(value) else {
         throw DecodeFailure(path: name)
      }

      return decoded
   }

   func bool(_ name: String) throws -> Bool {
      guard let value = Bool(try field(name)) else {
         throw DecodeFailure(path: name)
      }

      return value
   }

   func optionalBool(_ name: String) throws -> Bool? {
      guard let value = try optionalField(name) else {
         return nil
      }

      guard let decoded = Bool(value) else {
         throw DecodeFailure(path: name)
      }

      return decoded
   }

   func optionalDate(_ name: String) throws -> Date? {
      guard try optionalField(name) != nil else {
         return nil
      }

      return try date(name)
   }

   func date(_ name: String) throws -> Date {
      let value = try field(name)

      guard let seconds = Double(try value.timestamp.throwing.dynamicallyCall(withArguments: [])) else {
         throw DecodeFailure(path: name)
      }

      return Date(timeIntervalSince1970: seconds)
   }
}
