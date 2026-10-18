import Foundation

extension DummyEngine {
   // MARK: Reads

   func feed(after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.FeedItem>> {
      let failsSchema = consumeSchemaFault()

      return try await perform("feed", kind: .read) { () throws(EngineError) -> Engine.Page<Engine.FeedItem> in
         if failsSchema {
            throw .schemaChanged(path: "xdt_api__v1__feed__timeline__connection.edges[0].node.media")
         }

         let start = Int(cursor ?? "0") ?? 0
         let order = world.feedOrder.filter { pk in
            guard let record = world.posts[pk] else {
               return false
            }

            let isHidden = world.hiddenPostPKs.contains(pk)
            let authorIsHidden = world.isHiddenFromViewer(record.authorID)
            return !isHidden && !authorIsHidden
         }
         let end = min(start + Self.feedPageSize, order.count)
         let slice = start < end ? Array(order[start..<end]) : []

         var items = slice.compactMap { pk in
            world.enginePost(pk).map { Engine.FeedItem(kind: .post, post: $0) }
         }

         if start == 0 {
            items.insert(Engine.FeedItem(kind: .storiesTray, post: nil), at: 0)
         }

         let hasNextPage = end < order.count
         if !hasNextPage {
            items.append(Engine.FeedItem(kind: .endOfFeed, post: nil))
         }

         return Engine.Page(items: items, hasNextPage: hasNextPage, endCursor: hasNextPage ? String(end) : nil)
      }
   }

   func profile(username: String) async throws(EngineError) -> EngineResult<Engine.Profile> {
      try await perform("profile(username)", kind: .read) { () throws(EngineError) -> Engine.Profile in
         guard let user = world.users.values.first(where: { $0.username == username }), let profile = world.profile(user.id) else {
            throw .notFound
         }

         return profile
      }
   }

   func profile(id userID: String) async throws(EngineError) -> EngineResult<Engine.Profile> {
      try await perform("profile_by_id", kind: .read) { () throws(EngineError) -> Engine.Profile in
         guard let profile = world.profile(userID) else {
            throw .notFound
         }

         return profile
      }
   }

   func post(code: String) async throws(EngineError) -> EngineResult<Engine.Post> {
      try await perform("post(code)", kind: .read) { () throws(EngineError) -> Engine.Post in
         guard let pk = world.postPK(forCode: code), let post = world.enginePost(pk) else {
            throw .notFound
         }

         let canSee = world.canSeePosts(of: post.author.id)
         guard canSee else {
            throw .notFound
         }

         return withAudio(post)
      }
   }

   func comments(postPK: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.Comment>> {
      try await perform("comments", kind: .read) { () throws(EngineError) -> Engine.Page<Engine.Comment> in
         guard world.posts[postPK] != nil else {
            throw .notFound
         }

         return Engine.Page(items: world.comments[postPK] ?? [], hasNextPage: false, endCursor: nil)
      }
   }

   // MARK: Writes

   func like(postPK: String) async throws(EngineError) -> EngineResult<Void> {
      try await perform("like", kind: .write) { () throws(EngineError) in
         try setLiked(true, postPK: postPK)
      }
   }

   func unlike(postPK: String) async throws(EngineError) -> EngineResult<Void> {
      try await perform("unlike", kind: .write) { () throws(EngineError) in
         try setLiked(false, postPK: postPK)
      }
   }

   private func setLiked(_ isLiked: Bool, postPK: String) throws(EngineError) {
      guard let record = world.posts[postPK] else {
         throw .notFound
      }

      let isChange = record.hasLiked != isLiked
      guard isChange else {
         return
      }

      world.posts[postPK]?.hasLiked = isLiked
      world.posts[postPK]?.likeCount += isLiked ? 1 : -1
   }

   func comment(postPK: String, text: String) async throws(EngineError) -> EngineResult<Engine.Comment> {
      try await perform("comment", kind: .write) { () throws(EngineError) -> Engine.Comment in
         guard let record = world.posts[postPK] else {
            throw .notFound
         }

         if record.commentsDisabled {
            throw .upstreamRejected(code: "comments_disabled")
         }

         let viewer = world.users[viewerID]!
         let comment = Engine.Comment(
            id: world.makeID("c."),
            author: Engine.CommentAuthor(id: viewer.id, username: viewer.username, isVerified: viewer.isVerified, profilePicURL: "dummy://avatar/viewer"),
            text: text,
            createdAt: .now,
            likeCount: 0,
            hasLiked: false,
            parentCommentID: nil,
            replyCount: 0
         )

         world.comments[postPK, default: []].append(comment)
         return comment
      }
   }

   func deleteComment(postPK: String, commentID: String) async throws(EngineError) -> EngineResult<Void> {
      try await perform("delete_comment", kind: .write) { () throws(EngineError) in
         world.comments[postPK]?.removeAll { $0.id == commentID }
      }
   }

   func follow(userID: String) async throws(EngineError) -> EngineResult<Void> {
      try await perform("follow", kind: .write) { () throws(EngineError) in
         guard let user = world.users[userID] else {
            throw .notFound
         }

         let alreadyFollowing = world.followingIDs.contains(userID)
         guard !alreadyFollowing else {
            return
         }

         if user.isPrivate {
            world.outgoingRequestIDs.insert(userID)
            return
         }

         world.followingIDs.insert(userID)
         world.users[userID]?.followerCount += 1
         world.users[viewerID]?.followingCount += 1
      }
   }

   func unfollow(userID: String) async throws(EngineError) -> EngineResult<Void> {
      try await perform("unfollow", kind: .write) { () throws(EngineError) in
         guard world.users[userID] != nil else {
            throw .notFound
         }

         world.outgoingRequestIDs.remove(userID)

         let wasFollowing = world.followingIDs.remove(userID) != nil
         if wasFollowing {
            world.users[userID]?.followerCount -= 1
            world.users[viewerID]?.followingCount -= 1
         }
      }
   }

   func publishPhoto(imageURL: URL, caption: String) async throws(EngineError) -> EngineResult<Engine.PublishedPost> {
      try await perform("publish_photo", kind: .write) { () throws(EngineError) -> Engine.PublishedPost in
         insertOwnPost(imageURL: imageURL, caption: caption, kind: .photo)
      }
   }

   func deletePost(postPK: String, code: String) async throws(EngineError) -> EngineResult<Void> {
      try await perform("delete_post", kind: .write) { () throws(EngineError) in
         guard world.posts[postPK]?.authorID == viewerID else {
            throw .notFound
         }

         world.posts[postPK] = nil
         world.feedOrder.removeAll { $0 == postPK }
      }
   }

   // MARK: Direct

   func inbox(after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.DirectThread>> {
      try await perform("inbox", kind: .read) { () throws(EngineError) -> Engine.Page<Engine.DirectThread> in
         let threads = world.threads.values
            .filter { !$0.isRequest }
            .compactMap { world.engineThread($0.fbid) }
            .sorted { $0.lastActivityAt > $1.lastActivityAt }

         return Engine.Page(items: threads, hasNextPage: false, endCursor: nil)
      }
   }

   // The first page opens the thread the way a browser does, which marks it seen upstream.
   func messages(threadFBID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.Message>> {
      try await perform("thread_messages", kind: .read) { () throws(EngineError) -> Engine.Page<Engine.Message> in
         guard world.threads[threadFBID] != nil else {
            throw .notFound
         }

         if cursor == nil {
            world.threads[threadFBID]?.isUnread = false
         }

         let all = world.messages[threadFBID] ?? []
         let end = cursor.flatMap(Int.init) ?? all.count
         let start = max(0, end - Self.messagePageSize)
         let page = start < end ? Array(all[start..<end]) : []
         let hasOlder = start > 0

         return Engine.Page(items: page.map(world.asRead), hasNextPage: hasOlder, endCursor: hasOlder ? String(start) : nil)
      }
   }

   func messageRequests() async throws(EngineError) -> EngineResult<Engine.MessageRequests> {
      try await perform("message_requests", kind: .read) { () throws(EngineError) -> Engine.MessageRequests in
         let pending = world.threads.values
            .filter(\.isRequest)
            .compactMap { world.engineThread($0.fbid) }
            .sorted { $0.lastActivityAt > $1.lastActivityAt }

         return Engine.MessageRequests(pending: pending, spam: [])
      }
   }

   // The dummy holds no session. Its seeded accounts read as refreshed two days before launch.
   func sessionRefreshedAt() async -> Date? {
      Date().addingTimeInterval(-2 * 24 * 3600)
   }

   func unreadCounts() async throws(EngineError) -> EngineResult<Engine.UnreadCounts> {
      try await perform("unread_counts", kind: .read) { () throws(EngineError) -> Engine.UnreadCounts in
         let unread = world.threads.values.filter { $0.isUnread && !$0.isRequest }.count
         let pending = world.threads.values.filter(\.isRequest).count
         return Engine.UnreadCounts(inbox: unread, pending: pending)
      }
   }

   func send(threadFBID: String, text: String) async throws(EngineError) -> EngineResult<Engine.SentMessage> {
      let result = try await perform("send_message", kind: .write) { () throws(EngineError) -> Engine.SentMessage in
         guard world.threads[threadFBID] != nil else {
            throw .notFound
         }

         let offlineThreadingID = String(Int.random(in: 1_000_000_000...9_999_999_999))
         let message = world.appendMessage(threadFBID: threadFBID, senderID: viewerID, text: text, offlineThreadingID: offlineThreadingID)
         return Engine.SentMessage(id: message.id, offlineThreadingID: offlineThreadingID, threadFBID: threadFBID, sentAt: message.sentAt)
      }

      if case .value = result {
         scheduleReply(in: threadFBID)
      }

      return result
   }

   func unsend(threadFBID: String, messageID: String) async throws(EngineError) -> EngineResult<Void> {
      try await perform("unsend_message", kind: .write) { () throws(EngineError) in
         let ownsMessage = world.messages[threadFBID]?.contains { $0.id == messageID && $0.sender.igid == viewerID } ?? false
         guard ownsMessage else {
            throw .notFound
         }

         world.messages[threadFBID]?.removeAll { $0.id == messageID }
      }
   }

   func notes() async throws(EngineError) -> EngineResult<[Engine.Note]> {
      try await perform("notes", kind: .read) { () throws(EngineError) -> [Engine.Note] in
         world.notes
      }
   }

   func setNote(text: String, audience: Engine.NoteAudience) async throws(EngineError) -> EngineResult<Engine.Note> {
      try await perform("set_note", kind: .write) { () throws(EngineError) -> Engine.Note in
         world.notes.removeAll { $0.authorID == viewerID }

         let note = Engine.Note(id: world.makeID("n."), authorID: viewerID, authorUsername: world.users[viewerID]?.username, text: text, audience: audience, createdAt: .now)
         world.notes.insert(note, at: 0)
         return note
      }
   }

   func deleteNote(noteID: String) async throws(EngineError) -> EngineResult<Void> {
      try await perform("delete_note", kind: .write) { () throws(EngineError) in
         world.notes.removeAll { $0.id == noteID }
      }
   }

   // MARK: Proposed surface

   func storiesTray() async throws(EngineError) -> EngineResult<[Engine.StoryTrayEntry]> {
      try await perform("stories_tray (proposed)", kind: .read) { () throws(EngineError) -> [Engine.StoryTrayEntry] in
         world.stories.compactMap { record in
            world.summary(record.userID).map { Engine.StoryTrayEntry(user: $0, itemCount: record.itemCount, latestAt: record.latestAt, hasUnseen: !record.isSeen) }
         }
      }
   }

   func markStorySeen(userID: String) async throws(EngineError) -> EngineResult<Void> {
      try await perform("mark_story_seen (proposed)", kind: .write) { () throws(EngineError) in
         guard let index = world.stories.firstIndex(where: { $0.userID == userID }) else {
            return
         }

         world.stories[index].isSeen = true
      }
   }

   func reels(after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.Reel>> {
      try await perform("reels (proposed)", kind: .read) { () throws(EngineError) -> Engine.Page<Engine.Reel> in
         let reels = world.posts.values
            .filter(\.isReel)
            .sorted { $0.takenAt > $1.takenAt }
            .compactMap { record in
               world.enginePost(record.pk).map { Engine.Reel(post: withAudio($0), audioTitle: record.audioTitle ?? "Original audio", playCount: record.likeCount * 11, audioID: record.audioTitle.map(Self.audioID(forTitle:))) }
            }

         let start = Int(cursor ?? "0") ?? 0
         let end = min(start + Self.reelsPageSize, reels.count)
         let slice = start < end ? Array(reels[start..<end]) : []
         let hasNextPage = end < reels.count

         return Engine.Page(items: slice, hasNextPage: hasNextPage, endCursor: hasNextPage ? String(end) : nil)
      }
   }

   func search(query: String) async throws(EngineError) -> EngineResult<[Engine.UserSummary]> {
      try await perform("search (proposed)", kind: .read) { () throws(EngineError) -> [Engine.UserSummary] in
         let needle = query.lowercased()

         return world.users.values
            .filter { user in
               let isOther = user.id != viewerID && !world.blockedIDs.contains(user.id)
               let matchesUsername = user.username.lowercased().contains(needle)
               let matchesName = user.fullName.lowercased().contains(needle)
               return isOther && (matchesUsername || matchesName)
            }
            .sorted { $0.followerCount > $1.followerCount }
            .compactMap { world.summary($0.id) }
      }
   }

   func explore() async throws(EngineError) -> EngineResult<[Engine.GridTile]> {
      try await perform("explore (proposed)", kind: .read) { () throws(EngineError) -> [Engine.GridTile] in
         world.posts.values
            .filter { $0.authorID != viewerID && world.canSeePosts(of: $0.authorID) }
            .sorted { $0.likeCount > $1.likeCount }
            .prefix(18)
            .compactMap { world.tile($0.pk) }
      }
   }

   func activity() async throws(EngineError) -> EngineResult<[Engine.ActivityEntry]> {
      try await perform("activity (proposed)", kind: .read) { () throws(EngineError) -> [Engine.ActivityEntry] in
         world.activity
      }
   }

   func followRequests() async throws(EngineError) -> EngineResult<[Engine.UserSummary]> {
      try await perform("follow_requests (proposed)", kind: .read) { () throws(EngineError) -> [Engine.UserSummary] in
         world.incomingRequestIDs.compactMap { world.summary($0) }
      }
   }

   func resolveFollowRequest(userID: String, approve: Bool) async throws(EngineError) -> EngineResult<Void> {
      try await perform(approve ? "approve_request (proposed)" : "ignore_request (proposed)", kind: .write) { () throws(EngineError) in
         world.incomingRequestIDs.removeAll { $0 == userID }

         if approve {
            world.followerIDs.insert(userID)
            world.users[viewerID]?.followerCount += 1
         }
      }
   }

   func suggestedUsers() async throws(EngineError) -> EngineResult<[Engine.UserSummary]> {
      try await perform("suggested_users (proposed)", kind: .read) { () throws(EngineError) -> [Engine.UserSummary] in
         world.suggestedIDs.compactMap { world.summary($0) }
      }
   }

   func profileActivity() async throws(EngineError) -> EngineResult<Engine.ProfileActivity> {
      try await perform("profile_activity (proposed)", kind: .read) { () throws(EngineError) -> Engine.ProfileActivity in
         let recent = world.followerIDs.sorted().prefix(7).compactMap { world.summary($0) }
         return Engine.ProfileActivity(recentFollowers: recent, activeFollowerCount: 24_300)
      }
   }

   func profilePosts(userID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try await perform("profile_posts (proposed)", kind: .read) { () throws(EngineError) -> Engine.Page<Engine.GridTile> in
         guard world.canSeePosts(of: userID) else {
            return Engine.Page(items: [], hasNextPage: false, endCursor: nil)
         }

         let tiles = world.posts.values
            .filter { $0.authorID == userID && !$0.isReel }
            .sorted { $0.takenAt > $1.takenAt }
            .compactMap { world.tile($0.pk) }

         return Engine.Page(items: tiles, hasNextPage: false, endCursor: nil)
      }
   }

   func profileReels(userID: String) async throws(EngineError) -> EngineResult<[Engine.GridTile]> {
      try await perform("profile_reels (proposed)", kind: .read) { () throws(EngineError) -> [Engine.GridTile] in
         guard world.canSeePosts(of: userID) else {
            return []
         }

         return world.posts.values
            .filter { $0.authorID == userID && $0.kind == .video }
            .sorted { $0.takenAt > $1.takenAt }
            .compactMap { world.tile($0.pk) }
      }
   }

   func taggedPosts(userID: String) async throws(EngineError) -> EngineResult<[Engine.GridTile]> {
      try await perform("tagged_posts (proposed)", kind: .read) { () throws(EngineError) -> [Engine.GridTile] in
         userID == viewerID ? ["p.castle", "p.tram"].compactMap { world.tile($0) } : []
      }
   }

   func savedPosts() async throws(EngineError) -> EngineResult<[Engine.GridTile]> {
      try await perform("saved_posts (proposed)", kind: .read) { () throws(EngineError) -> [Engine.GridTile] in
         world.posts.values.filter(\.hasSaved).compactMap { world.tile($0.pk) }
      }
   }

   // The dummy world holds every tile of these grids, so its first page is the whole grid.
   func profileReelsPage(userID: String) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      Self.wholePage(try await profileReels(userID: userID))
   }

   func taggedPostsPage(userID: String) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      Self.wholePage(try await taggedPosts(userID: userID))
   }

   func savedPostsPage() async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      Self.wholePage(try await savedPosts())
   }

   private static func wholePage(_ result: EngineResult<[Engine.GridTile]>) -> EngineResult<Engine.Page<Engine.GridTile>> {
      switch result {
         case .value(let tiles): .value(Engine.Page(items: tiles, hasNextPage: false, endCursor: nil))
         case .checkpoint(let checkpoint): .checkpoint(checkpoint)
      }
   }

   func highlights(userID: String) async throws(EngineError) -> EngineResult<[Engine.Highlight]> {
      try await perform("highlights (proposed)", kind: .read) { () throws(EngineError) -> [Engine.Highlight] in
         world.canSeePosts(of: userID) ? world.highlights[userID] ?? [] : []
      }
   }

   func followers(userID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.UserSummary>> {
      try await perform("followers (proposed)", kind: .read) { () throws(EngineError) -> Engine.Page<Engine.UserSummary> in
         guard world.canSeePosts(of: userID) else {
            throw .notFound
         }

         let ids = userID == viewerID ? Array(world.followerIDs) : Array(world.users.keys.filter { $0 != userID }.prefix(8))
         return Engine.Page(items: ids.sorted().compactMap { world.summary($0) }, hasNextPage: false, endCursor: nil)
      }
   }

   func following(userID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.UserSummary>> {
      try await perform("following (proposed)", kind: .read) { () throws(EngineError) -> Engine.Page<Engine.UserSummary> in
         guard world.canSeePosts(of: userID) else {
            throw .notFound
         }

         let ids = userID == viewerID ? Array(world.followingIDs) : Array(world.users.keys.filter { $0 != userID }.suffix(6))
         return Engine.Page(items: ids.sorted().compactMap { world.summary($0) }, hasNextPage: false, endCursor: nil)
      }
   }

   func save(postPK: String) async throws(EngineError) -> EngineResult<Void> {
      try await perform("save (proposed)", kind: .write) { () throws(EngineError) in
         guard world.posts[postPK] != nil else {
            throw .notFound
         }

         world.posts[postPK]?.hasSaved = true
      }
   }

   func unsave(postPK: String) async throws(EngineError) -> EngineResult<Void> {
      try await perform("unsave (proposed)", kind: .write) { () throws(EngineError) in
         world.posts[postPK]?.hasSaved = false
      }
   }

   // MARK: Story reels and the posts grid by username
   // A reel read marks its first item seen, as the engine's default Behavior does, so the dummy
   // counts it as a write.

   func storyReel(userID: String) async throws(EngineError) -> EngineResult<Engine.StoryReel?> {
      try await perform("stories.reel", kind: .write) { () throws(EngineError) -> Engine.StoryReel? in
         guard let index = world.stories.firstIndex(where: { $0.userID == userID }), let owner = world.user(userID) else {
            return nil
         }

         let record = world.stories[index]
         world.stories[index].isSeen = true

         return Self.dummyReel(id: "reel.\(userID)", owner: owner, title: nil, itemCount: record.itemCount, latestAt: record.latestAt)
      }
   }

   func highlightReel(highlightID: String) async throws(EngineError) -> EngineResult<Engine.StoryReel> {
      try await perform("stories.highlight", kind: .write) { () throws(EngineError) -> Engine.StoryReel in
         let match = world.highlights.lazy.compactMap { ownerID, highlights in
            highlights.first { $0.id == highlightID }.map { (ownerID, $0) }
         }.first

         guard let (ownerID, highlight) = match, let owner = world.user(ownerID) ?? world.user(viewerID) else {
            throw .notFound
         }

         return Self.dummyReel(id: highlight.id, owner: owner, title: highlight.title, itemCount: highlight.itemCount ?? 3, latestAt: .now.addingTimeInterval(-86_400 * 30))
      }
   }

   func markStorySeen(reelID: String, itemID: String) async throws(EngineError) -> EngineResult<Void> {
      try await perform("stories.mark_seen", kind: .write) { () throws(EngineError) in
         guard itemID.hasPrefix(reelID) else {
            throw .notFound
         }
      }
   }

   func profilePosts(username: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try await perform("profiles.posts", kind: .read) { () throws(EngineError) -> Engine.Page<Engine.GridTile> in
         guard let user = world.users.values.first(where: { $0.username == username }) else {
            throw .notFound
         }

         guard world.canSeePosts(of: user.id) else {
            return Engine.Page(items: [], hasNextPage: false, endCursor: nil)
         }

         let tiles = world.posts.values
            .filter { $0.authorID == user.id && !$0.isReel }
            .sorted { $0.takenAt > $1.takenAt }
            .compactMap { world.tile($0.pk) }

         let start = cursor.flatMap(Int.init) ?? 0
         let end = min(start + Self.profilePageSize, tiles.count)
         let page = start < end ? Array(tiles[start..<end]) : []
         let hasNextPage = end < tiles.count

         return Engine.Page(items: page, hasNextPage: hasNextPage, endCursor: hasNextPage ? String(end) : nil)
      }
   }

   static let profilePageSize = 12

   private static func dummyReel(id: String, owner: DummyWorld.User, title: String?, itemCount: Int, latestAt: Date) -> Engine.StoryReel {
      let items = (0..<itemCount).map { position in
         let takenAt = latestAt.addingTimeInterval(Double(position - itemCount + 1) * 600)

         return Engine.StoryItem(
            id: "\(id).\(position)",
            pk: "\(id).\(position)",
            ownerID: owner.id,
            mediaType: 1,
            takenAt: takenAt,
            expiringAt: takenAt.addingTimeInterval(86_400),
            images: [],
            videoDuration: nil,
            canReply: true
         )
      }

      return Engine.StoryReel(id: id, ownerID: owner.id, ownerUsername: owner.username, title: title, latestItemAt: latestAt, items: items)
   }
}

extension DummyEngine {
   static let explorePageSize = 12
   static let reelsPageSize = 3

   func explore(after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try await perform("feeds.explore", kind: .read) { () throws(EngineError) -> Engine.Page<Engine.GridTile> in
         let tiles = world.posts.values
            .filter { $0.authorID != viewerID && world.canSeePosts(of: $0.authorID) }
            .sorted { $0.likeCount > $1.likeCount }
            .compactMap { world.tile($0.pk) }

         let start = Int(cursor ?? "0") ?? 0
         let end = min(start + Self.explorePageSize, tiles.count)
         let slice = start < end ? Array(tiles[start..<end]) : []
         let hasNextPage = end < tiles.count

         return Engine.Page(items: slice, hasNextPage: hasNextPage, endCursor: hasNextPage ? String(end) : nil)
      }
   }

   func recentSearches() async throws(EngineError) -> EngineResult<[Engine.RecentSearch]> {
      try await perform("search.recent", kind: .read) { () throws(EngineError) -> [Engine.RecentSearch] in
         let accounts = world.suggestedIDs.prefix(2).compactMap { world.summary($0) }.map { summary in
            Engine.RecentSearch(kind: .account, account: summary, keyword: nil)
         }

         return accounts + [
            Engine.RecentSearch(kind: .keyword, account: nil, keyword: "film cameras"),
            Engine.RecentSearch(kind: .place, account: nil, keyword: nil),
         ]
      }
   }

   // The seeded rows are typed, and one row arrives untyped the way the real engine sends every
   // row, so both renderings stay exercised.
   func activityFeed() async throws(EngineError) -> EngineResult<Engine.ActivityFeed> {
      try await perform("account.activity", kind: .read) { () throws(EngineError) -> Engine.ActivityFeed in
         let storyLiker = world.summary("noor.aziz")
         let untyped = storyLiker.map { liker in
            Engine.UntypedActivityEntry(
               id: "a.untyped.1",
               rawKind: "story_like",
               text: "\(liker.username) liked your story.",
               accountID: liker.id,
               accountUsername: liker.username,
               occurredAt: Date.now.addingTimeInterval(-30 * 60),
               mediaCode: nil
            )
         }

         return Engine.ActivityFeed(entries: world.activity, untyped: untyped.map { [$0] } ?? [], hasUnseen: true)
      }
   }
}
