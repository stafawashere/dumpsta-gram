import Foundation

// Follow and unfollow. Stores read the profile back through profile(id:) to learn whether a
// follow became a request, because the engine returns nothing from either write.
extension PythonEngine {
   func follow(userID: String) async throws(EngineError) -> EngineResult<Void> {
      try await guarded(.socialWrites) { bridge, handle throws(EngineError) in
         try await bridge.follow(handle, userID: userID)
      }
   }

   func unfollow(userID: String) async throws(EngineError) -> EngineResult<Void> {
      try await guarded(.socialWrites) { bridge, handle throws(EngineError) in
         try await bridge.unfollow(handle, userID: userID)
      }
   }
}
