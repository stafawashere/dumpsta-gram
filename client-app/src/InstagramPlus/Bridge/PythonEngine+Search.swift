import Foundation

// Search, the viewer's recent searches, the explore grid and a place's first grid page.
//
// Account search is search.accounts. It sends the typeahead the client's Behavior names, the
// personalised one under PARITY. A client allowed only search-non-personalised sends the
// non-personalised typeahead instead, which answers accounts only. Recent hashtag and place
// entries carry no payload in the engine, and a place's grid is read by its Location.id only.
extension PythonEngine {
   func search(query: String) async throws(EngineError) -> EngineResult<[Engine.UserSummary]> {
      let isPersonalised = allows(.search)
      let capability: Capability = isPersonalised ? .search : .searchNonPersonalised

      return try await guarded(capability) { bridge, handle throws(EngineError) in
         try await bridge.searchAccounts(handle, query: query, personalised: isPersonalised)
      }
   }

   func recentSearches() async throws(EngineError) -> EngineResult<[Engine.RecentSearch]> {
      try await guarded(.recentSearches) { bridge, handle throws(EngineError) in
         try await bridge.recentSearches(handle)
      }
   }

   func explore(after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try await guarded(.explore) { bridge, handle throws(EngineError) in
         try await bridge.explore(handle, after: cursor)
      }
   }

   func explore() async throws(EngineError) -> EngineResult<[Engine.GridTile]> {
      switch try await explore(after: nil) {
         case .value(let page): .value(page.items)
         case .checkpoint(let checkpoint): .checkpoint(checkpoint)
      }
   }

   func placePosts(placeID: String) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try await guarded(.places) { bridge, handle throws(EngineError) in
         try await bridge.placePosts(handle, placeID: placeID)
      }
   }

   // search.top answers blended rows. Hashtag and place rows carry no payload in the engine.
   func searchTop(query: String) async throws(EngineError) -> EngineResult<[Engine.SearchResult]> {
      try await guarded(.searchTop) { bridge, handle throws(EngineError) in
         try await bridge.searchTop(handle, query: query)
      }
   }

   func searchKeyword(query: String) async throws(EngineError) -> EngineResult<Engine.KeywordResults> {
      try await guarded(.searchKeyword) { bridge, handle throws(EngineError) in
         try await bridge.searchKeyword(handle, query: query)
      }
   }

   // The header of one exact tag, with no post count.
   func hashtag(name: String) async throws(EngineError) -> EngineResult<Engine.HashtagHeader> {
      try await guarded(.hashtag) { bridge, handle throws(EngineError) in
         try await bridge.hashtag(handle, name: name)
      }
   }

   // Explore as one flat page of posts, the cursor passed back exactly as it came.
   func explorePosts(after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.Post>> {
      try await guarded(.explorePosts) { bridge, handle throws(EngineError) in
         try await bridge.explorePosts(handle, after: cursor)
      }
   }
}
