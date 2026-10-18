import Foundation
import os
@preconcurrency import PythonKit

// The one owner of Python in the app (docs/bridge/threading-and-gil.md, rule 1). Every
// PythonObject is created, read and released on this actor, inside PythonRuntime.withGIL, and
// every method returns Swift values only. Exceptions are mapped here, onto EngineResult and
// EngineError, and never travel outward. Nothing here retries or paces: the engine does both.
//
// The actor runs on its own serial dispatch queue, because a SyncClient call blocks its thread
// while the engine's loop thread does the work, and that must not park a thread of Swift's
// cooperative pool.
//
// Known limitation, an engine gap: every call holds this actor until the engine answers,
// including the time the engine's pacer waits before a write (about 30 s under PARITY), so a
// story seen mark or a reel read delays every later call on every account. The public surface
// offers no way to submit a call and poll for its result: SyncClient methods block, and
// AsyncClient returns coroutines that need an event loop running on some thread, which the
// app would have to own as a second Python thread. The engine's own loop thread is private.
// The fix belongs in the engine, as a non-blocking submit entry point on the public surface.
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
   private var clients: [Handle: PythonObject] = [:]
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

         if let client = clients.removeValue(forKey: handle) {
            _ = try? client.close.throwing.dynamicallyCall(withArguments: [])
         }
      }
   }

   // MARK: Reads

   func profile(_ handle: Handle, username: String) throws(EngineError) -> EngineResult<Engine.Profile> {
      try call(handle) { client in
         let profile = try client.profile.throwing.dynamicallyCall(withArguments: [username])
         return try decodeProfile(profile)
      }
   }

   func profile(_ handle: Handle, id userID: String) throws(EngineError) -> EngineResult<Engine.Profile> {
      try call(handle) { client in
         let profile = try client.profile_by_id.throwing.dynamicallyCall(withArguments: [userID])
         return try decodeProfile(profile)
      }
   }

   func feed(_ handle: Handle, after cursor: String?) throws(EngineError) -> EngineResult<Engine.Page<Engine.FeedItem>> {
      try call(handle) { client in
         let page = try client.feed.throwing.dynamicallyCall(withKeywordArguments: ["after": cursor])
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

   func comments(_ handle: Handle, postPK: String, after cursor: String?) throws(EngineError) -> EngineResult<Engine.Page<Engine.Comment>> {
      try call(handle) { client in
         let page = try client.media.comments.throwing.dynamicallyCall(withKeywordArguments: ["": postPK, "after": cursor])
         return try decodePage(page, decodeComment)
      }
   }

   // media.by_code answers a PostDetail, which has every Post field the app reads except
   // is_seen. Six requests under the default Behavior.
   func post(_ handle: Handle, code: String) throws(EngineError) -> EngineResult<Engine.Post> {
      try call(handle) { client in
         let detail = try client.media.by_code.throwing.dynamicallyCall(withArguments: [code])
         return try decodePost(detail, carriesSeenFlag: false)
      }
   }

   // media.download takes the engine's own MediaImage. The rendition is rebuilt from the values
   // the engine gave when the post was read, and the engine fetches its URL from the CDN. The
   // person already chose to replace a file at the destination in the save panel.
   func download(_ handle: Handle, image: Engine.MediaImage, to destination: URL) throws(EngineError) -> EngineResult<URL> {
      try callWithModule(handle) { client, module in
         let rendition = try module.MediaImage.throwing.dynamicallyCall(withKeywordArguments: [
            "url": image.url,
            "width": image.width,
            "height": image.height,
         ])

         let written = try client.media.download.throwing.dynamicallyCall(withKeywordArguments: [
            "": rendition,
            "": destination.path,
            "overwrite": true,
         ])

         guard let path = String(Python.str(written)) else {
            throw DecodeFailure(path: "download.path")
         }

         return URL(fileURLWithPath: path)
      }
   }

   func inbox(_ handle: Handle, after cursor: String?) throws(EngineError) -> EngineResult<Engine.Page<Engine.DirectThread>> {
      try call(handle) { client in
         let page = try client.direct.inbox.throwing.dynamicallyCall(withKeywordArguments: ["after": cursor])
         return try decodePage(page, decodeThread)
      }
   }

   func messages(_ handle: Handle, threadFBID: String, after cursor: String?) throws(EngineError) -> EngineResult<Engine.Page<Engine.Message>> {
      try call(handle) { client in
         let page = try client.direct.messages.throwing.dynamicallyCall(withKeywordArguments: ["": threadFBID, "after": cursor])
         return try decodePage(page, decodeMessage)
      }
   }

   func messageRequests(_ handle: Handle) throws(EngineError) -> EngineResult<Engine.MessageRequests> {
      try call(handle) { client in
         let requests = try client.direct.message_requests.throwing.dynamicallyCall(withArguments: [])

         return Engine.MessageRequests(
            pending: try Array(requests.field("pending")).map(decodeThread),
            spam: try Array(requests.field("spam")).map(decodeThread)
         )
      }
   }

   func unreadCounts(_ handle: Handle) throws(EngineError) -> EngineResult<Engine.UnreadCounts> {
      try call(handle) { client in
         let counts = try client.direct.unread_counts.throwing.dynamicallyCall(withArguments: [])
         return Engine.UnreadCounts(inbox: try counts.int("inbox"), pending: try counts.int("pending"))
      }
   }

   func inboxLoad(_ handle: Handle) throws(EngineError) -> EngineResult<Engine.InboxLoad> {
      try call(handle) { client in
         let load = try client.direct.inbox_load.throwing.dynamicallyCall(withArguments: [])
         let counts = try load.field("unread_counts")

         return Engine.InboxLoad(
            threads: try decodePage(load.field("threads"), decodeThread),
            notes: try decodeNotes(load.field("notes")),
            unreadCounts: Engine.UnreadCounts(inbox: try counts.int("inbox"), pending: try counts.int("pending"))
         )
      }
   }

   func notes(_ handle: Handle) throws(EngineError) -> EngineResult<[Engine.Note]> {
      try call(handle) { client in
         try decodeNotes(client.direct.notes.throwing.dynamicallyCall(withArguments: []))
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

   func storiesTray(_ handle: Handle) throws(EngineError) -> EngineResult<[Engine.StoryTrayEntry]> {
      try call(handle) { client in
         let tray = try client.stories.tray.throwing.dynamicallyCall(withArguments: [])

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
   func storyReel(_ handle: Handle, userID: String) throws(EngineError) -> EngineResult<Engine.StoryReel?> {
      try call(handle) { client in
         let reel = try client.stories.reel.throwing.dynamicallyCall(withArguments: [userID])

         guard !reel.isNone else {
            return nil
         }

         return try keepStoryReel(reel, for: handle)
      }
   }

   func highlightReel(_ handle: Handle, highlightID: String) throws(EngineError) -> EngineResult<Engine.StoryReel> {
      try call(handle) { client in
         let reel = try client.stories.highlight.throwing.dynamicallyCall(withArguments: [highlightID])
         return try keepStoryReel(reel, for: handle)
      }
   }

   func highlights(_ handle: Handle, userID: String) throws(EngineError) -> EngineResult<[Engine.Highlight]> {
      try call(handle) { client in
         let tray = try client.profiles.highlights.throwing.dynamicallyCall(withArguments: [userID])

         return try Array(tray.field("highlights")).map { highlight in
            Engine.Highlight(id: try highlight.string("id"), title: try highlight.string("title"), itemCount: nil)
         }
      }
   }

   func profilePosts(_ handle: Handle, username: String, after cursor: String?) throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try call(handle) { client in
         let page = try client.profiles.posts.throwing.dynamicallyCall(withKeywordArguments: ["": username, "after": cursor])
         return try decodePage(page, decodeTile)
      }
   }

   // The reels, tagged and saved reads answer one page with has_more and take no cursor, so a
   // page from them never has an end cursor.
   func profileReelsPage(_ handle: Handle, userID: String) throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try call(handle) { client in
         let reels = try client.profiles.reels.throwing.dynamicallyCall(withArguments: [userID])
         return Engine.Page(items: try Array(reels.field("reels")).map(decodeTile), hasNextPage: try reels.bool("has_more"), endCursor: nil)
      }
   }

   func taggedPostsPage(_ handle: Handle, userID: String) throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try call(handle) { client in
         let tagged = try client.profiles.tagged.throwing.dynamicallyCall(withArguments: [userID])
         return Engine.Page(items: try Array(tagged.field("posts")).map(decodeTile), hasNextPage: try tagged.bool("has_more"), endCursor: nil)
      }
   }

   // SavedPost has no comment_count, so its tiles carry nil rather than a zero.
   func savedPostsPage(_ handle: Handle) throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try call(handle) { client in
         let saved = try client.account.saved.throwing.dynamicallyCall(withArguments: [])

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

   func profileReels(_ handle: Handle, userID: String) throws(EngineError) -> EngineResult<[Engine.GridTile]> {
      Self.items(of: try profileReelsPage(handle, userID: userID))
   }

   func taggedPosts(_ handle: Handle, userID: String) throws(EngineError) -> EngineResult<[Engine.GridTile]> {
      Self.items(of: try taggedPostsPage(handle, userID: userID))
   }

   func savedPosts(_ handle: Handle) throws(EngineError) -> EngineResult<[Engine.GridTile]> {
      Self.items(of: try savedPostsPage(handle))
   }

   private static func items<Item: Sendable>(of result: EngineResult<Engine.Page<Item>>) -> EngineResult<[Item]> {
      switch result {
         case .value(let page): .value(page.items)
         case .checkpoint(let checkpoint): .checkpoint(checkpoint)
      }
   }

   func followers(_ handle: Handle, userID: String, after cursor: String?) throws(EngineError) -> EngineResult<Engine.Page<Engine.UserSummary>> {
      try call(handle) { client in
         let page = try client.profiles.followers.throwing.dynamicallyCall(withKeywordArguments: ["": userID, "after": cursor])
         return try decodePage(page, decodeProfileSummary)
      }
   }

   func following(_ handle: Handle, userID: String, after cursor: String?) throws(EngineError) -> EngineResult<Engine.Page<Engine.UserSummary>> {
      try call(handle) { client in
         let page = try client.profiles.following.throwing.dynamicallyCall(withKeywordArguments: ["": userID, "after": cursor])
         return try decodePage(page, decodeProfileSummary)
      }
   }

   // Close friends and blocked accounts are two engine reads. The engine has no muted list.
   func relationships(_ handle: Handle) throws(EngineError) -> EngineResult<Engine.Relationships> {
      try call(handle) { client in
         let closeFriends = try Array(client.account.close_friends.throwing.dynamicallyCall(withArguments: [])).map(decodeProfileSummary)

         let blocked = try Array(client.account.blocked.throwing.dynamicallyCall(withArguments: [])).map { account in
            Engine.UserSummary(
               id: try account.string("id"),
               username: try account.string("username"),
               fullName: "",
               isVerified: try account.bool("is_verified"),
               isPrivate: false,
               profilePicURL: try account.string("profile_pic_url")
            )
         }

         return Engine.Relationships(
            closeFriendIDs: closeFriends.map(\.id),
            blockedIDs: blocked.map(\.id),
            mutedIDs: [],
            closeFriends: closeFriends,
            blocked: blocked,
            isMutedListKnown: false
         )
      }
   }

   // search.accounts sends the typeahead the client's Behavior names. With personalised false
   // the call goes through a client scoped to the non-personalised route, which shares this
   // client's session and pacer and is closed again before the GIL is released.
   func searchAccounts(_ handle: Handle, query: String, personalised: Bool) throws(EngineError) -> EngineResult<[Engine.UserSummary]> {
      try callWithModule(handle) { client, module in
         guard !personalised else {
            return try Array(client.search.accounts.throwing.dynamicallyCall(withArguments: [query])).map(decodeProfileSummary)
         }

         let behavior = try Python.import("dataclasses").replace.throwing.dynamicallyCall(withKeywordArguments: [
            "": client.field("behavior"),
            "typeahead_route": module.field("TypeaheadRoute").field("NON_PERSONALISED"),
         ])
         let scoped = try client.with_behavior.throwing.dynamicallyCall(withArguments: [behavior])
         defer { _ = try? scoped.close.throwing.dynamicallyCall(withArguments: []) }

         return try Array(scoped.search.accounts.throwing.dynamicallyCall(withArguments: [query])).map(decodeProfileSummary)
      }
   }

   func recentSearches(_ handle: Handle) throws(EngineError) -> EngineResult<[Engine.RecentSearch]> {
      try call(handle) { client in
         let entries = try client.search.recent.throwing.dynamicallyCall(withArguments: [])
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
   func explore(_ handle: Handle, after cursor: String?) throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try call(handle) { client in
         let grid = try client.feeds.explore.throwing.dynamicallyCall(withKeywordArguments: ["after": cursor])

         return Engine.Page(
            items: try Array(grid.field("posts")).map(decodeTile),
            hasNextPage: try grid.bool("more_available"),
            endCursor: try grid.optionalString("end_cursor")
         )
      }
   }

   // feeds.location reads the first grid page of a place by its Location.id. It returns no
   // cursor, so the page says whether more exist and nothing reads them.
   func placePosts(_ handle: Handle, placeID: String) throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try call(handle) { client in
         let posts = try client.feeds.location.throwing.dynamicallyCall(withArguments: [placeID])

         return Engine.Page(
            items: try Array(posts.field("posts")).map(decodeTile),
            hasNextPage: try posts.bool("has_more"),
            endCursor: nil
         )
      }
   }

   // The reels feed carries no play count, and its audio title is absent where a reel has no
   // audio model.
   func reels(_ handle: Handle, after cursor: String?) throws(EngineError) -> EngineResult<Engine.Page<Engine.Reel>> {
      try call(handle) { client in
         let page = try client.feeds.reels.throwing.dynamicallyCall(withKeywordArguments: ["after": cursor])

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
   func activityFeed(_ handle: Handle) throws(EngineError) -> EngineResult<Engine.ActivityFeed> {
      try call(handle) { client in
         let feed = try client.account.activity.throwing.dynamicallyCall(withArguments: [])

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
   func followRequests(_ handle: Handle) throws(EngineError) -> EngineResult<[Engine.UserSummary]> {
      try call(handle) { client in
         let requests = try client.account.follow_requests.throwing.dynamicallyCall(withArguments: [])
         return try Array(requests.field("accounts")).map(decodeProfileSummary)
      }
   }

   // SuggestedAccount.reason is dropped, since the rail has no place for it yet.
   func suggestedUsers(_ handle: Handle) throws(EngineError) -> EngineResult<[Engine.UserSummary]> {
      try call(handle) { client in
         let suggested = try client.profiles.suggested_for_you.throwing.dynamicallyCall(withArguments: [])
         return try Array(suggested).map { try decodeProfileSummary($0.field("account")) }
      }
   }

   // MARK: Reads added after 1.1.0

   // media.page loads the post page as a browser does, six requests under the default Behavior.
   func postPage(_ handle: Handle, code: String) throws(EngineError) -> EngineResult<Engine.PostPage> {
      try call(handle) { client in
         let page = try client.media.page.throwing.dynamicallyCall(withArguments: [code])

         return Engine.PostPage(
            post: try decodePost(page.field("post"), carriesSeenFlag: false),
            comments: try decodePage(page.field("comments"), decodeComment),
            authorGrid: try Array(page.field("author_grid")).map(decodeTile)
         )
      }
   }

   // media.by_id answers a thinner PostDetail than by_code, one request.
   func post(_ handle: Handle, pk: String) throws(EngineError) -> EngineResult<Engine.Post> {
      try call(handle) { client in
         let detail = try client.media.by_id.throwing.dynamicallyCall(withArguments: [pk])
         return try decodePost(detail, carriesSeenFlag: false)
      }
   }

   // A sample of the likers. The engine offers no cursor.
   func likers(_ handle: Handle, postPK: String) throws(EngineError) -> EngineResult<[Engine.UserSummary]> {
      try call(handle) { client in
         try Array(client.media.likers.throwing.dynamicallyCall(withArguments: [postPK])).map(decodeProfileSummary)
      }
   }

   func moreFromAuthor(_ handle: Handle, authorID: String) throws(EngineError) -> EngineResult<[Engine.GridTile]> {
      try call(handle) { client in
         try Array(client.media.more_from_author.throwing.dynamicallyCall(withArguments: [authorID])).map(decodeTile)
      }
   }

   func replies(_ handle: Handle, postPK: String, commentID: String, after cursor: String?) throws(EngineError) -> EngineResult<Engine.Page<Engine.Comment>> {
      try call(handle) { client in
         let page = try client.media.replies.throwing.dynamicallyCall(withKeywordArguments: ["": postPK, "": commentID, "after": cursor])
         return try decodePage(page, decodeComment)
      }
   }

   func mutualFollowers(_ handle: Handle, userID: String) throws(EngineError) -> EngineResult<Engine.MutualFollowers> {
      try call(handle) { client in
         let mutual = try client.profiles.mutual_followers.throwing.dynamicallyCall(withArguments: [userID])

         return Engine.MutualFollowers(
            accounts: try Array(mutual.field("accounts")).map(decodeProfileSummary),
            hasMore: try mutual.bool("has_more")
         )
      }
   }

   // profiles.suggested, the accounts shown beside one profile.
   func similarAccounts(_ handle: Handle, userID: String) throws(EngineError) -> EngineResult<[Engine.UserSummary]> {
      try call(handle) { client in
         try Array(client.profiles.suggested.throwing.dynamicallyCall(withArguments: [userID])).map(decodeProfileSummary)
      }
   }

   func savedCollections(_ handle: Handle) throws(EngineError) -> EngineResult<Engine.SavedCollections> {
      try call(handle) { client in
         let saved = try client.account.collections.throwing.dynamicallyCall(withArguments: [])
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

   func hasNewPosts(_ handle: Handle) throws(EngineError) -> EngineResult<Bool> {
      try call(handle) { client in
         let answer = try client.feeds.has_new_posts.throwing.dynamicallyCall(withArguments: [])

         guard let hasNew = Bool(answer) else {
            throw DecodeFailure(path: "has_new_posts")
         }

         return hasNew
      }
   }

   func searchTop(_ handle: Handle, query: String) throws(EngineError) -> EngineResult<[Engine.SearchResult]> {
      try call(handle) { client in
         let top = try client.search.top.throwing.dynamicallyCall(withArguments: [query])
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
   func searchKeyword(_ handle: Handle, query: String) throws(EngineError) -> EngineResult<Engine.KeywordResults> {
      try call(handle) { client in
         let results = try client.search.keyword.throwing.dynamicallyCall(withArguments: [query])
         return Engine.KeywordResults(posts: try Array(results.field("posts")).map(decodeTile), hasMore: try results.bool("has_more"))
      }
   }

   func hashtag(_ handle: Handle, name: String) throws(EngineError) -> EngineResult<Engine.HashtagHeader> {
      try call(handle) { client in
         let header = try client.search.hashtag.throwing.dynamicallyCall(withArguments: [name])
         return Engine.HashtagHeader(id: try header.string("id"), name: try header.string("name"))
      }
   }

   func explorePosts(_ handle: Handle, after cursor: String?) throws(EngineError) -> EngineResult<Engine.Page<Engine.Post>> {
      try call(handle) { client in
         let page = try client.feeds.explore_posts.throwing.dynamicallyCall(withKeywordArguments: ["after": cursor])
         return try decodePage(page) { try decodePost($0) }
      }
   }

   func audio(_ handle: Handle, audioID: String, after cursor: String?) throws(EngineError) -> EngineResult<Engine.AudioPage> {
      try call(handle) { client in
         let page = try client.feeds.audio.throwing.dynamicallyCall(withKeywordArguments: ["": audioID, "after": cursor])
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

   func audioClips(_ handle: Handle, audioID: String, after cursor: String?) throws(EngineError) -> EngineResult<Engine.Page<Engine.Post>> {
      try call(handle) { client in
         let page = try client.feeds.audio_clips.throwing.dynamicallyCall(withKeywordArguments: ["": audioID, "after": cursor])
         return try decodePage(page) { try decodePost($0) }
      }
   }

   // MARK: Writes
   // A write that returns was accepted by the engine. Every refusal, the write stop, a
   // checkpoint and a revoked session arrive as the engine's exceptions and are mapped below.

   func like(_ handle: Handle, postPK: String) throws(EngineError) -> EngineResult<Void> {
      try call(handle) { client in
         _ = try client.media.like.throwing.dynamicallyCall(withArguments: [postPK])
      }
   }

   func unlike(_ handle: Handle, postPK: String) throws(EngineError) -> EngineResult<Void> {
      try call(handle) { client in
         _ = try client.media.unlike.throwing.dynamicallyCall(withArguments: [postPK])
      }
   }

   func comment(_ handle: Handle, postPK: String, text: String) throws(EngineError) -> EngineResult<Engine.Comment> {
      try call(handle) { client in
         let created = try client.media.comment.throwing.dynamicallyCall(withArguments: [postPK, text])
         return try decodeComment(created)
      }
   }

   func deleteComment(_ handle: Handle, postPK: String, commentID: String) throws(EngineError) -> EngineResult<Void> {
      try call(handle) { client in
         _ = try client.media.delete_comment.throwing.dynamicallyCall(withArguments: [postPK, commentID])
      }
   }

   func deletePost(_ handle: Handle, postPK: String, code: String) throws(EngineError) -> EngineResult<Void> {
      try call(handle) { client in
         _ = try client.media.delete_post.throwing.dynamicallyCall(withArguments: [postPK, code])
      }
   }

   func publishPhoto(_ handle: Handle, imagePath: String, caption: String) throws(EngineError) -> EngineResult<Engine.PublishedPost> {
      try call(handle) { client in
         let published = try client.media.publish_photo.throwing.dynamicallyCall(withKeywordArguments: ["": imagePath, "caption": caption])
         return try decodePublishedPost(published)
      }
   }

   func publishCarousel(_ handle: Handle, imagePaths: [String], caption: String) throws(EngineError) -> EngineResult<Engine.PublishedPost> {
      try call(handle) { client in
         let published = try client.media.publish_carousel.throwing.dynamicallyCall(withKeywordArguments: ["": imagePaths, "caption": caption])
         return try decodePublishedPost(published)
      }
   }

   func follow(_ handle: Handle, userID: String) throws(EngineError) -> EngineResult<Void> {
      try call(handle) { client in
         _ = try client.social.follow.throwing.dynamicallyCall(withArguments: [userID])
      }
   }

   func unfollow(_ handle: Handle, userID: String) throws(EngineError) -> EngineResult<Void> {
      try call(handle) { client in
         _ = try client.social.unfollow.throwing.dynamicallyCall(withArguments: [userID])
      }
   }

   func send(_ handle: Handle, threadFBID: String, text: String) throws(EngineError) -> EngineResult<Engine.SentMessage> {
      try call(handle) { client in
         let sent = try client.direct.send.throwing.dynamicallyCall(withArguments: [threadFBID, text])

         return Engine.SentMessage(
            id: try sent.string("id"),
            offlineThreadingID: try sent.string("offline_threading_id"),
            threadFBID: try sent.string("thread_fbid"),
            sentAt: try sent.date("sent_at")
         )
      }
   }

   func unsend(_ handle: Handle, threadFBID: String, messageID: String) throws(EngineError) -> EngineResult<Void> {
      try call(handle) { client in
         _ = try client.direct.unsend.throwing.dynamicallyCall(withArguments: [threadFBID, messageID])
      }
   }

   func setNote(_ handle: Handle, text: String, audience: Engine.NoteAudience) throws(EngineError) -> EngineResult<Engine.Note> {
      try callWithModule(handle) { client, module in
         let engineAudience = try module.NoteAudience.throwing.dynamicallyCall(withArguments: [audience.rawValue])
         let note = try client.direct.set_note.throwing.dynamicallyCall(withKeywordArguments: ["": text, "audience": engineAudience])
         let noteAudience = try note.int("audience")

         guard let decodedAudience = Engine.NoteAudience(rawValue: noteAudience) else {
            throw DecodeFailure(path: "Note.audience")
         }

         return try decodeNote(note, audience: decodedAudience)
      }
   }

   func deleteNote(_ handle: Handle, noteID: String) throws(EngineError) -> EngineResult<Void> {
      try call(handle) { client in
         _ = try client.direct.delete_note.throwing.dynamicallyCall(withArguments: [noteID])
      }
   }

   // Marks one item of a reel read earlier in this session. The engine refuses an item that is
   // not in the reel before sending anything.
   func markStorySeen(_ handle: Handle, reelID: String, itemID: String) throws(EngineError) -> EngineResult<Void> {
      try call(handle) { client in
         guard let reel = storyReels[handle]?[reelID] else {
            throw StoryReelNotRead()
         }

         let items = try Array(reel.field("items"))

         guard let item = try items.first(where: { try $0.string("id") == itemID }) else {
            throw StoryReelNotRead()
         }

         _ = try client.stories.mark_seen.throwing.dynamicallyCall(withKeywordArguments: ["": item, "reel": reel])
      }
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

   private func call<Value: Sendable>(_ handle: Handle, _ body: (PythonObject) throws -> Value) throws(EngineError) -> EngineResult<Value> {
      try callWithModule(handle) { client, _ in try body(client) }
   }

   private func callWithModule<Value: Sendable>(_ handle: Handle, _ body: (PythonObject, PythonObject) throws -> Value) throws(EngineError) -> EngineResult<Value> {
      let outcome: Outcome<Value> = PythonRuntime.withGIL(on: self) {
         guard let client = clients[handle] else {
            return .failure(.authenticationFailed)
         }

         return capture { module in try body(client, module) }
      }

      return try resolve(outcome)
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
