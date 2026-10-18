import Foundation

// The reads added to the engine after 1.1.0, answered from the dummy world with the engine's
// shapes: likers as a sample with no cursor, first pages with has_more where the engine gives
// only a first page, and hashtag and place rows of the top search with no payload.
extension DummyEngine {
   static let likerSampleSize = 6
   static let audioPageSize = 2

   func postPage(code: String) async throws(EngineError) -> EngineResult<Engine.PostPage> {
      try await perform("media.page", kind: .read) { () throws(EngineError) -> Engine.PostPage in
         guard let pk = world.postPK(forCode: code), let post = world.enginePost(pk), world.canSeePosts(of: post.author.id) else {
            throw .notFound
         }

         let comments = Engine.Page(items: world.comments[pk] ?? [], hasNextPage: false, endCursor: nil)
         return Engine.PostPage(post: withAudio(post), comments: comments, authorGrid: authorGrid(of: post.author.id, excluding: pk))
      }
   }

   func post(pk: String) async throws(EngineError) -> EngineResult<Engine.Post> {
      try await perform("media.by_id", kind: .read) { () throws(EngineError) -> Engine.Post in
         guard let post = world.enginePost(pk), world.canSeePosts(of: post.author.id) else {
            throw .notFound
         }

         return withAudio(post)
      }
   }

   func likers(postPK: String) async throws(EngineError) -> EngineResult<[Engine.UserSummary]> {
      try await perform("media.likers", kind: .read) { () throws(EngineError) -> [Engine.UserSummary] in
         guard let record = world.posts[postPK] else {
            throw .notFound
         }

         let others = world.users.keys
            .filter { $0 != record.authorID && $0 != viewerID }
            .sorted()
            .prefix(Self.likerSampleSize)

         let viewerLikes = record.hasLiked ? [viewerID] : []
         return (viewerLikes + others).compactMap { world.summary($0) }
      }
   }

   func moreFromAuthor(authorID: String) async throws(EngineError) -> EngineResult<[Engine.GridTile]> {
      try await perform("media.more_from_author", kind: .read) { () throws(EngineError) -> [Engine.GridTile] in
         world.canSeePosts(of: authorID) ? authorGrid(of: authorID, excluding: nil) : []
      }
   }

