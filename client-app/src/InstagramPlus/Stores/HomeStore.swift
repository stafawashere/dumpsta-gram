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
   private var postPKsByRequestedCode: [String: Post.ID] = [:]
   private(set) var pendingWritePKs: Set<String> = []
   private(set) var unshownFeedItemCount = 0

   private(set) var comments: [Post.ID: [PostComment]] = [:]
   private(set) var commentStates: [Post.ID: LoadState] = [:]
   private var commentCursors: [Post.ID: String] = [:]
   private var loadingMoreComments: Set<Post.ID> = []

   private(set) var stories: [Story] = []
   private(set) var storiesState = LoadState.idle
   private var storyReels: [Account.ID: StoryFrames] = [:]
   private var storyReelStates: [Account.ID: LoadState] = [:]
   private var storyReelReads: [Account.ID: Task<Void, Never>] = [:]
   private var markedStoryItemIDs: Set<String> = []
   private(set) var suggestions: [Account] = []
   private(set) var suggestionsState = LoadState.idle
   private(set) var recentFollowers: [Account] = []
   private(set) var activeFollowerCount = 0
   private(set) var isPublishing = false

   private(set) var likers: [Post.ID: [Account]] = [:]
   private(set) var likerStates: [Post.ID: LoadState] = [:]
   private(set) var authorGrids: [Account.ID: [ProfileTile]] = [:]
   private(set) var authorGridStates: [Account.ID: LoadState] = [:]
   private(set) var replyStates: [PostComment.ID: LoadState] = [:]
   private var replyCursors: [PostComment.ID: String] = [:]
   private(set) var newPostsState = NewPostsState.unchecked

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

   // A post read by its code is found again by the code it was asked for, even when the code the
   // engine read out of the page differs from it.
   func post(code: String) -> Post? {
      if let pk = postPKsByRequestedCode[code], let post = postsByPK[pk] {
         return post
      }

      return postsByPK.values.first { $0.code == code }
   }

   var heldPostCount: Int {
      postsByPK.count
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
            unshownFeedItemCount = 0
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

   func isSaveStateKnown(_ postPK: String) -> Bool {
      postsByPK[postPK]?.isSaved != nil
   }

   // Ads, explore stories, suggestions and the other units carry no post the engine models, so
   // they are counted for the feed footer rather than left out without a word. The stories unit
   // is the tray the stories row reads on its own, and the end marker holds nothing.
   private func apply(_ page: Engine.Page<Engine.FeedItem>) {
      for item in page.items {
         guard item.kind == .post, let enginePost = item.post else {
            let isShownElsewhere = item.kind == .storiesTray || item.kind == .endOfFeed

            if !isShownElsewhere {
               unshownFeedItemCount += 1
            }

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
      storiesState = .loading

      let engine = engine
      switch await gateway.read("stories", { () async throws(EngineError) in try await engine.storiesTray() }) {
         case .success(let tray):
            let previousPostedAt = Dictionary(stories.map { ($0.id, $0.postedAt) }, uniquingKeysWith: { first, _ in first })
            stories = tray.map(Story.init)

            // A reel read earlier stays until its tray row changes, because reading it again
            // marks it seen again.
            for story in stories where previousPostedAt[story.id] != story.postedAt {
               storyReels[story.id] = nil
               storyReelStates[story.id] = nil
            }

            storiesState = .loaded

         case .failure(let error):
            storiesState = .failed(Self.describe(error))

         case .halted:
            storiesState = .idle
      }
   }

   // The engine's tray row has no unseen flag, so on the real engine the ring cannot say
   // whether a story is new until the viewer has opened it here.
   func isSeenStateKnown(_ authorID: Account.ID) -> Bool {
      stories.first { $0.id == authorID }?.hasUnseenItems != nil
   }

   private func loadRail() async {
      let engine = engine

      suggestionsState = .loading

      switch await gateway.read("suggestions", { () async throws(EngineError) in try await engine.suggestedUsers() }) {
         case .success(let users):
            suggestions = users.map(Account.init)
            suggestionsState = .loaded

         case .failure(let error):
            suggestionsState = .failed(Self.describe(error))

         case .halted:
            suggestionsState = .idle
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

      // media.page loads the post as its page does, with the first comments and the author's
      // grid in the same action, so neither is read again when the overlay asks for it.
      let engine = engine
      switch await gateway.read("the post", { () async throws(EngineError) in try await engine.postPage(code: code) }) {
         case .success(let page):
            let post = Post(page.post)
            postsByPK[post.id] = post
            postPKsByRequestedCode[code] = post.id
            comments[post.id] = page.comments.items.map(PostComment.init)
            commentCursors[post.id] = page.comments.hasNextPage ? page.comments.endCursor : nil
            commentStates[post.id] = .loaded
            authorGrids[post.author.id] = page.authorGrid.map(ProfileTile.init).filter { $0.id != post.id }
            authorGridStates[post.author.id] = .loaded
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

      let wasLiked = post.isLiked
      let previousLikeCount = post.likeCount
      let willLike = wasLiked != true
      postsByPK[postPK]?.isLiked = willLike

      // From an unknown state nothing says whether the count already holds this like.
      if wasLiked != nil {
         postsByPK[postPK]?.likeCount += willLike ? 1 : -1
      }
      pendingWritePKs.insert(postPK)
      defer { pendingWritePKs.remove(postPK) }

      let engine = engine
      let outcome = await gateway.write(willLike ? "the like" : "the unlike") { () async throws(EngineError) in
         if willLike {
            return try await engine.like(postPK: postPK)
         }

         return try await engine.unlike(postPK: postPK)
      }

      // Unknown after a failed read-back keeps the last count the engine gave, not the
      // optimistic one.
      await settle(outcome, postPK: postPK, revert: {
         self.postsByPK[postPK]?.isLiked = wasLiked
         self.postsByPK[postPK]?.likeCount = previousLikeCount
      }, whenReadBackFails: {
         self.postsByPK[postPK]?.isLiked = nil
         self.postsByPK[postPK]?.likeCount = previousLikeCount
      })
   }

   func toggleSave(postPK: String) async {
      guard let post = postsByPK[postPK], !pendingWritePKs.contains(postPK) else {
         return
      }

      let wasSaved = post.isSaved
      let willSave = wasSaved != true
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
         self.postsByPK[postPK]?.isSaved = wasSaved
      }, whenReadBackFails: {
         self.postsByPK[postPK]?.isSaved = nil
      })
   }

   // A failed write is rolled back. An uncertain one is never sent again: the post is read back
   // so the interface shows whatever happened upstream. When that read fails too, a state the
   // store can hold as unknown is marked unknown rather than left optimistic.
   private func settle(_ outcome: CallOutcome<Void>, postPK: String, revert: () -> Void, whenReadBackFails: (() -> Void)? = nil) async {
      switch outcome {
         case .success:
            break

         case .failure(.outcomeUnknown):
            let didReadBack = await refresh(postPK: postPK)

            if !didReadBack {
               whenReadBackFails?()
            }

         case .failure, .halted:
            revert()
      }
   }

   // media.by_id is one request where by_code under the default Behavior is six.
   private func refresh(postPK: String) async -> Bool {
      guard postsByPK[postPK] != nil else {
         return false
      }

      let engine = engine
      guard case .success(let enginePost) = await gateway.read("the post", { () async throws(EngineError) in try await engine.post(pk: postPK) }) else {
         return false
      }

      postsByPK[postPK] = Post(enginePost)
      return true
   }

   // MARK: Comments

   func comments(for postPK: String) -> [PostComment] {
      comments[postPK] ?? []
   }

   func commentState(for postPK: String) -> LoadState {
      commentStates[postPK] ?? .idle
   }

   func hasMoreComments(for postPK: String) -> Bool {
      commentCursors[postPK] != nil
   }

   func isLoadingMoreComments(for postPK: String) -> Bool {
      loadingMoreComments.contains(postPK)
   }

   func loadComments(postPK: String) async {
      commentStates[postPK] = .loading

      let engine = engine
      switch await gateway.read("comments", { () async throws(EngineError) in try await engine.comments(postPK: postPK, after: nil) }) {
         case .success(let page):
            comments[postPK] = page.items.map(PostComment.init)
            commentCursors[postPK] = page.hasNextPage ? page.endCursor : nil
            commentStates[postPK] = .loaded

         case .failure(let error):
            commentStates[postPK] = .failed(Self.describe(error))

         case .halted:
            commentStates[postPK] = .idle
      }
   }

   // The cursor goes back to the engine exactly as it came. A comment already shown is not
   // added twice.
   func loadMoreComments(postPK: String) async {
      guard let cursor = commentCursors[postPK], !loadingMoreComments.contains(postPK) else {
         return
      }

      loadingMoreComments.insert(postPK)
      defer { loadingMoreComments.remove(postPK) }

      let engine = engine
      guard case .success(let page) = await gateway.read("more comments", { () async throws(EngineError) in try await engine.comments(postPK: postPK, after: cursor) }) else {
         return
      }

      let known = Set(comments[postPK]?.map(\.id) ?? [])
      let fresh = page.items.map(PostComment.init).filter { !known.contains($0.id) }

      comments[postPK, default: []].append(contentsOf: fresh)
      commentCursors[postPK] = page.hasNextPage ? page.endCursor : nil
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

   // The engine offers several crops of one picture and says none is the picture, so the first
   // rendition it gave is downloaded as it came.
   func download(_ post: Post, to destination: URL) async -> Bool {
      guard let rendition = post.images.first else {
         return false
      }

      let engine = engine
      let image = Engine.MediaImage(url: rendition.url, width: rendition.width, height: rendition.height)
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

      let wasLiked = comments[postPK]![index].isLiked
      let previousLikeCount = comments[postPK]![index].likeCount
      let willLike = wasLiked != true
      comments[postPK]![index].isLiked = willLike
      if wasLiked != nil {
         comments[postPK]![index].likeCount = previousLikeCount.map { $0 + (willLike ? 1 : -1) }
      }

      let engine = engine
      let outcome = await gateway.write(willLike ? "the comment like" : "the comment unlike") { () async throws(EngineError) in
         try await engine.likeComment(postPK: postPK, commentID: commentID, liked: willLike)
      }

      switch outcome {
         case .success:
            break

         case .failure(.outcomeUnknown):
            await loadComments(postPK: postPK)

            // A reload that failed leaves the optimistic comment behind, so its like state and
            // count are marked unknown instead.
            let didReload = commentState(for: postPK).hasLoaded
            let unknownIndex = comments[postPK]?.firstIndex(where: { $0.id == commentID })

            if !didReload, let unknownIndex {
               comments[postPK]![unknownIndex].isLiked = nil
               comments[postPK]![unknownIndex].likeCount = nil
            }

         case .failure, .halted:
            guard let revertIndex = comments[postPK]?.firstIndex(where: { $0.id == commentID }) else {
               return
            }

            comments[postPK]![revertIndex].isLiked = wasLiked
            comments[postPK]![revertIndex].likeCount = previousLikeCount
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

   // MARK: Post page extras
   // Each is read only when a person opens the part of the post page that shows it, because
   // every read waits its turn in the pacer and holds the engine while it runs.

   func likers(of postPK: String) -> [Account] {
      likers[postPK] ?? []
   }

   func likerState(of postPK: String) -> LoadState {
      likerStates[postPK] ?? .idle
   }

   // The engine answers a sample of the likers with no cursor, so there is no next page.
   func loadLikers(postPK: String) async {
      guard !likerState(of: postPK).isLoading else {
         return
      }

      likerStates[postPK] = .loading

      let engine = engine
      switch await gateway.read("the likes", { () async throws(EngineError) in try await engine.likers(postPK: postPK) }) {
         case .success(let summaries):
            likers[postPK] = summaries.map(Account.init)
            likerStates[postPK] = .loaded

         case .failure(let error):
            likerStates[postPK] = .failed(Self.describe(error))

         case .halted:
            likerStates[postPK] = .idle
      }
   }

   func authorGrid(of authorID: Account.ID) -> [ProfileTile] {
      authorGrids[authorID] ?? []
   }

   func authorGridState(of authorID: Account.ID) -> LoadState {
      authorGridStates[authorID] ?? .idle
   }

   func loadAuthorGrid(authorID: Account.ID) async {
      let state = authorGridState(of: authorID)
      guard !state.isLoading, !state.hasLoaded else {
         return
      }

      authorGridStates[authorID] = .loading

      let engine = engine
      switch await gateway.read("more posts from this account", { () async throws(EngineError) in try await engine.moreFromAuthor(authorID: authorID) }) {
         case .success(let tiles):
            authorGrids[authorID] = tiles.map(ProfileTile.init)
            authorGridStates[authorID] = .loaded

         case .failure(let error):
            authorGridStates[authorID] = .failed(Self.describe(error))

         case .halted:
            authorGridStates[authorID] = .idle
      }
   }

   func replyState(of commentID: PostComment.ID) -> LoadState {
      replyStates[commentID] ?? .idle
   }

   func hasMoreReplies(to commentID: PostComment.ID) -> Bool {
      replyCursors[commentID] != nil
   }

   // The first call reads the first page of replies and each later one the page after it, the
   // cursor passed back exactly as it came. A reply already shown is not added twice.
   func loadReplies(to commentID: PostComment.ID, on postPK: String) async {
      guard !replyState(of: commentID).isLoading else {
         return
      }

      let cursor = replyCursors[commentID]
      let isFirstPage = !replyState(of: commentID).hasLoaded

      guard isFirstPage || cursor != nil else {
         return
      }

      replyStates[commentID] = .loading

      let engine = engine
      switch await gateway.read("the replies", { () async throws(EngineError) in try await engine.replies(postPK: postPK, commentID: commentID, after: cursor) }) {
         case .success(let page):
            let known = Set(comments[postPK]?.map(\.id) ?? [])
            let fresh = page.items.map(PostComment.init).filter { !known.contains($0.id) }

            comments[postPK, default: []].append(contentsOf: fresh)
            replyCursors[commentID] = page.hasNextPage ? page.endCursor : nil
            replyStates[commentID] = .loaded

         case .failure(let error):
            replyStates[commentID] = .failed(Self.describe(error))

         case .halted:
            replyStates[commentID] = isFirstPage ? .idle : .loaded
      }
   }

   // MARK: New posts
   // One read when a person asks. Nothing here polls.

   func checkForNewPosts() async {
      guard newPostsState != .checking else {
         return
      }

      newPostsState = .checking

      let engine = engine
      switch await gateway.read("checking for new posts", { () async throws(EngineError) in try await engine.hasNewPosts() }) {
         case .success(let hasNew):
            newPostsState = hasNew ? .available : .upToDate

         case .failure:
            newPostsState = .unknown

         case .halted:
            newPostsState = .unchecked
      }
   }

   func showNewPosts() async {
      newPostsState = .unchecked
      await load()
   }

   // MARK: Story reels
   // Under the engine's default Behavior reading a reel marks its first item seen, which the
   // author sees, so the read goes through the write path and no separate mark follows for that
   // item. Each later item is marked once, when it is first shown, as a browser does. A reel is
   // read once per tray row, and a second viewer waits on the read in flight.

   func storyReel(for authorID: Account.ID) -> StoryFrames? {
      storyReels[authorID]
   }

   func storyReelState(for authorID: Account.ID) -> LoadState {
      storyReelStates[authorID] ?? .idle
   }

   func loadStoryReel(_ authorID: Account.ID) async {
      let state = storyReelState(for: authorID)
      let isSettled = state == .loaded || state == .notFound

      guard !isSettled else {
         return
      }

      if let inFlight = storyReelReads[authorID] {
         await inFlight.value
         return
      }

      let read = Task { await performStoryReelRead(authorID) }
      storyReelReads[authorID] = read
      await read.value
      storyReelReads[authorID] = nil
   }

   private func performStoryReelRead(_ authorID: Account.ID) async {
      storyReelStates[authorID] = .loading

      let engine = engine
      switch await gateway.write("opening the story", { () async throws(EngineError) in try await engine.storyReel(userID: authorID) }) {
         case .success(let reel?):
            storyReels[authorID] = StoryFrames(reel)
            storyReelStates[authorID] = .loaded

            if let index = stories.firstIndex(where: { $0.id == authorID }) {
               stories[index].hasUnseenItems = false
            }

         case .success(nil):
            storyReelStates[authorID] = .notFound

         case .failure(let error):
            storyReelStates[authorID] = .failed(Self.describe(error))

         case .halted:
            storyReelStates[authorID] = .idle
      }
   }

   // The first item was marked by the read that returned the reel. A mark that fails is not
   // sent again.
   func markStoryFrameSeen(in reel: StoryFrames, at index: Int) {
      let isLaterItem = index > 0 && reel.frames.indices.contains(index)

      guard isLaterItem else {
         return
      }

      let itemID = reel.frames[index].id

      guard !markedStoryItemIDs.contains(itemID) else {
         return
      }

      markedStoryItemIDs.insert(itemID)

      let engine = engine
      let reelID = reel.reelID

      Task {
         _ = await gateway.write("marking the story seen") { () async throws(EngineError) in
            try await engine.markStorySeen(reelID: reelID, itemID: itemID)
         }
      }
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

// The items of one live reel or one highlight, as the viewers show them.
struct StoryFrames: Hashable, Sendable {
   struct Frame: Identifiable, Hashable, Sendable {
      let id: String
      let postedAt: Date
      let isVideo: Bool
      let mediaURL: URL?
   }

   let reelID: String
   let title: String?
   let frames: [Frame]
}

// What the last ask of feeds.has_new_posts said. Unknown when the read failed.
enum NewPostsState: Equatable, Sendable {
   case unchecked
   case checking
   case available
   case upToDate
   case unknown
}
