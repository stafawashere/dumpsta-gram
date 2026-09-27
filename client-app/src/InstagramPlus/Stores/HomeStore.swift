import Foundation
import Observation

enum FeedOrdering: String, CaseIterable, Identifiable {
   case latest
   case popular

   var id: String { rawValue }

   var title: String {
      switch self {
         case .latest: "Latest"
         case .popular: "Popular"
      }
   }
}

@MainActor
@Observable
final class HomeStore {
   let gateway: EngineGateway

   private(set) var feedState = LoadState.idle
   private(set) var isLoadingMore = false
   private(set) var hasMorePosts = false
   private var nextCursor: String?

   private(set) var postsByPK: [String: Post] = [:]
   private(set) var feedPKs: [String] = []
   private(set) var detailStates: [String: LoadState] = [:]
   private(set) var pendingWritePKs: Set<String> = []

   private(set) var comments: [Post.ID: [PostComment]] = [:]
   private(set) var commentStates: [Post.ID: LoadState] = [:]

   private(set) var stories: [Story] = []
   private(set) var suggestions: [Account] = []
   private(set) var recentFollowers: [Account] = []
   private(set) var activeFollowerCount = 0
   private(set) var isPublishing = false

   var feedOrdering: FeedOrdering = .latest

   init(gateway: EngineGateway) {
      self.gateway = gateway
   }

   var engine: any AppEngine { gateway.client }

   var orderedPosts: [Post] {
      let posts = feedPKs.compactMap { postsByPK[$0] }

      switch feedOrdering {
         case .latest: return posts
         case .popular: return posts.sorted { $0.likeCount > $1.likeCount }
      }
   }

   func post(code: String) -> Post? {
      postsByPK.values.first { $0.code == code }
   }

   func post(pk: String) -> Post? {
      postsByPK[pk]
   }

   func isPending(_ postPK: String) -> Bool {
      pendingWritePKs.contains(postPK)
   }

   // MARK: Loading

   // The feed goes first because it is what the page is for. Every later read waits its turn in
   // the pacer, so the rail fills in over the following seconds on the parity timing.
   func load() async {
      feedState = .loading
      nextCursor = nil

      let engine = engine
      let feedOutcome = await gateway.read("the feed") { () async throws(EngineError) in try await engine.feed(after: nil) }

      switch feedOutcome {
         case .success(let page):
            feedPKs = []
            apply(page)
            feedState = .loaded

         case .failure(let error):
            feedState = .failed(Self.describe(error))

         case .halted:
            feedState = .idle
            return
      }

      await loadStories()
      await loadRail()
   }

   func loadMore() async {
      let canLoadMore = hasMorePosts && !isLoadingMore
      guard canLoadMore else {
         return
      }

      isLoadingMore = true
      defer { isLoadingMore = false }

      let engine = engine
      let cursor = nextCursor

      if case .success(let page) = await gateway.read("more posts", { () async throws(EngineError) in try await engine.feed(after: cursor) }) {
         apply(page)
      }
   }

   private func apply(_ page: Engine.Page<Engine.FeedItem>) {
      for item in page.items {
         guard item.kind == .post, let enginePost = item.post else {
            continue
         }

         let post = Post(enginePost)
         postsByPK[post.id] = post

         if !feedPKs.contains(post.id) {
            feedPKs.append(post.id)
         }
      }

      hasMorePosts = page.hasNextPage
      nextCursor = page.endCursor
   }

   func loadStories() async {
      let engine = engine

      if case .success(let tray) = await gateway.read("stories", { () async throws(EngineError) in try await engine.storiesTray() }) {
         stories = tray.map(Story.init)
      }
   }

   private func loadRail() async {
      let engine = engine

      if case .success(let users) = await gateway.read("suggestions", { () async throws(EngineError) in try await engine.suggestedUsers() }) {
         suggestions = users.map(Account.init)
      }

      if case .success(let activity) = await gateway.read("profile activity", { () async throws(EngineError) in try await engine.profileActivity() }) {
         recentFollowers = activity.recentFollowers.map(Account.init)
         activeFollowerCount = activity.activeFollowerCount
      }
   }

