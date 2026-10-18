import Foundation

// The stories tray, one account's live reel, one highlight, and marking a later item seen.
//
// Under the engine's default Behavior (mark_stories_seen) stories.reel and stories.highlight
// each send one visible write marking the reel's first item seen, and raise that write's error
// instead of returning the reel when it fails. Stores therefore send both reads through the
// gateway's write path and never send a separate mark for the first item. The bridge keeps
// each reel it read, because stories.mark_seen takes the engine's own item and reel objects.
extension PythonEngine {
   func storiesTray() async throws(EngineError) -> EngineResult<[Engine.StoryTrayEntry]> {
      try await guarded(.storiesTray) { bridge, handle throws(EngineError) in
         try await bridge.storiesTray(handle)
      }
   }

   func storyReel(userID: String) async throws(EngineError) -> EngineResult<Engine.StoryReel?> {
      try await guarded(.storyReels) { bridge, handle throws(EngineError) in
         try await bridge.storyReel(handle, userID: userID)
      }
   }

   func highlightReel(highlightID: String) async throws(EngineError) -> EngineResult<Engine.StoryReel> {
      try await guarded(.storyReels) { bridge, handle throws(EngineError) in
         try await bridge.highlightReel(handle, highlightID: highlightID)
      }
   }

   func markStorySeen(reelID: String, itemID: String) async throws(EngineError) -> EngineResult<Void> {
      try await guarded(.storyReels) { bridge, handle throws(EngineError) in
         try await bridge.markStorySeen(handle, reelID: reelID, itemID: itemID)
      }
   }
}
