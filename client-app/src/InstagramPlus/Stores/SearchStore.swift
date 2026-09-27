import Observation

@MainActor
@Observable
final class SearchStore {
   let gateway: EngineGateway

   private(set) var results: [Account] = []
   private(set) var resultsState = LoadState.idle
   private(set) var resultsQuery = ""
   private(set) var exploreTiles: [ProfileTile] = []
   private(set) var exploreState = LoadState.idle

   var recent: [Account] = []

   init(gateway: EngineGateway) {
      self.gateway = gateway
   }

   // Every search is a paced request, so typing waits for a pause before asking.
   func search(_ query: String) async {
      let needle = query.trimmingCharacters(in: .whitespaces)

      guard !needle.isEmpty else {
         results = []
         resultsState = .idle
         resultsQuery = ""
         return
      }

      try? await Task.sleep(for: .milliseconds(350))

      if Task.isCancelled {
         return
      }

      resultsState = .loading

      let engine = gateway.client
      switch await gateway.read("search", { () async throws(EngineError) in try await engine.search(query: needle) }) {
         case .success(let users):
            results = users.map(Account.init)
            resultsQuery = needle
            resultsState = .loaded

         case .failure(let error):
            resultsState = .failed(HomeStore.describe(error))

         case .halted:
            resultsState = .idle
      }
   }

   func loadExplore() async {
      guard !exploreState.hasLoaded else {
         return
      }

      exploreState = .loading

      let engine = gateway.client
      switch await gateway.read("explore", { () async throws(EngineError) in try await engine.explore() }) {
         case .success(let tiles):
            exploreTiles = tiles.map(ProfileTile.init)
            exploreState = .loaded

         case .failure(let error):
            exploreState = .failed(HomeStore.describe(error))

         case .halted:
            exploreState = .idle
      }
   }

   func remember(_ account: Account) {
      recent.removeAll { $0.id == account.id }
      recent.insert(account, at: 0)
   }

   func forget(_ accountID: Account.ID) {
      recent.removeAll { $0.id == accountID }
   }

   func clearRecent() {
      recent.removeAll()
   }
}
