import Observation

@MainActor
@Observable
final class ReelsStore {
   let gateway: EngineGateway

   private(set) var state = LoadState.idle
   private(set) var reels: [Reel] = []
   private(set) var pendingIDs: Set<Reel.ID> = []

   init(gateway: EngineGateway) {
      self.gateway = gateway
   }

   func load() async {
      state = .loading

      let engine = gateway.client
      switch await gateway.read("reels", { () async throws(EngineError) in try await engine.reels(after: nil) }) {
         case .success(let page):
            reels = page.items.map(Reel.init)
            state = .loaded

         case .failure(let error):
            state = .failed(HomeStore.describe(error))

         case .halted:
            state = .idle
      }
   }

   func toggleLike(reelID: Reel.ID) async {
      guard let index = reels.firstIndex(where: { $0.id == reelID }), !pendingIDs.contains(reelID) else {
         return
      }

      let willLike = !reels[index].isLiked
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

      switch outcome {
         case .success, .failure(.outcomeUnknown):
            break

         case .failure, .halted:
            guard let revertIndex = reels.firstIndex(where: { $0.id == reelID }) else {
               return
            }

            reels[revertIndex].isLiked = !willLike
            reels[revertIndex].likeCount += willLike ? -1 : 1
      }
   }

   func toggleSave(reelID: Reel.ID) async {
      guard let index = reels.firstIndex(where: { $0.id == reelID }), !pendingIDs.contains(reelID) else {
         return
      }

      let willSave = !reels[index].isSaved
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

      switch outcome {
         case .success, .failure(.outcomeUnknown):
            break

         case .failure, .halted:
            guard let revertIndex = reels.firstIndex(where: { $0.id == reelID }) else {
               return
            }

            reels[revertIndex].isSaved = !willSave
      }
   }
}