   func loadPost(code: String) async {
      let alreadyLoaded = post(code: code) != nil
      guard !alreadyLoaded else {
         detailStates[code] = .loaded
         return
      }

      detailStates[code] = .loading

      let engine = engine
      switch await gateway.read("the post", { () async throws(EngineError) in try await engine.post(code: code) }) {
         case .success(let enginePost):
            let post = Post(enginePost)
            postsByPK[post.id] = post
            detailStates[code] = .loaded

         case .failure(.notFound):
            detailStates[code] = .notFound

         case .failure(let error):
            detailStates[code] = .failed(Self.describe(error))

         case .halted:
            detailStates[code] = .idle
      }
   }

   func detailState(code: String) -> LoadState {
      detailStates[code] ?? .idle
   }

   // MARK: Likes and saves

   func toggleLike(postPK: String) async {
      guard let post = postsByPK[postPK], !pendingWritePKs.contains(postPK) else {
         return
      }

      let willLike = !post.isLiked
      postsByPK[postPK]?.isLiked = willLike
      postsByPK[postPK]?.likeCount += willLike ? 1 : -1
      pendingWritePKs.insert(postPK)
      defer { pendingWritePKs.remove(postPK) }

      let engine = engine
      let outcome = await gateway.write(willLike ? "the like" : "the unlike") { () async throws(EngineError) in
         if willLike {
            return try await engine.like(postPK: postPK)
         }

         return try await engine.unlike(postPK: postPK)
      }

      await settle(outcome, postPK: postPK, revert: {
         self.postsByPK[postPK]?.isLiked = !willLike
         self.postsByPK[postPK]?.likeCount += willLike ? -1 : 1
      })
   }

   func toggleSave(postPK: String) async {
      guard let post = postsByPK[postPK], !pendingWritePKs.contains(postPK) else {
         return
      }

      let willSave = !post.isSaved
      postsByPK[postPK]?.isSaved = willSave
      pendingWritePKs.insert(postPK)
      defer { pendingWritePKs.remove(postPK) }

      let engine = engine
      let outcome = await gateway.write(willSave ? "the save" : "the unsave") { () async throws(EngineError) in
         if willSave {
            return try await engine.save(postPK: postPK)
         }

         return try await engine.unsave(postPK: postPK)
      }

      await settle(outcome, postPK: postPK, revert: {
         self.postsByPK[postPK]?.isSaved = !willSave
      })
   }

   // A failed write is rolled back. An uncertain one is never sent again: the post is read back
   // so the interface shows whatever actually happened upstream.
   private func settle(_ outcome: CallOutcome<Void>, postPK: String, revert: () -> Void) async {
      switch outcome {
         case .success:
            break

         case .failure(.outcomeUnknown):
            await refresh(postPK: postPK)

         case .failure, .halted:
            revert()
      }
   }

   private func refresh(postPK: String) async {
      guard let code = postsByPK[postPK]?.code else {
         return
      }

      let engine = engine
      if case .success(let enginePost) = await gateway.read("the post", { () async throws(EngineError) in try await engine.post(code: code) }) {
         postsByPK[postPK] = Post(enginePost)
      }
   }

   // MARK: Comments

   func comments(for postPK: String) -> [PostComment] {
      comments[postPK] ?? []
   }

   func commentState(for postPK: String) -> LoadState {
      commentStates[postPK] ?? .idle
   }

   func loadComments(postPK: String) async {
      commentStates[postPK] = .loading

      let engine = engine
      switch await gateway.read("comments", { () async throws(EngineError) in try await engine.comments(postPK: postPK, after: nil) }) {
         case .success(let page):
            comments[postPK] = page.items.map(PostComment.init)
            commentStates[postPK] = .loaded

         case .failure(let error):
            commentStates[postPK] = .failed(Self.describe(error))

         case .halted:
            commentStates[postPK] = .idle
      }
   }

