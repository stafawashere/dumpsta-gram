import Observation

@MainActor
@Observable
final class ReelsStore {
   let gateway: EngineGateway

   private(set) var state = LoadState.idle
   private(set) var reels: [Reel] = []
   private(set) var pendingIDs: Set<Reel.ID> = []
   private(set) var isLoadingMore = false
   private(set) var hasMoreReels = false
   private var nextCursor: String?

   private(set) var audioPages: [String: AudioPageContent] = [:]
   private(set) var audioStates: [String: LoadState] = [:]
   private var audioCursors: [String: String] = [:]
   private var loadingMoreAudio: Set<String> = []

   init(gateway: EngineGateway) {
      self.gateway = gateway
   }

   func load() async {
      state = .loading
      nextCursor = nil

      let engine = gateway.client
      switch await gateway.read("reels", { () async throws(EngineError) in try await engine.reels(after: nil) }) {
         case .success(let page):
            reels = []
            apply(page)
            state = .loaded

         case .failure(let error):
            state = .failed(HomeStore.describe(error))

         case .halted:
            state = .idle
      }
   }

   func loadMore() async {
      let canLoadMore = hasMoreReels && !isLoadingMore && state.hasLoaded

      guard canLoadMore else {
         return
      }

      isLoadingMore = true
      defer { isLoadingMore = false }

      let engine = gateway.client
      let cursor = nextCursor

      if case .success(let page) = await gateway.read("more reels", { () async throws(EngineError) in try await engine.reels(after: cursor) }) {
         apply(page)
      }
   }

   // The engine's reels carry no saved flag, so a reel without one shows its bookmark as unknown
   // rather than as not saved.
   func isSaveStateKnown(_ reelID: Reel.ID) -> Bool {
      reels.first { $0.id == reelID }?.isSaved != nil
   }

   func isLikeStateKnown(_ reelID: Reel.ID) -> Bool {
      reels.first { $0.id == reelID }?.isLiked != nil
   }

   private func apply(_ page: Engine.Page<Engine.Reel>) {
      let knownIDs = Set(reels.map(\.id))
      let newReels = page.items.filter { !knownIDs.contains($0.post.pk) }

      reels += newReels.map(Reel.init)
      hasMoreReels = page.hasNextPage
      nextCursor = page.endCursor
   }

   func toggleLike(reelID: Reel.ID) async {
      guard let index = reels.firstIndex(where: { $0.id == reelID }), !pendingIDs.contains(reelID) else {
         return
      }

      let wasLiked = reels[index].isLiked
      let previousLikeCount = reels[index].likeCount
      let willLike = wasLiked != true
      reels[index].isLiked = willLike
      reels[index].likeCount += willLike ? 1 : -1
      pendingIDs.insert(reelID)
      defer { pendingIDs.remove(reelID) }

      let engine = gateway.client
      let outcome = await gateway.write(willLike ? "the like" : "the unlike") { () async throws(EngineError) in
         if willLike {
            return try await engine.like(postPK: reelID)
         }

         return try await engine.unlike(postPK: reelID)
      }

      // Unknown after a failed read-back keeps the last count the engine gave, not the
      // optimistic one.
      let restore: (Int, Bool?) -> Void = { index, isLiked in
         self.reels[index].isLiked = isLiked
         self.reels[index].likeCount = previousLikeCount
      }

      await settle(outcome, reelID: reelID, revert: { restore($0, wasLiked) }, markUnknown: { restore($0, nil) })
   }

   func toggleSave(reelID: Reel.ID) async {
      guard let index = reels.firstIndex(where: { $0.id == reelID }), !pendingIDs.contains(reelID) else {
         return
      }

      let wasSaved = reels[index].isSaved
      let willSave = wasSaved != true
      reels[index].isSaved = willSave
      pendingIDs.insert(reelID)
      defer { pendingIDs.remove(reelID) }

      let engine = gateway.client
      let outcome = await gateway.write(willSave ? "the save" : "the unsave") { () async throws(EngineError) in
         if willSave {
            return try await engine.save(postPK: reelID)
         }

         return try await engine.unsave(postPK: reelID)
      }

      await settle(outcome, reelID: reelID, revert: { self.reels[$0].isSaved = wasSaved }, markUnknown: { self.reels[$0].isSaved = nil })
   }

