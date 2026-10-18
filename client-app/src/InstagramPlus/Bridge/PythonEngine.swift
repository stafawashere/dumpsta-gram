import Foundation

extension EngineError {
   // Codes the bridge raises itself. Neither ever came from Instagram.
   static let notWiredCode = "not_wired"
   static let bridgeFailureCode = "bridge_failure"
   static let sessionUnavailableCode = "session_unavailable"
}

// One account's real engine client, behind the same protocols as DummyEngine (ADR-0004: one
// client per adopted session). It holds a handle into PythonBridge and no Python value.
//
// The engine raises CheckpointRequired but does not refuse later calls on its own, because
// Session.checkpoint_active is set only by the cookie sync. So a checkpoint or a revoked
// session stops this client until a person reconnects it, on top of the gateway's own stop.
// Nothing here retries, paces, or decides whether a call succeeded.
actor PythonEngine: AppEngine, ReportsSessionStop {
   enum Capability: String, CaseIterable, Sendable {
      case profile
      case feed
      case post
      case download
      case comments
      case mediaWrites = "media-writes"
      case socialWrites = "social-writes"
      case inbox
      case messages
      case messageRequests = "message-requests"
      case unreadCounts = "unread-counts"
      case notes
      case directWrites = "direct-writes"
      case events
      case storiesTray = "stories-tray"
      case storyReels = "story-reels"
      case profilePosts = "profile-posts"
      case profileReels = "profile-reels"
      case tagged
      case saved
      case highlights
      case followLists = "follow-lists"
      case relationships
      case search
      case searchNonPersonalised = "search-non-personalised"
      case recentSearches = "recent-searches"
      case explore
      case places
      case reels
      case activity
      case followRequests = "follow-requests"
      case suggestions
      case postPage = "post-page"
      case postByID = "post-by-id"
      case likers
      case moreFromAuthor = "more-from-author"
      case replies
      case mutualFollowers = "mutual-followers"
      case similarAccounts = "similar-accounts"
      case collections
      case newPosts = "new-posts"
      case searchTop = "search-top"
      case searchKeyword = "search-keyword"
      case hashtag
      case explorePosts = "explore-posts"
      case audio
   }

   private enum Stop {
      case checkpoint(Checkpoint)
      case revoked
      case unavailable(EngineError)
   }

   nonisolated let viewerID: String

   private let bridge: PythonBridge
   nonisolated let sessionFile: URL?
   private let enabled: Set<Capability>
   private var handle: PythonBridge.Handle?
   private var stop: Stop?

   private var eventBuffer: [Engine.Event] = []
   private var drainTask: Task<Void, Never>?

   init(bridge: PythonBridge, opened: PythonBridge.OpenedSession?, sessionFile: URL?, enabled: Set<Capability>, viewerID: String? = nil) {
      self.bridge = bridge
      self.viewerID = opened?.viewerID ?? viewerID ?? ""
      self.handle = opened?.handle
      self.sessionFile = sessionFile
      self.enabled = enabled
   }

   private var notWired: EngineError {
      .upstreamRejected(code: EngineError.notWiredCode)
   }

   func allows(_ capability: Capability) -> Bool {
      enabled.contains(capability)
   }

   // MARK: Session lifecycle

   // A person confirmed a checkpoint or asked to reconnect. The session file is opened again as
   // a fresh client. The call the stop interrupted is not replayed.
   func reconnect() async {
      stop = nil

      guard let sessionFile else {
         return
      }

      await close()

      do throws(EngineError) {
         switch try await bridge.open(sessionFile: sessionFile) {
            case .value(let opened):
               handle = opened.handle

            case .checkpoint(let checkpoint):
               stop = .checkpoint(checkpoint)
         }
      } catch {
         // Any other failure leaves no open client behind. The client stays stopped with that
         // error until a person reconnects, rather than looking active and failing call by call.
         stop = error == .authenticationFailed ? .revoked : .unavailable(error)
      }
   }

   // What the last reconnect left behind, so the gateway does not call a stopped client active.
   func sessionStop() -> SessionState? {
      switch stop {
         case .checkpoint(let checkpoint): .checkpoint(checkpoint)
         case .revoked: .revoked
         case .unavailable, nil: nil
      }
   }

   func reopenFailure() -> EngineError? {
      guard case .unavailable(let error) = stop else {
         return nil
      }

      return error
   }

   func close() async {
      await stopEvents()

      if let handle {
         await bridge.close(handle)
      }

      handle = nil
   }

   func guarded<Value: Sendable>(
      _ capability: Capability,
      _ body: (PythonBridge, PythonBridge.Handle) async throws(EngineError) -> EngineResult<Value>
   ) async throws(EngineError) -> EngineResult<Value> {
      switch stop {
         case .checkpoint(let checkpoint):
            return .checkpoint(checkpoint)

         case .revoked:
            throw .authenticationFailed

         case .unavailable:
            throw .upstreamRejected(code: EngineError.sessionUnavailableCode)

         case nil:
            break
      }

      guard enabled.contains(capability) else {
         throw notWired
      }

      guard let handle else {
         throw .authenticationFailed
      }

      do throws(EngineError) {
         let result = try await body(bridge, handle)

         if case .checkpoint(let checkpoint) = result {
            stop = .checkpoint(checkpoint)
         }

         return result
      } catch {
         if error == .authenticationFailed {
            stop = .revoked
         }

         throw error
      }
   }

   // MARK: Events

   // The listener polls inside the engine. This drains its buffer on the bridge every 200 ms
   // into a Swift buffer, and drainEvents hands that buffer to the store.
   func startEvents(since messageID: String?) async {
      await stopEvents()

      do throws(EngineError) {
         let started = try await guarded(.events) { bridge, handle throws(EngineError) in
            try await bridge.startEvents(handle, since: messageID)
         }

         if case .checkpoint(let checkpoint) = started {
            eventBuffer.append(.listenerStopped(.checkpoint(checkpoint)))
            return
         }
      } catch {
         eventBuffer.append(.listenerStopped(.error(error)))
         return
      }

      drainTask = Task { [weak self] in
         while !Task.isCancelled {
            try? await Task.sleep(for: .milliseconds(200))

            guard let self, await self.pumpEvents() else {
               return
            }
         }
      }
   }

   func drainEvents() async -> [Engine.Event] {
      let drained = eventBuffer
      eventBuffer.removeAll()
      return drained
   }

   func stopEvents() async {
      drainTask?.cancel()
      drainTask = nil

      if let handle {
         await bridge.stopEvents(handle)
      }
   }

   private func pumpEvents() async -> Bool {
      guard let handle else {
         return false
      }

      let events = await bridge.drainEvents(handle)
      eventBuffer.append(contentsOf: events)

      for case .listenerStopped(let reason) in events {
         switch reason {
            case .checkpoint(let checkpoint):
               stop = .checkpoint(checkpoint)

            case .error(.authenticationFailed):
               stop = .revoked

            case .error:
               break
         }

         drainTask = nil
         await bridge.stopEvents(handle)
         return false
      }

      return true
   }

   // MARK: Grid first pages

   func profileReelsPage(userID: String) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try await guarded(.profileReels) { bridge, handle throws(EngineError) in
         try await bridge.profileReelsPage(handle, userID: userID)
      }
   }

   func taggedPostsPage(userID: String) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try await guarded(.tagged) { bridge, handle throws(EngineError) in
         try await bridge.taggedPostsPage(handle, userID: userID)
      }
   }

   func savedPostsPage() async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try await guarded(.saved) { bridge, handle throws(EngineError) in
         try await bridge.savedPostsPage(handle)
      }
   }

   // MARK: Not wired yet
   // Each later wiring slice replaces a block here with a bridge call.

   // The engine marks an item, not an account, and never by user id. See PythonEngine+Stories.
   func markStorySeen(userID: String) async throws(EngineError) -> EngineResult<Void> { throw notWired }
   // The engine types no activity kind, so every row comes through activityFeed() untyped.
   func activity() async throws(EngineError) -> EngineResult<[Engine.ActivityEntry]> { throw notWired }
   func resolveFollowRequest(userID: String, approve: Bool) async throws(EngineError) -> EngineResult<Void> { throw notWired }
   func profileActivity() async throws(EngineError) -> EngineResult<Engine.ProfileActivity> { throw notWired }
   // The engine keys the posts grid on the username. See profilePosts(username:after:).
   func profilePosts(userID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> { throw notWired }
   func save(postPK: String) async throws(EngineError) -> EngineResult<Void> { throw notWired }
   func unsave(postPK: String) async throws(EngineError) -> EngineResult<Void> { throw notWired }
   func hidePost(postPK: String) async throws(EngineError) -> EngineResult<Void> { throw notWired }
   func sharePost(postPK: String, threadFBIDs: [String]) async throws(EngineError) -> EngineResult<Void> { throw notWired }
   func likeComment(postPK: String, commentID: String, liked: Bool) async throws(EngineError) -> EngineResult<Void> { throw notWired }
   func replyToComment(postPK: String, parentCommentID: String, text: String) async throws(EngineError) -> EngineResult<Engine.Comment> { throw notWired }

   func resolveMessageRequest(threadFBID: String, accept: Bool) async throws(EngineError) -> EngineResult<Void> { throw notWired }
   func createThread(userIDs: [String]) async throws(EngineError) -> EngineResult<Engine.DirectThread> { throw notWired }
   func react(threadFBID: String, messageID: String, emoji: String?) async throws(EngineError) -> EngineResult<Void> { throw notWired }
   func sendReply(threadFBID: String, text: String, replyingTo messageID: String) async throws(EngineError) -> EngineResult<Engine.SentMessage> { throw notWired }
   func sendPhoto(threadFBID: String, imageURL: URL) async throws(EngineError) -> EngineResult<Engine.SentMessage> { throw notWired }
   func setThreadMuted(threadFBID: String, muted: Bool) async throws(EngineError) -> EngineResult<Void> { throw notWired }

   func publishStory(imageURL: URL) async throws(EngineError) -> EngineResult<Void> { throw notWired }
   func likeStory(userID: String) async throws(EngineError) -> EngineResult<Void> { throw notWired }
   func archivedStories() async throws(EngineError) -> EngineResult<[Engine.GridTile]> { throw notWired }

   func editProfile(fullName: String, biography: String, externalURL: String?) async throws(EngineError) -> EngineResult<Engine.Profile> { throw notWired }
   func removeFollower(userID: String) async throws(EngineError) -> EngineResult<Void> { throw notWired }
   func setCloseFriend(userID: String, included: Bool) async throws(EngineError) -> EngineResult<Void> { throw notWired }
   func setBlocked(userID: String, blocked: Bool) async throws(EngineError) -> EngineResult<Void> { throw notWired }
   func setMuted(userID: String, muted: Bool) async throws(EngineError) -> EngineResult<Void> { throw notWired }

   // Engine gaps. search.top returns hashtag and place rows with no payload, so neither a tag
   // nor a place id can come from a search, and the engine has no hashtag grid.
   func searchTags(query: String) async throws(EngineError) -> EngineResult<[Engine.Hashtag]> { throw notWired }
   func searchPlaces(query: String) async throws(EngineError) -> EngineResult<[Engine.Place]> { throw notWired }
   func hashtagPosts(name: String) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> { throw notWired }
}