   func addComment(_ text: String, to postPK: String, viewer: Account) async {
      let trimmedText = text.trimmingCharacters(in: .whitespacesAndNewlines)
      guard !trimmedText.isEmpty else {
         return
      }

      let pendingID = "pending." + UUID().uuidString
      let pending = PostComment(id: pendingID, author: viewer, text: trimmedText, postedAt: .now, likeCount: 0, isLiked: false, isPending: true)
      comments[postPK, default: []].append(pending)
      postsByPK[postPK]?.commentCount += 1

      let engine = engine
      let outcome = await gateway.write("the comment") { () async throws(EngineError) in try await engine.comment(postPK: postPK, text: trimmedText) }

      switch outcome {
         case .success(let created):
            replaceComment(pendingID, in: postPK, with: PostComment(created))

         case .failure(.outcomeUnknown):
            await loadComments(postPK: postPK)

         case .failure, .halted:
            comments[postPK]?.removeAll { $0.id == pendingID }
            postsByPK[postPK]?.commentCount -= 1
      }
   }

   func deleteComment(_ commentID: String, from postPK: String) async {
      guard let removed = comments[postPK]?.first(where: { $0.id == commentID }) else {
         return
      }

      comments[postPK]?.removeAll { $0.id == commentID }
      postsByPK[postPK]?.commentCount -= 1

      let engine = engine
      let outcome = await gateway.write("the comment delete") { () async throws(EngineError) in try await engine.deleteComment(postPK: postPK, commentID: commentID) }

      switch outcome {
         case .success:
            break

         case .failure(.outcomeUnknown):
            await loadComments(postPK: postPK)

         case .failure, .halted:
            comments[postPK, default: []].append(removed)
            postsByPK[postPK]?.commentCount += 1
      }
   }

   private func replaceComment(_ commentID: String, in postPK: String, with comment: PostComment) {
      guard let index = comments[postPK]?.firstIndex(where: { $0.id == commentID }) else {
         return
      }

      comments[postPK]?[index] = comment
   }

   // MARK: Publishing and stories

   func publish(imageURLs: [URL], caption: String) async -> Bool {
      guard let firstURL = imageURLs.first else {
         return false
      }

      isPublishing = true
      defer { isPublishing = false }

      let engine = engine
      let isCarousel = imageURLs.count > 1
      let outcome = await gateway.write("the post") { () async throws(EngineError) in
         if isCarousel {
            return try await engine.publishCarousel(imageURLs: imageURLs, caption: caption)
         }

         return try await engine.publishPhoto(imageURL: firstURL, caption: caption)
      }

      switch outcome {
         case .success, .failure(.outcomeUnknown):
            feedOrdering = .latest
            await load()
            return true

         case .failure, .halted:
            return false
      }
   }

   func publishStory(imageURL: URL) async -> Bool {
      let engine = engine
      let outcome = await gateway.write("the story") { () async throws(EngineError) in try await engine.publishStory(imageURL: imageURL) }

      switch outcome {
         case .success, .failure(.outcomeUnknown):
            await loadStories()
            return true

         case .failure, .halted:
            return false
      }
   }

   func likeStory(authorID: Account.ID) async {
      let engine = engine
      _ = await gateway.write("the story like") { () async throws(EngineError) in try await engine.likeStory(userID: authorID) }
   }

   // MARK: Post actions

   func hide(postPK: String) async {
      guard let position = feedPKs.firstIndex(of: postPK) else {
         return
      }

      feedPKs.remove(at: position)

      let engine = engine
      let outcome = await gateway.write("hiding the post") { () async throws(EngineError) in try await engine.hidePost(postPK: postPK) }

      switch outcome {
         case .success, .failure(.outcomeUnknown):
            break

         case .failure, .halted:
            feedPKs.insert(postPK, at: min(position, feedPKs.count))
      }
   }