   // A failed write is rolled back. An uncertain one is never sent again: the reel is read back
   // through the post read, so the interface shows whatever happened upstream. When the read
   // back fails too, the state the write touched is marked unknown and the optimistic value goes.
   private func settle(_ outcome: CallOutcome<Void>, reelID: Reel.ID, revert: (Int) -> Void, markUnknown: (Int) -> Void) async {
      switch outcome {
         case .success:
            break

         case .failure(.outcomeUnknown):
            let didReadBack = await readBack(reelID: reelID)

            if !didReadBack, let index = reels.firstIndex(where: { $0.id == reelID }) {
               markUnknown(index)
            }

         case .failure, .halted:
            guard let index = reels.firstIndex(where: { $0.id == reelID }) else {
               return
            }

            revert(index)
      }
   }

   // media.by_id, one request, where reading by code under the default Behavior is six.
   private func readBack(reelID: Reel.ID) async -> Bool {
      guard reels.contains(where: { $0.id == reelID }) else {
         return false
      }

      let engine = gateway.client
      guard case .success(let post) = await gateway.read("the reel", { () async throws(EngineError) in try await engine.post(pk: reelID) }) else {
         return false
      }

      guard let index = reels.firstIndex(where: { $0.id == reelID }) else {
         return true
      }

      reels[index].isLiked = post.hasLiked
      reels[index].likeCount = post.likeCount
      reels[index].commentCount = post.commentCount
      reels[index].isSaved = post.hasSaved
      return true
   }

   // MARK: Audio pages
   // Read when a person opens an audio, never ahead of it. The first page comes from feeds.audio
   // and each later one from feeds.audio_clips, the cursor passed back exactly as it came.

   func audioPage(_ audioID: String) -> AudioPageContent? {
      audioPages[audioID]
   }

   func audioState(_ audioID: String) -> LoadState {
      audioStates[audioID] ?? .idle
   }

   func hasMoreClips(_ audioID: String) -> Bool {
      audioCursors[audioID] != nil
   }

   func isLoadingMoreClips(_ audioID: String) -> Bool {
      loadingMoreAudio.contains(audioID)
   }

   func loadAudio(_ audioID: String, title: String) async {
      let state = audioState(audioID)
      guard !state.isLoading, !state.hasLoaded else {
         return
      }

      audioStates[audioID] = .loading

      let engine = gateway.client
      switch await gateway.read("the audio", { () async throws(EngineError) in try await engine.audio(audioID: audioID, after: nil) }) {
         case .success(let page):
            audioPages[audioID] = AudioPageContent(page, fallbackTitle: title)
            audioCursors[audioID] = page.hasNextPage ? page.endCursor : nil
            audioStates[audioID] = .loaded

         case .failure(.notFound):
            audioStates[audioID] = .notFound

         case .failure(let error):
            audioStates[audioID] = .failed(HomeStore.describe(error))

         case .halted:
            audioStates[audioID] = .idle
      }
   }

   func loadMoreClips(_ audioID: String) async {
      guard let cursor = audioCursors[audioID], !loadingMoreAudio.contains(audioID) else {
         return
      }

      loadingMoreAudio.insert(audioID)
      defer { loadingMoreAudio.remove(audioID) }

      let engine = gateway.client
      guard case .success(let page) = await gateway.read("more clips", { () async throws(EngineError) in try await engine.audioClips(audioID: audioID, after: cursor) }) else {
         return
      }

      let known = Set(audioPages[audioID]?.clips.map(\.id) ?? [])
      let fresh = page.items.map(ProfileTile.init).filter { !known.contains($0.id) }

      audioPages[audioID]?.clips.append(contentsOf: fresh)
      audioCursors[audioID] = page.hasNextPage ? page.endCursor : nil
   }
}

// One audio's page as the audio view shows it. The artist is nil where the engine read no
// audio model.
struct AudioPageContent: Hashable, Sendable {
   let title: String
   let artist: String?
   let clipsCount: Int
   let isRestricted: Bool
   var clips: [ProfileTile]
}
