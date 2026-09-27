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

   private(set) var tagResults: [Hashtag] = []
   private(set) var placeResults: [Place] = []
   private(set) var collectionTiles: [String: [ProfileTile]] = [:]
   private(set) var collectionStates: [String: LoadState] = [:]

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

            if case .success(let tags) = await gateway.read("tag search", { () async throws(EngineError) in try await engine.searchTags(query: needle) }) {
               tagResults = tags.map(Hashtag.init)
            }

            if case .success(let places) = await gateway.read("place search", { () async throws(EngineError) in try await engine.searchPlaces(query: needle) }) {
               placeResults = places.map(Place.init)
            }

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

   func collectionState(_ key: String) -> LoadState {
      collectionStates[key] ?? .idle
   }

   func tiles(for key: String) -> [ProfileTile] {
      collectionTiles[key] ?? []
   }

   func loadHashtag(_ name: String) async {
      let key = "tag:" + name
      collectionStates[key] = .loading

      let engine = gateway.client
      let hasCount = tagResults.contains { $0.name == name }

      if !hasCount, case .success(let tags) = await gateway.read("the hashtag", { () async throws(EngineError) in try await engine.searchTags(query: name) }) {
         tagResults = tags.map(Hashtag.init)
      }

      await store(key, gateway.read("the hashtag", { () async throws(EngineError) in try await engine.hashtagPosts(name: name) }))
   }

   func findPlace(named name: String) async -> Place? {
      if let known = placeResults.first(where: { $0.name == name }) {
         return known
      }

      let engine = gateway.client
      guard case .success(let places) = await gateway.read("the place", { () async throws(EngineError) in try await engine.searchPlaces(query: name) }) else {
         return nil
      }

      return places.map(Place.init).first { $0.name == name }
   }

   func loadPlace(_ placeID: String) async {
      let key = "place:" + placeID
      collectionStates[key] = .loading

      let engine = gateway.client
      await store(key, gateway.read("the place", { () async throws(EngineError) in try await engine.placePosts(placeID: placeID) }))
   }

   private func store(_ key: String, _ outcome: CallOutcome<Engine.Page<Engine.GridTile>>) async {
      switch outcome {
         case .success(let page):
            collectionTiles[key] = page.items.map(ProfileTile.init)
            collectionStates[key] = .loaded

         case .failure(let error):
            collectionStates[key] = .failed(HomeStore.describe(error))

         case .halted:
            collectionStates[key] = .idle
      }
   }
}