   func delete(postPK: String) async -> Bool {
      guard let post = postsByPK[postPK] else {
         return false
      }

      let engine = engine
      let outcome = await gateway.write("the post delete") { () async throws(EngineError) in try await engine.deletePost(postPK: postPK, code: post.code) }

      switch outcome {
         case .success:
            feedPKs.removeAll { $0 == postPK }
            postsByPK[postPK] = nil
            return true

         case .failure(.outcomeUnknown):
            await load()
            return true

         case .failure, .halted:
            return false
      }
   }

   func share(postPK: String, to threadIDs: [DirectThread.ID]) async -> Bool {
      let engine = engine
      let outcome = await gateway.write("the share") { () async throws(EngineError) in try await engine.sharePost(postPK: postPK, threadFBIDs: threadIDs) }

      if case .success = outcome {
         return true
      }

      return false
   }

   func download(_ post: Post, to destination: URL) async -> Bool {
      guard let imageURL = post.imageURL else {
         return false
      }

      let engine = engine
      let image = Engine.MediaImage(url: imageURL, width: 1080, height: 1080)
      let outcome = await gateway.read("the download") { () async throws(EngineError) in try await engine.download(image: image, to: destination) }

      if case .success = outcome {
         return true
      }

      return false
   }

   func toggleCommentLike(_ commentID: PostComment.ID, on postPK: String) async {
      guard let index = comments[postPK]?.firstIndex(where: { $0.id == commentID }) else {
         return
      }

      let willLike = !comments[postPK]![index].isLiked
      comments[postPK]![index].isLiked = willLike
      comments[postPK]![index].likeCount += willLike ? 1 : -1

      let engine = engine
      let outcome = await gateway.write(willLike ? "the comment like" : "the comment unlike") { () async throws(EngineError) in
         try await engine.likeComment(postPK: postPK, commentID: commentID, liked: willLike)
      }

      switch outcome {
         case .success:
            break

         case .failure(.outcomeUnknown):
            await loadComments(postPK: postPK)

         case .failure, .halted:
            guard let revertIndex = comments[postPK]?.firstIndex(where: { $0.id == commentID }) else {
               return
            }

            comments[postPK]![revertIndex].isLiked = !willLike
            comments[postPK]![revertIndex].likeCount += willLike ? -1 : 1
      }
   }

   func reply(_ text: String, to parentID: PostComment.ID, on postPK: String, viewer: Account) async {
      let trimmedText = text.trimmingCharacters(in: .whitespacesAndNewlines)
      guard !trimmedText.isEmpty else {
         return
      }

      let pendingID = "pending." + UUID().uuidString
      let pending = PostComment(id: pendingID, author: viewer, text: trimmedText, postedAt: .now, likeCount: 0, isLiked: false, isPending: true, parentID: parentID)
      comments[postPK, default: []].append(pending)

      let engine = engine
      let outcome = await gateway.write("the reply") { () async throws(EngineError) in
         try await engine.replyToComment(postPK: postPK, parentCommentID: parentID, text: trimmedText)
      }

      switch outcome {
         case .success(let created):
            replaceComment(pendingID, in: postPK, with: PostComment(created))

         case .failure(.outcomeUnknown):
            await loadComments(postPK: postPK)

         case .failure, .halted:
            comments[postPK]?.removeAll { $0.id == pendingID }
      }
   }

   func markStorySeen(authorID: Account.ID) async {
      guard let index = stories.firstIndex(where: { $0.id == authorID }), stories[index].hasUnseenItems else {
         return
      }

      stories[index].hasUnseenItems = false

      let engine = engine
      _ = await gateway.read("story seen") { () async throws(EngineError) in try await engine.markStorySeen(userID: authorID) }
   }

   static func describe(_ error: EngineError) -> String {
      switch error {
         case .transportFailure: "Instagram+ couldn't reach Instagram."
         case .schemaChanged: "Instagram changed how this loads. The engine needs an update."
         case .rateLimited: "Instagram asked for a pause."
         case .notFound: "This isn't available."
         default: "Something went wrong loading this."
      }
   }
}
