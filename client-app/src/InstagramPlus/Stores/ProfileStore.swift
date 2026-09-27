import Observation

enum ProfileTab: String, CaseIterable, Identifiable {
   case posts
   case reels
   case saved
   case tagged

   var id: String { rawValue }

   var title: String {
      switch self {
         case .posts: "Posts"
         case .reels: "Reels"
         case .saved: "Saved"
         case .tagged: "Tagged"
      }
   }

   var symbolName: String {
      switch self {
         case .posts: "square.grid.3x3"
         case .reels: "play.rectangle"
         case .saved: "bookmark"
         case .tagged: "person.crop.square"
      }
   }
}

enum FollowListKind: String, Identifiable {
   case followers
   case following

   var id: String { rawValue }

   var title: String {
      switch self {
         case .followers: "Followers"
         case .following: "Following"
      }
   }
}

@MainActor
@Observable
final class ProfileStore {
   private struct TileKey: Hashable {
      let accountID: Account.ID
      let tab: ProfileTab
   }

   let gateway: EngineGateway

   private(set) var profiles: [Account.ID: ProfileDetails] = [:]
   private(set) var profileStates: [Account.ID: LoadState] = [:]
   private(set) var highlights: [Account.ID: [Highlight]] = [:]
   private(set) var pendingFollowIDs: Set<Account.ID> = []
   private var tiles: [TileKey: [ProfileTile]] = [:]
   private var tileStates: [TileKey: LoadState] = [:]
   private var knownFollowing: [Account.ID: Bool] = [:]

   init(gateway: EngineGateway) {
      self.gateway = gateway
   }

   var viewerID: Account.ID { gateway.viewerID }

   var viewer: ProfileDetails? { profiles[viewerID] }

   var viewerAccount: Account {
      viewer?.account ?? Account(id: viewerID, username: "you", displayName: "You", location: nil)
   }

   func details(for accountID: Account.ID) -> ProfileDetails? {
      profiles[accountID]
   }

   func state(for accountID: Account.ID) -> LoadState {
      profileStates[accountID] ?? .idle
   }

   func isViewer(_ accountID: Account.ID) -> Bool {
      accountID == viewerID
   }

   func isFollowing(_ accountID: Account.ID) -> Bool {
      profiles[accountID]?.isFollowing ?? knownFollowing[accountID] ?? false
   }

   func hasRequested(_ accountID: Account.ID) -> Bool {
      profiles[accountID]?.hasRequestedFollow ?? false
   }

   func isPending(_ accountID: Account.ID) -> Bool {
      pendingFollowIDs.contains(accountID)
   }

   func noteFollowing(_ accountID: Account.ID, _ isFollowing: Bool) {
      knownFollowing[accountID] = isFollowing
   }

   func tiles(for accountID: Account.ID, tab: ProfileTab) -> [ProfileTile] {
      tiles[TileKey(accountID: accountID, tab: tab)] ?? []
   }

   func tileState(for accountID: Account.ID, tab: ProfileTab) -> LoadState {
      tileStates[TileKey(accountID: accountID, tab: tab)] ?? .idle
   }

   // MARK: Loading

   func load(_ accountID: Account.ID, includingContent: Bool = true) async {
      profileStates[accountID] = .loading

      let engine = gateway.client
      switch await gateway.read("the profile", { () async throws(EngineError) in try await engine.profile(id: accountID) }) {
         case .success(let profile):
            profiles[accountID] = ProfileDetails(profile)
            profileStates[accountID] = .loaded

         case .failure(.notFound):
            profileStates[accountID] = .notFound
            return

         case .failure(let error):
            profileStates[accountID] = .failed(HomeStore.describe(error))
            return

         case .halted:
            profileStates[accountID] = .idle
            return
      }

      guard includingContent else {
         return
      }

      await loadTiles(accountID, tab: .posts)

      if case .success(let engineHighlights) = await gateway.read("highlights", { () async throws(EngineError) in try await engine.highlights(userID: accountID) }) {
         highlights[accountID] = engineHighlights.map { Highlight(id: $0.id, title: $0.title) }
      }
   }