   func replies(postPK: String, commentID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.Comment>> {
      try await perform("media.replies", kind: .read) { () throws(EngineError) -> Engine.Page<Engine.Comment> in
         guard let comments = world.comments[postPK], comments.contains(where: { $0.id == commentID }) else {
            throw .notFound
         }

         let replies = comments.filter { $0.parentCommentID == commentID }
         return Engine.Page(items: replies, hasNextPage: false, endCursor: nil)
      }
   }

   func mutualFollowers(userID: String) async throws(EngineError) -> EngineResult<Engine.MutualFollowers> {
      try await perform("profiles.mutual_followers", kind: .read) { () throws(EngineError) -> Engine.MutualFollowers in
         let mutual = world.followingIDs
            .filter { $0 != userID && $0 != viewerID }
            .sorted()

         let shown = mutual.prefix(3).compactMap { world.summary($0) }
         return Engine.MutualFollowers(accounts: shown, hasMore: mutual.count > shown.count)
      }
   }

   func similarAccounts(userID: String) async throws(EngineError) -> EngineResult<[Engine.UserSummary]> {
      try await perform("profiles.suggested", kind: .read) { () throws(EngineError) -> [Engine.UserSummary] in
         world.suggestedIDs.filter { $0 != userID }.compactMap { world.summary($0) }
      }
   }

   func savedCollections() async throws(EngineError) -> EngineResult<Engine.SavedCollections> {
      try await perform("account.collections", kind: .read) { () throws(EngineError) -> Engine.SavedCollections in
         let savedCount = world.posts.values.filter(\.hasSaved).count

         let collections = [
            Engine.SavedCollection(id: "col.all", name: "All posts", kind: .allPosts, mediaCount: savedCount, coverURLs: []),
            Engine.SavedCollection(id: "col.audio", name: "Audio", kind: .audio, mediaCount: nil, coverURLs: []),
            Engine.SavedCollection(id: "col.trips", name: "Trips", kind: .other, mediaCount: 4, coverURLs: []),
         ]

         return Engine.SavedCollections(collections: collections, hasMore: false)
      }
   }

   func hasNewPosts() async throws(EngineError) -> EngineResult<Bool> {
      try await perform("feeds.has_new_posts", kind: .read) { () throws(EngineError) -> Bool in
         false
      }
   }

   func searchTop(query: String) async throws(EngineError) -> EngineResult<[Engine.SearchResult]> {
      let accounts = try await search(query: query)

      guard case .value(let summaries) = accounts else {
         if case .checkpoint(let checkpoint) = accounts {
            return .checkpoint(checkpoint)
         }

         return .value([])
      }

      return try await perform("search.top", kind: .read) { () throws(EngineError) -> [Engine.SearchResult] in
         var rows = summaries.prefix(4).map { Engine.SearchResult(kind: .account, account: $0, keyword: nil, position: nil) }
         rows.append(Engine.SearchResult(kind: .keyword, account: nil, keyword: query.lowercased(), position: nil))
         rows.append(Engine.SearchResult(kind: .hashtag, account: nil, keyword: nil, position: nil))

         for (position, index) in rows.indices.enumerated() {
            rows[index] = Engine.SearchResult(kind: rows[index].kind, account: rows[index].account, keyword: rows[index].keyword, position: position)
         }

         return rows
      }
   }

   func searchKeyword(query: String) async throws(EngineError) -> EngineResult<Engine.KeywordResults> {
      try await perform("search.keyword", kind: .read) { () throws(EngineError) -> Engine.KeywordResults in
         let needle = query.lowercased()

         let matches = world.posts.values
            .filter { $0.caption.lowercased().contains(needle) && world.canSeePosts(of: $0.authorID) }
            .sorted { $0.likeCount > $1.likeCount }
            .compactMap { world.tile($0.pk) }

         let firstPage = Array(matches.prefix(Self.explorePageSize))
         return Engine.KeywordResults(posts: firstPage, hasMore: matches.count > firstPage.count)
      }
   }

   func hashtag(name: String) async throws(EngineError) -> EngineResult<Engine.HashtagHeader> {
      try await perform("search.hashtag", kind: .read) { () throws(EngineError) -> Engine.HashtagHeader in
         let tag = name.lowercased()
         let isUsed = world.posts.values.contains { world.hashtags(in: $0.caption).contains(tag) }

         guard isUsed else {
            throw .notFound
         }

         return Engine.HashtagHeader(id: "tag." + tag, name: tag)
      }
   }

   func explorePosts(after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.Post>> {
      try await perform("feeds.explore_posts", kind: .read) { () throws(EngineError) -> Engine.Page<Engine.Post> in
         let posts = world.posts.values
            .filter { $0.authorID != viewerID && world.canSeePosts(of: $0.authorID) }
            .sorted { $0.likeCount > $1.likeCount }
            .compactMap { world.enginePost($0.pk).map(withAudio) }

         return Self.page(of: posts, after: cursor, size: Self.explorePageSize)
      }
   }

   func audio(audioID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.AudioPage> {
      try await perform("feeds.audio", kind: .read) { () throws(EngineError) -> Engine.AudioPage in
         let clips = clipsUsing(audioID)

         guard let title = clips.first?.audioTitle else {
            throw .notFound
         }

         let page = Self.page(of: clips, after: cursor, size: Self.audioPageSize)
         let audio = Engine.MediaAudio(audioID: audioID, title: title, artist: clips.first?.author.username ?? "", isExplicit: false)

         return Engine.AudioPage(audio: audio, clips: page.items, clipsCount: clips.count, isRestricted: false, hasNextPage: page.hasNextPage, endCursor: page.endCursor)
      }
   }

   func audioClips(audioID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.Post>> {
      try await perform("feeds.audio_clips", kind: .read) { () throws(EngineError) -> Engine.Page<Engine.Post> in
         Self.page(of: clipsUsing(audioID), after: cursor, size: Self.audioPageSize)
      }
   }

   // The dummy's audio id is its title, so two reels on the same title share a page.
   func withAudio(_ post: Engine.Post) -> Engine.Post {
      guard let title = world.posts[post.pk]?.audioTitle else {
         return post
      }

      var withAudio = post
      withAudio.audioID = Self.audioID(forTitle: title)
      withAudio.audioTitle = title
      return withAudio
   }

   static func audioID(forTitle title: String) -> String {
      "audio." + title.lowercased().replacingOccurrences(of: " ", with: "-")
   }

   private func clipsUsing(_ audioID: String) -> [Engine.Post] {
      world.posts.values
         .filter { record in record.audioTitle.map(Self.audioID(forTitle:)) == audioID }
         .sorted { $0.takenAt > $1.takenAt }
         .compactMap { world.enginePost($0.pk).map(withAudio) }
   }

   private func authorGrid(of authorID: String, excluding excludedPK: String?) -> [Engine.GridTile] {
      world.posts.values
         .filter { $0.authorID == authorID && $0.pk != excludedPK && !$0.isReel }
         .sorted { $0.takenAt > $1.takenAt }
         .prefix(6)
         .compactMap { world.tile($0.pk) }
   }

   private static func page<Item: Sendable>(of items: [Item], after cursor: String?, size: Int) -> Engine.Page<Item> {
      let start = Int(cursor ?? "0") ?? 0
      let end = min(start + size, items.count)
      let slice = start < end ? Array(items[start..<end]) : []
      let hasNextPage = end < items.count

      return Engine.Page(items: slice, hasNextPage: hasNextPage, endCursor: hasNextPage ? String(end) : nil)
   }
}
