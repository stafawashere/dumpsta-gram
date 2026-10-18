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
   private(set) var archive: [ProfileTile] = []
   private(set) var archiveState = LoadState.idle
   private(set) var closeFriendIDs: Set<Account.ID> = []
   private(set) var blockedIDs: Set<Account.ID> = []
   private(set) var mutedIDs: Set<Account.ID> = []
   private(set) var relationshipsState = LoadState.idle
   private var knownAccounts: [Account.ID: Account] = [:]
   private var tiles: [TileKey: [ProfileTile]] = [:]
   private var tileStates: [TileKey: LoadState] = [:]
   private var tileCursors: [TileKey: String] = [:]
   private var tilesWithMorePages: Set<TileKey> = []
   private var tileReads: [TileKey: Task<Void, Never>] = [:]
   private var loadingMoreTiles: Set<TileKey> = []
   private var highlightStates: [Account.ID: LoadState] = [:]
   private var highlightReels: [Highlight.ID: StoryFrames] = [:]
   private var highlightReelStates: [Highlight.ID: LoadState] = [:]
   private var highlightReelReads: [Highlight.ID: Task<Void, Never>] = [:]
   private(set) var isMutedListKnown = true
   private var knownFollowing: [Account.ID: Bool] = [:]
   private var profileReads: [Account.ID: Task<Void, Never>] = [:]

   private(set) var mutualFollowers: [Account.ID: [Account]] = [:]
   private(set) var mutualFollowersHaveMore: Set<Account.ID> = []
   private(set) var mutualFollowerStates: [Account.ID: LoadState] = [:]
   private(set) var similarAccounts: [Account.ID: [Account]] = [:]
   private(set) var similarAccountStates: [Account.ID: LoadState] = [:]
   private(set) var collections: [SavedCollection] = []
   private(set) var collectionsState = LoadState.idle
   private(set) var hasMoreCollections = false

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

   // False when a loaded profile came without a friendship status and nothing since said whether
   // the viewer follows the account.
   func isRelationshipKnown(_ accountID: Account.ID) -> Bool {
      guard let details = profiles[accountID] else {
         return true
      }

      return details.isFollowing != nil || knownFollowing[accountID] != nil
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

   func highlightState(for accountID: Account.ID) -> LoadState {
      highlightStates[accountID] ?? .idle
   }

   func hasMoreTiles(for accountID: Account.ID, tab: ProfileTab) -> Bool {
      tilesWithMorePages.contains(TileKey(accountID: accountID, tab: tab))
   }

   // Only the posts grid has a cursor. The reels, tagged and saved reads say whether more exist
   // and offer no way to read them.
   func canLoadMoreTiles(tab: ProfileTab) -> Bool {
      tab == .posts
   }

   // SavedPost carries no comment count on the real engine, so a saved tile's hover shows likes
   // only instead of a zero.
   func isCommentCountKnown(_ tileID: ProfileTile.ID) -> Bool {
      let tile = tiles.values.lazy.flatMap { $0 }.first { $0.id == tileID }
      return tile?.commentCount != nil
   }

   // MARK: Loading

   // The shell and the Profile page both ask for the viewer at launch. A profile that is
   // already loaded is not read again, and a second caller waits on the read in flight. The
   // posts grid and the highlights are read once each, and again only on a retry.
   func load(_ accountID: Account.ID, includingContent: Bool = true) async {
      let isLoaded = profileStates[accountID] == .loaded

      if !isLoaded {
         await readProfile(accountID)
      }

      let hasProfile = profileStates[accountID] == .loaded

      guard includingContent, hasProfile else {
         return
      }

      if !tileState(for: accountID, tab: .posts).hasLoaded {
         await loadTiles(accountID, tab: .posts)
      }

      if highlightStates[accountID] != .loaded {
         await loadHighlights(accountID)
      }
   }

   private func loadHighlights(_ accountID: Account.ID) async {
      highlightStates[accountID] = .loading

      let engine = gateway.client
      switch await gateway.read("highlights", { () async throws(EngineError) in try await engine.highlights(userID: accountID) }) {
         case .success(let engineHighlights):
            highlights[accountID] = engineHighlights.map { Highlight(id: $0.id, title: $0.title) }
            highlightStates[accountID] = .loaded

         case .failure(let error):
            highlightStates[accountID] = .failed(HomeStore.describe(error))

         case .halted:
            highlightStates[accountID] = .idle
      }
   }

   private func readProfile(_ accountID: Account.ID) async {
      if let inFlight = profileReads[accountID] {
         await inFlight.value
         return
      }

      let read = Task { await performProfileRead(accountID) }
      profileReads[accountID] = read
      await read.value
      profileReads[accountID] = nil
   }

   private func performProfileRead(_ accountID: Account.ID) async {
      profileStates[accountID] = .loading

      let engine = gateway.client
      switch await gateway.read("the profile", { () async throws(EngineError) in try await engine.profile(id: accountID) }) {
         case .success(let profile):
            let details = ProfileDetails(profile)
            profiles[accountID] = details
            knownAccounts[accountID] = details.account
            profileStates[accountID] = .loaded

         case .failure(.notFound):
            profileStates[accountID] = .notFound

         case .failure(let error):
            profileStates[accountID] = .failed(HomeStore.describe(error))

         case .halted:
            profileStates[accountID] = .idle
      }
   }

   // The Profile page's own task and load() can both ask for the first page of a tab; the
   // second waits on the read in flight.
   func loadTiles(_ accountID: Account.ID, tab: ProfileTab) async {
      let key = TileKey(accountID: accountID, tab: tab)

      if let inFlight = tileReads[key] {
         await inFlight.value
         return
      }

      let read = Task { await performTileRead(key) }
      tileReads[key] = read
      await read.value
      tileReads[key] = nil
   }

   private func performTileRead(_ key: TileKey) async {
      tileStates[key] = .loading

      let accountID = key.accountID
      let engine = gateway.client
      let outcome: CallOutcome<Engine.Page<Engine.GridTile>>

      switch key.tab {
         case .posts:
            guard let username = profiles[accountID]?.account.username else {
               tileStates[key] = .idle
               return
            }

            outcome = await gateway.read("posts", { () async throws(EngineError) in try await engine.profilePosts(username: username, after: nil) })

         case .reels:
            outcome = await gateway.read("reels", { () async throws(EngineError) in try await engine.profileReelsPage(userID: accountID) })

         case .saved:
            outcome = await gateway.read("saved posts", { () async throws(EngineError) in try await engine.savedPostsPage() })

         case .tagged:
            outcome = await gateway.read("tagged posts", { () async throws(EngineError) in try await engine.taggedPostsPage(userID: accountID) })
      }

      switch outcome {
         case .success(let page):
            tiles[key] = []
            apply(page, to: key)
            tileStates[key] = .loaded

         case .failure(let error):
            tileStates[key] = .failed(HomeStore.describe(error))

         case .halted:
            tileStates[key] = .idle
      }
   }

   // Only the posts grid pages. The cursor goes back to the engine exactly as it came.
   func loadMoreTiles(_ accountID: Account.ID, tab: ProfileTab) async {
      let key = TileKey(accountID: accountID, tab: tab)
      let canLoadMore = canLoadMoreTiles(tab: tab) && tilesWithMorePages.contains(key) && !loadingMoreTiles.contains(key)

      guard canLoadMore, let cursor = tileCursors[key], let username = profiles[accountID]?.account.username else {
         return
      }

      loadingMoreTiles.insert(key)
      defer { loadingMoreTiles.remove(key) }

      let engine = gateway.client
      if case .success(let page) = await gateway.read("more posts", { () async throws(EngineError) in try await engine.profilePosts(username: username, after: cursor) }) {
         apply(page, to: key)
      }
   }

   private func apply(_ page: Engine.Page<Engine.GridTile>, to key: TileKey) {
      let known = Set((tiles[key] ?? []).map(\.id))
      let fresh = page.items.filter { !known.contains($0.pk) }

      tiles[key, default: []].append(contentsOf: fresh.map(ProfileTile.init))
      tileCursors[key] = page.endCursor

      if page.hasNextPage {
         tilesWithMorePages.insert(key)
      } else {
         tilesWithMorePages.remove(key)
      }
   }

   struct FollowListPage {
      let accounts: [Account]
      let hasNextPage: Bool
      let endCursor: String?
   }

   func followList(_ kind: FollowListKind, of accountID: Account.ID, after cursor: String? = nil) async -> CallOutcome<FollowListPage> {
      let engine = gateway.client
      let outcome = switch kind {
         case .followers: await gateway.read("followers", { () async throws(EngineError) in try await engine.followers(userID: accountID, after: cursor) })
         case .following: await gateway.read("following", { () async throws(EngineError) in try await engine.following(userID: accountID, after: cursor) })
      }

      switch outcome {
         case .success(let page):
            let accounts = page.items.map(Account.init)
            remember(accounts)
            return .success(FollowListPage(accounts: accounts, hasNextPage: page.hasNextPage, endCursor: page.endCursor))

         case .failure(let error):
            return .failure(error)

         case .halted:
            return .halted
      }
   }

   // MARK: Profile extras
   // Read when a person opens them, never with the profile. Mutual followers and collections
   // are first pages only, and the result says whether more exist.

   func mutualFollowerState(for accountID: Account.ID) -> LoadState {
      mutualFollowerStates[accountID] ?? .idle
   }

   func loadMutualFollowers(_ accountID: Account.ID) async {
      guard !mutualFollowerState(for: accountID).isLoading else {
         return
      }

      mutualFollowerStates[accountID] = .loading

      let engine = gateway.client
      switch await gateway.read("mutual followers", { () async throws(EngineError) in try await engine.mutualFollowers(userID: accountID) }) {
         case .success(let mutual):
            let accounts = mutual.accounts.map(Account.init)
            remember(accounts)
            mutualFollowers[accountID] = accounts

            if mutual.hasMore {
               mutualFollowersHaveMore.insert(accountID)
            } else {
               mutualFollowersHaveMore.remove(accountID)
            }

            mutualFollowerStates[accountID] = .loaded

         case .failure(let error):
            mutualFollowerStates[accountID] = .failed(HomeStore.describe(error))

         case .halted:
            mutualFollowerStates[accountID] = .idle
      }
   }

   func similarAccountState(for accountID: Account.ID) -> LoadState {
      similarAccountStates[accountID] ?? .idle
   }

   func loadSimilarAccounts(_ accountID: Account.ID) async {
      guard !similarAccountState(for: accountID).isLoading else {
         return
      }

      similarAccountStates[accountID] = .loading

      let engine = gateway.client
      switch await gateway.read("similar accounts", { () async throws(EngineError) in try await engine.similarAccounts(userID: accountID) }) {
         case .success(let summaries):
            let accounts = summaries.map(Account.init)
            remember(accounts)
            similarAccounts[accountID] = accounts
            similarAccountStates[accountID] = .loaded

         case .failure(let error):
            similarAccountStates[accountID] = .failed(HomeStore.describe(error))

         case .halted:
            similarAccountStates[accountID] = .idle
      }
   }

   func loadCollections() async {
      guard !collectionsState.isLoading else {
         return
      }

      collectionsState = .loading

      let engine = gateway.client
      switch await gateway.read("collections", { () async throws(EngineError) in try await engine.savedCollections() }) {
         case .success(let saved):
            collections = saved.collections.map(SavedCollection.init)
            hasMoreCollections = saved.hasMore
            collectionsState = .loaded

         case .failure(let error):
            collectionsState = .failed(HomeStore.describe(error))

         case .halted:
            collectionsState = .idle
      }
   }

   // MARK: Highlight reels
   // Reading a highlight marks its first item seen under the engine's default Behavior, so the
   // read goes through the write path, once per highlight.

   func highlightReel(_ highlightID: Highlight.ID) -> StoryFrames? {
      highlightReels[highlightID]
   }

   func highlightReelState(_ highlightID: Highlight.ID) -> LoadState {
      highlightReelStates[highlightID] ?? .idle
   }

   func loadHighlightReel(_ highlightID: Highlight.ID) async {
      guard highlightReelState(highlightID) != .loaded else {
         return
      }

      if let inFlight = highlightReelReads[highlightID] {
         await inFlight.value
         return
      }

      let read = Task { await performHighlightReelRead(highlightID) }
      highlightReelReads[highlightID] = read
      await read.value
      highlightReelReads[highlightID] = nil
   }

   private func performHighlightReelRead(_ highlightID: Highlight.ID) async {
      highlightReelStates[highlightID] = .loading

      let engine = gateway.client
      switch await gateway.write("opening the highlight", { () async throws(EngineError) in try await engine.highlightReel(highlightID: highlightID) }) {
         case .success(let reel):
            highlightReels[highlightID] = StoryFrames(reel)
            highlightReelStates[highlightID] = .loaded

         case .failure(.notFound):
            highlightReelStates[highlightID] = .notFound

         case .failure(let error):
            highlightReelStates[highlightID] = .failed(HomeStore.describe(error))

         case .halted:
            highlightReelStates[highlightID] = .idle
      }
   }

   // MARK: Following

   func toggleFollow(_ accountID: Account.ID) async {
      let isUnknown = !isViewer(accountID) && !isRelationshipKnown(accountID)

      guard !pendingFollowIDs.contains(accountID), !isUnknown else {
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
            await readProfile(accountID)

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

   // MARK: Profile editing and relationships

   func resolve(username: String) async -> Account.ID? {
      if let known = knownAccounts.values.first(where: { $0.username == username }) {
         return known.id
      }

      let engine = gateway.client
      switch await gateway.read("the profile", { () async throws(EngineError) in try await engine.profile(username: username) }) {
         case .success(let profile):
            let details = ProfileDetails(profile)
            profiles[profile.id] = details
            knownAccounts[profile.id] = details.account
            profileStates[profile.id] = .loaded
            return profile.id

         case .failure(.notFound):
            gateway.post(Notice(tone: .info, title: "No account named \(username)", message: "It may have been renamed or removed."))
            return nil

         case .failure, .halted:
            return nil
      }
   }

   func account(_ accountID: Account.ID) -> Account? {
      knownAccounts[accountID] ?? profiles[accountID]?.account
   }

   func remember(_ accounts: [Account]) {
      for account in accounts {
         knownAccounts[account.id] = account
      }
   }

   func editProfile(fullName: String, biography: String, website: String?) async -> Bool {
      let engine = gateway.client
      let outcome = await gateway.write("the profile edit") { () async throws(EngineError) in
         try await engine.editProfile(fullName: fullName, biography: biography, externalURL: website)
      }

      switch outcome {
         case .success(let profile):
            profiles[viewerID] = ProfileDetails(profile)
            return true

         case .failure(.outcomeUnknown):
            await load(viewerID, includingContent: false)
            return true

         case .failure, .halted:
            return false
      }
   }

   func removeFollower(_ accountID: Account.ID) async -> Bool {
      let engine = gateway.client
      let outcome = await gateway.write("removing the follower") { () async throws(EngineError) in try await engine.removeFollower(userID: accountID) }

      guard case .success = outcome else {
         return false
      }

      profiles[viewerID]?.stats.followerCount -= 1
      return true
   }

   func loadArchive() async {
      archiveState = .loading

      let engine = gateway.client
      switch await gateway.read("the archive", { () async throws(EngineError) in try await engine.archivedStories() }) {
         case .success(let tiles):
            archive = tiles.map(ProfileTile.init)
            archiveState = .loaded

         case .failure(let error):
            archiveState = .failed(HomeStore.describe(error))

         case .halted:
            archiveState = .idle
      }
   }

   func loadRelationships() async {
      relationshipsState = .loading

      let engine = gateway.client
      switch await gateway.read("your lists", { () async throws(EngineError) in try await engine.relationships() }) {
         case .success(let relationships):
            closeFriendIDs = Set(relationships.closeFriendIDs)
            blockedIDs = Set(relationships.blockedIDs)
            mutedIDs = Set(relationships.mutedIDs)
            isMutedListKnown = relationships.isMutedListKnown

            for summary in relationships.closeFriends + relationships.blocked where knownAccounts[summary.id] == nil {
               knownAccounts[summary.id] = Account(summary)
            }

            relationshipsState = .loaded

         case .failure(let error):
            relationshipsState = .failed(HomeStore.describe(error))

         case .halted:
            relationshipsState = .idle
      }
   }

   func setCloseFriend(_ accountID: Account.ID, included: Bool) async {
      toggle(&closeFriendIDs, accountID, included)
      profiles[accountID]?.isCloseFriend = included

      let engine = gateway.client
      let outcome = await gateway.write(included ? "adding a close friend" : "removing a close friend") { () async throws(EngineError) in
         try await engine.setCloseFriend(userID: accountID, included: included)
      }

      if case .success = outcome {
         return
      }

      await loadRelationships()
   }

   func setBlocked(_ accountID: Account.ID, blocked: Bool) async {
      toggle(&blockedIDs, accountID, blocked)
      profiles[accountID]?.isBlocking = blocked

      let engine = gateway.client
      let outcome = await gateway.write(blocked ? "the block" : "the unblock") { () async throws(EngineError) in
         try await engine.setBlocked(userID: accountID, blocked: blocked)
      }

      switch outcome {
         case .success, .failure(.outcomeUnknown):
            await load(accountID, includingContent: !blocked)

         case .failure, .halted:
            await loadRelationships()
            await load(accountID, includingContent: false)
      }
   }

   func setMuted(_ accountID: Account.ID, muted: Bool) async {
      toggle(&mutedIDs, accountID, muted)
      profiles[accountID]?.isMuting = muted

      let engine = gateway.client
      let outcome = await gateway.write(muted ? "the mute" : "the unmute") { () async throws(EngineError) in
         try await engine.setMuted(userID: accountID, muted: muted)
      }

      if case .success = outcome {
         return
      }

      await loadRelationships()
   }

   private func toggle(_ set: inout Set<Account.ID>, _ accountID: Account.ID, _ isIncluded: Bool) {
      if isIncluded {
         set.insert(accountID)
      } else {
         set.remove(accountID)
      }
   }
}