   func loadTiles(_ accountID: Account.ID, tab: ProfileTab) async {
      let key = TileKey(accountID: accountID, tab: tab)
      tileStates[key] = .loading

      let engine = gateway.client
      let outcome: CallOutcome<[Engine.GridTile]> = switch tab {
         case .posts:
            await pageItems(gateway.read("posts", { () async throws(EngineError) in try await engine.profilePosts(userID: accountID, after: nil) }))
         case .reels:
            await gateway.read("reels", { () async throws(EngineError) in try await engine.profileReels(userID: accountID) })
         case .saved:
            await gateway.read("saved posts", { () async throws(EngineError) in try await engine.savedPosts() })
         case .tagged:
            await gateway.read("tagged posts", { () async throws(EngineError) in try await engine.taggedPosts(userID: accountID) })
      }

      switch outcome {
         case .success(let engineTiles):
            tiles[key] = engineTiles.map(ProfileTile.init)
            tileStates[key] = .loaded

         case .failure(let error):
            tileStates[key] = .failed(HomeStore.describe(error))

         case .halted:
            tileStates[key] = .idle
      }
   }

   private func pageItems<Item>(_ outcome: CallOutcome<Engine.Page<Item>>) -> CallOutcome<[Item]> {
      switch outcome {
         case .success(let page): .success(page.items)
         case .failure(let error): .failure(error)
         case .halted: .halted
      }
   }

   func followList(_ kind: FollowListKind, of accountID: Account.ID) async -> CallOutcome<[Account]> {
      let engine = gateway.client
      let outcome = switch kind {
         case .followers: await gateway.read("followers", { () async throws(EngineError) in try await engine.followers(userID: accountID, after: nil) })
         case .following: await gateway.read("following", { () async throws(EngineError) in try await engine.following(userID: accountID, after: nil) })
      }

      switch outcome {
         case .success(let page): return .success(page.items.map(Account.init))
         case .failure(let error): return .failure(error)
         case .halted: return .halted
      }
   }

   // MARK: Following

   func toggleFollow(_ accountID: Account.ID) async {
      guard !pendingFollowIDs.contains(accountID) else {
         return
      }

      let wasFollowing = isFollowing(accountID)
      let wasRequested = hasRequested(accountID)
      let willFollow = !wasFollowing && !wasRequested
      let isPrivate = profiles[accountID]?.isPrivate ?? false

      applyFollow(accountID, following: willFollow && !isPrivate, requested: willFollow && isPrivate)
      pendingFollowIDs.insert(accountID)
      defer { pendingFollowIDs.remove(accountID) }

      let engine = gateway.client
      let outcome = await gateway.write(willFollow ? "the follow" : "the unfollow") { () async throws(EngineError) in
         if willFollow {
            return try await engine.follow(userID: accountID)
         }

         return try await engine.unfollow(userID: accountID)
      }

      switch outcome {
         case .success:
            await refreshProfileIfLoaded(accountID)

         case .failure(.outcomeUnknown):
            await load(accountID)

         case .failure, .halted:
            applyFollow(accountID, following: wasFollowing, requested: wasRequested)
      }
   }

   private func applyFollow(_ accountID: Account.ID, following: Bool, requested: Bool) {
      let wasFollowing = isFollowing(accountID)
      knownFollowing[accountID] = following

      guard profiles[accountID] != nil else {
         return
      }

      profiles[accountID]?.isFollowing = following
      profiles[accountID]?.hasRequestedFollow = requested

      let followerDelta = (following ? 1 : 0) - (wasFollowing ? 1 : 0)
      profiles[accountID]?.stats.followerCount += followerDelta
      profiles[viewerID]?.stats.followingCount += followerDelta
   }

   private func refreshProfileIfLoaded(_ accountID: Account.ID) async {
      guard profiles[accountID] != nil else {
         return
      }

      let engine = gateway.client
      if case .success(let profile) = await gateway.read("the profile", { () async throws(EngineError) in try await engine.profile(id: accountID) }) {
         profiles[accountID] = ProfileDetails(profile)
      }
   }
}
