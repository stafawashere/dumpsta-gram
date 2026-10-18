import Foundation

// The home timeline and the reels feed. The bridge decodes each page on its actor, the home
// feed into Engine.FeedItem with every one of the engine's nine kinds, and a cursor goes back
// to the engine exactly as it came. A reel carries no play count and no saved flag.
extension PythonEngine {
   func feed(after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.FeedItem>> {
      try await guarded(.feed) { bridge, handle throws(EngineError) in
         try await bridge.feed(handle, after: cursor)
      }
   }

   func reels(after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.Reel>> {
      try await guarded(.reels) { bridge, handle throws(EngineError) in
         try await bridge.reels(handle, after: cursor)
      }
   }

   // One read, sent only when a person asks. Nothing here polls it.
   func hasNewPosts() async throws(EngineError) -> EngineResult<Bool> {
      try await guarded(.newPosts) { bridge, handle throws(EngineError) in
         try await bridge.hasNewPosts(handle)
      }
   }

   // An audio's page and the clips using it. audio_id comes from the post as the engine gave it.
   func audio(audioID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.AudioPage> {
      try await guarded(.audio) { bridge, handle throws(EngineError) in
         try await bridge.audio(handle, audioID: audioID, after: cursor)
      }
   }

   func audioClips(audioID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.Post>> {
      try await guarded(.audio) { bridge, handle throws(EngineError) in
         try await bridge.audioClips(handle, audioID: audioID, after: cursor)
      }
   }
}
