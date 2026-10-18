import Foundation

// The viewer's own lists and activity: saved posts, close friends, blocked accounts, the
// activity feed and pending follow requests. Saved posts and follow requests are first pages
// only. The engine has no muted accounts read, and the result says so. Activity rows arrive
// untyped, and reading the feed marks nothing seen.
extension PythonEngine {
   func savedPosts() async throws(EngineError) -> EngineResult<[Engine.GridTile]> {
      try await guarded(.saved) { bridge, handle throws(EngineError) in
         try await bridge.savedPosts(handle)
      }
   }

   func relationships() async throws(EngineError) -> EngineResult<Engine.Relationships> {
      try await guarded(.relationships) { bridge, handle throws(EngineError) in
         try await bridge.relationships(handle)
      }
   }

   func activityFeed() async throws(EngineError) -> EngineResult<Engine.ActivityFeed> {
      try await guarded(.activity) { bridge, handle throws(EngineError) in
         try await bridge.activityFeed(handle)
      }
   }

   func followRequests() async throws(EngineError) -> EngineResult<[Engine.UserSummary]> {
      try await guarded(.followRequests) { bridge, handle throws(EngineError) in
         try await bridge.followRequests(handle)
      }
   }

   // The viewer's saved collections, first page only.
   func savedCollections() async throws(EngineError) -> EngineResult<Engine.SavedCollections> {
      try await guarded(.collections) { bridge, handle throws(EngineError) in
         try await bridge.savedCollections(handle)
      }
   }
}
