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
   private(set) var isLoadingMoreExplore = false
   private(set) var hasMoreExplore = false
   private var exploreCursor: String?

   var recent: [Account] = []
   private(set) var recentKeywords: [String] = []
   private(set) var recentWithoutDetailsCount = 0
   private(set) var recentState = LoadState.idle

   private(set) var tagResults: [Hashtag] = []
   private(set) var tagSearchState = LoadState.idle
   private(set) var placeResults: [Place] = []
   private(set) var placeSearchState = LoadState.idle
   private(set) var collectionTiles: [String: [ProfileTile]] = [:]
   private(set) var collectionStates: [String: LoadState] = [:]

   private(set) var topRows: [TopSearchRow] = []
   private(set) var topWithoutDetailsCount = 0
   private(set) var topState = LoadState.idle
   private var topQuery = ""

   private(set) var keywordTiles: [ProfileTile] = []
   private(set) var keywordHasMore = false
   private(set) var keywordState = LoadState.idle
   private var keywordQuery = ""

   private(set) var exactTag: Hashtag?
   private(set) var exactTagState = LoadState.idle
   private var exactTagQuery = ""

   private(set) var explorePosts: [ProfileTile] = []
   private(set) var explorePostsState = LoadState.idle
   private(set) var hasMoreExplorePosts = false
   private(set) var isLoadingMoreExplorePosts = false
   private var explorePostsCursor: String?

   static let notWiredDescription = "Instagram+ cannot search this yet. Nothing was sent."

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

            await searchTags(needle)
            await searchPlaces(needle)

         case .failure(let error):
            resultsState = .failed(HomeStore.describe(error))

         case .halted:
            resultsState = .idle
      }
   }

   // Once the engine answers that tag or place search is not wired, later searches stop asking,
   // because the answer cannot change within a launch and each ask posts a notice.
   private func searchTags(_ needle: String) async {
      guard !Self.isNotWired(tagSearchState) else {
         return
      }

      let engine = gateway.client
      switch await gateway.read("tag search", { () async throws(EngineError) in try await engine.searchTags(query: needle) }) {
         case .success(let tags):
            tagResults = tags.map(Hashtag.init)
            tagSearchState = .loaded

         case .failure(let error):
            tagResults = []
            tagSearchState = .failed(Self.describe(error))

         case .halted:
            tagSearchState = .idle
      }
   }

   private func searchPlaces(_ needle: String) async {
      guard !Self.isNotWired(placeSearchState) else {
         return
      }

      let engine = gateway.client
      switch await gateway.read("place search", { () async throws(EngineError) in try await engine.searchPlaces(query: needle) }) {
         case .success(let places):
            placeResults = places.map(Place.init)
            placeSearchState = .loaded

         case .failure(let error):
            placeResults = []
            placeSearchState = .failed(Self.describe(error))

         case .halted:
            placeSearchState = .idle
      }
   }

   func loadExplore() async {
      guard !exploreState.hasLoaded else {
         return
      }

      exploreState = .loading

      let engine = gateway.client
      switch await gateway.read("explore", { () async throws(EngineError) in try await engine.explore(after: nil) }) {
         case .success(let page):
            exploreTiles = page.items.map(ProfileTile.init)
            hasMoreExplore = page.hasNextPage
            exploreCursor = page.endCursor
            exploreState = .loaded

         case .failure(let error):
            exploreState = .failed(HomeStore.describe(error))

         case .halted:
            exploreState = .idle
      }
   }

   func loadMoreExplore() async {
      let canLoadMore = hasMoreExplore && !isLoadingMoreExplore && exploreState.hasLoaded

      guard canLoadMore else {
         return
      }

      isLoadingMoreExplore = true
      defer { isLoadingMoreExplore = false }

      let engine = gateway.client
      let cursor = exploreCursor

      if case .success(let page) = await gateway.read("more of explore", { () async throws(EngineError) in try await engine.explore(after: cursor) }) {
         let knownIDs = Set(exploreTiles.map(\.id))
         exploreTiles += page.items.map(ProfileTile.init).filter { !knownIDs.contains($0.id) }
         hasMoreExplore = page.hasNextPage
         exploreCursor = page.endCursor
      }
   }

   // MARK: Search extras
   // Each is read for the current query only when its tab is opened, and once per query.

   func loadTop(_ query: String) async {
      let needle = query.trimmingCharacters(in: .whitespaces)
      let isCurrent = needle == topQuery && (topState.hasLoaded || topState.isLoading)

      guard !needle.isEmpty, !isCurrent else {
         return
      }

      topQuery = needle
      topState = .loading

      let engine = gateway.client
      switch await gateway.read("top results", { () async throws(EngineError) in try await engine.searchTop(query: needle) }) {
         case .success(let results):
            topRows = results.compactMap(TopSearchRow.init)
            topWithoutDetailsCount = results.count - topRows.count
            topState = .loaded

         case .failure(let error):
            topState = .failed(Self.describe(error))

         case .halted:
            topState = .idle
      }
   }

   func loadKeyword(_ query: String) async {
      let needle = query.trimmingCharacters(in: .whitespaces)
      let isCurrent = needle == keywordQuery && (keywordState.hasLoaded || keywordState.isLoading)

      guard !needle.isEmpty, !isCurrent else {
         return
      }

      keywordQuery = needle
      keywordState = .loading

      let engine = gateway.client
      switch await gateway.read("posts for the search", { () async throws(EngineError) in try await engine.searchKeyword(query: needle) }) {
         case .success(let results):
            keywordTiles = results.posts.map(ProfileTile.init)
            keywordHasMore = results.hasMore
            keywordState = .loaded

         case .failure(let error):
            keywordState = .failed(Self.describe(error))

         case .halted:
            keywordState = .idle
      }
   }

   // The engine reads the header of one exact tag. A leading # typed in the search box is not
   // part of the tag's name.
   func loadExactTag(_ query: String) async {
      var needle = query.trimmingCharacters(in: .whitespaces)

      if needle.hasPrefix("#") {
         needle.removeFirst()
      }

      let isSettled = exactTagState.isLoading || exactTagState.hasLoaded || exactTagState == .notFound
      let alreadyAsked = needle == exactTagQuery && isSettled

      guard !needle.isEmpty, !alreadyAsked else {
         return
      }

      exactTagQuery = needle
      exactTag = nil
      exactTagState = .loading

      let engine = gateway.client
      switch await gateway.read("the hashtag", { () async throws(EngineError) in try await engine.hashtag(name: needle) }) {
         case .success(let header):
            exactTag = Hashtag(header)
            exactTagState = .loaded

         case .failure(.notFound):
            exactTagState = .notFound

         case .failure(let error):
            exactTagState = .failed(Self.describe(error))

         case .halted:
            exactTagState = .idle
      }
   }

   func isTagSearchUnavailable() -> Bool {
      Self.isNotWired(tagSearchState)
   }

   func loadExplorePosts() async {
      guard !explorePostsState.hasLoaded, !explorePostsState.isLoading else {
         return
      }

      explorePostsState = .loading

      let engine = gateway.client
      switch await gateway.read("explore posts", { () async throws(EngineError) in try await engine.explorePosts(after: nil) }) {
         case .success(let page):
            explorePosts = page.items.map(ProfileTile.init)
            hasMoreExplorePosts = page.hasNextPage
            explorePostsCursor = page.endCursor
            explorePostsState = .loaded

         case .failure(let error):
            explorePostsState = .failed(HomeStore.describe(error))

         case .halted:
            explorePostsState = .idle
      }
   }

   func loadMoreExplorePosts() async {
      let canLoadMore = hasMoreExplorePosts && !isLoadingMoreExplorePosts && explorePostsState.hasLoaded

      guard canLoadMore else {
         return
      }

      isLoadingMoreExplorePosts = true
      defer { isLoadingMoreExplorePosts = false }

      let engine = gateway.client
      let cursor = explorePostsCursor

      if case .success(let page) = await gateway.read("more explore posts", { () async throws(EngineError) in try await engine.explorePosts(after: cursor) }) {
         let knownIDs = Set(explorePosts.map(\.id))
         explorePosts += page.items.map(ProfileTile.init).filter { !knownIDs.contains($0.id) }
         hasMoreExplorePosts = page.hasNextPage
         explorePostsCursor = page.endCursor
      }
   }

   // The engine's recent searches. Hashtag and place entries carry no payload in the engine, so
   // they are counted rather than shown. Adding and clearing recents have no engine write, so
   // remember, forget and clearRecent change this list on this Mac only.
   func loadRecent() async {
      guard !recentState.hasLoaded, !recentState.isLoading else {
         return
      }

      recentState = .loading

      let engine = gateway.client
      switch await gateway.read("recent searches", { () async throws(EngineError) in try await engine.recentSearches() }) {
         case .success(let entries):
            let engineAccounts = entries.compactMap(\.account).map(Account.init)
            let rememberedHere = recent.filter { account in !engineAccounts.contains { $0.id == account.id } }

            recent = rememberedHere + engineAccounts
            recentKeywords = entries.compactMap(\.keyword)
            recentWithoutDetailsCount = entries.filter { $0.account == nil && $0.keyword == nil }.count
            recentState = .loaded

         case .failure(let error):
            recentState = .failed(Self.describe(error))

         case .halted:
            recentState = .idle
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
      recentKeywords.removeAll()
      recentWithoutDetailsCount = 0
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

      if !hasCount {
         switch await gateway.read("the hashtag", { () async throws(EngineError) in try await engine.searchTags(query: name) }) {
            case .success(let tags):
               tagResults = tags.map(Hashtag.init)

            // The engine has no tag search, but it reads the header of one exact tag, without
            // a post count.
            case .failure(.upstreamRejected(let code)) where code == EngineError.notWiredCode:
               tagSearchState = .failed(Self.notWiredDescription)

               if case .success(let header) = await gateway.read("the hashtag", { () async throws(EngineError) in try await engine.hashtag(name: name) }) {
                  tagResults.append(Hashtag(header))
               }

            case .failure, .halted:
               break
         }
      }

      await store(key, gateway.read("the hashtag", { () async throws(EngineError) in try await engine.hashtagPosts(name: name) }))
   }

   // A place page needs the place's id. This answers only from places the engine already
   // returned to this store with their ids, and never searches a name to find one. A route that
   // carries only a name, such as a post's location today, finds nothing here.
   func findPlace(named name: String) async -> Place? {
      placeResults.first { $0.name == name }
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

   private static func describe(_ error: EngineError) -> String {
      error == .upstreamRejected(code: EngineError.notWiredCode) ? notWiredDescription : HomeStore.describe(error)
   }

   private static func isNotWired(_ state: LoadState) -> Bool {
      state == .failed(notWiredDescription)
   }
}

// One row of the blended top results that the page can show. Hashtag and place rows carry no
// payload in the engine, so they are counted instead.
struct TopSearchRow: Identifiable, Hashable, Sendable {
   enum Content: Hashable, Sendable {
      case account(Account)
      case keyword(String)
   }

   let id: String
   let content: Content
}
