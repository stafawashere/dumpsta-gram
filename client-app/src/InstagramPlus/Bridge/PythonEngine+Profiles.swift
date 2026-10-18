import Foundation

// Profile reads. By id costs one request. By username costs about seven under PARITY, so
// stores use an id whenever they have one. The posts grid is keyed on the username, reels,
// tagged posts and highlights are first pages only, and a posts or follow list cursor goes back
// to the engine exactly as it came.
extension PythonEngine {
   func profile(username: String) async throws(EngineError) -> EngineResult<Engine.Profile> {
      try await guarded(.profile) { bridge, handle throws(EngineError) in
         try await bridge.profile(handle, username: username)
      }
   }

   func profile(id userID: String) async throws(EngineError) -> EngineResult<Engine.Profile> {
      try await guarded(.profile) { bridge, handle throws(EngineError) in
         try await bridge.profile(handle, id: userID)
      }
   }

   func profilePosts(username: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try await guarded(.profilePosts) { bridge, handle throws(EngineError) in
         try await bridge.profilePosts(handle, username: username, after: cursor)
      }
   }

   func profileReels(userID: String) async throws(EngineError) -> EngineResult<[Engine.GridTile]> {
      try await guarded(.profileReels) { bridge, handle throws(EngineError) in
         try await bridge.profileReels(handle, userID: userID)
      }
   }

   func taggedPosts(userID: String) async throws(EngineError) -> EngineResult<[Engine.GridTile]> {
      try await guarded(.tagged) { bridge, handle throws(EngineError) in
         try await bridge.taggedPosts(handle, userID: userID)
      }
   }

   func highlights(userID: String) async throws(EngineError) -> EngineResult<[Engine.Highlight]> {
      try await guarded(.highlights) { bridge, handle throws(EngineError) in
         try await bridge.highlights(handle, userID: userID)
      }
   }

   // Two requests per page under PARITY, the second filling each row's friendship status.
   func followers(userID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.UserSummary>> {
      try await guarded(.followLists) { bridge, handle throws(EngineError) in
         try await bridge.followers(handle, userID: userID, after: cursor)
      }
   }

   func following(userID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.UserSummary>> {
      try await guarded(.followLists) { bridge, handle throws(EngineError) in
         try await bridge.following(handle, userID: userID, after: cursor)
      }
   }

   // profiles.suggested_for_you, the home rail's list. Each row's reason is not carried.
   func suggestedUsers() async throws(EngineError) -> EngineResult<[Engine.UserSummary]> {
      try await guarded(.suggestions) { bridge, handle throws(EngineError) in
         try await bridge.suggestedUsers(handle)
      }
   }

   // The mutual followers line and the similar accounts row, first pages only. Mutual followers
   // cost two requests under PARITY, the second filling each row's friendship status.
   func mutualFollowers(userID: String) async throws(EngineError) -> EngineResult<Engine.MutualFollowers> {
      try await guarded(.mutualFollowers) { bridge, handle throws(EngineError) in
         try await bridge.mutualFollowers(handle, userID: userID)
      }
   }

   func similarAccounts(userID: String) async throws(EngineError) -> EngineResult<[Engine.UserSummary]> {
      try await guarded(.similarAccounts) { bridge, handle throws(EngineError) in
         try await bridge.similarAccounts(handle, userID: userID)
      }
   }
}
