import Foundation

// One post by its code, a rendition download, comments and the post writes. A download is one
// CDN fetch and no Instagram request. A comments cursor goes back to the engine exactly as it came.
// Publishing hands the engine the local file paths as they are, and the engine uploads them.
// Each write is sent once through the gateway's write path, and the engine's pacer, write
// budget and write stop decide whether it leaves at all.
extension PythonEngine {
   func post(code: String) async throws(EngineError) -> EngineResult<Engine.Post> {
      try await guarded(.post) { bridge, handle throws(EngineError) in
         try await bridge.post(handle, code: code)
      }
   }

   func download(image: Engine.MediaImage, to destination: URL) async throws(EngineError) -> EngineResult<URL> {
      try await guarded(.download) { bridge, handle throws(EngineError) in
         try await bridge.download(handle, image: image, to: destination)
      }
   }

   func comments(postPK: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.Comment>> {
      try await guarded(.comments) { bridge, handle throws(EngineError) in
         try await bridge.comments(handle, postPK: postPK, after: cursor)
      }
   }

   func like(postPK: String) async throws(EngineError) -> EngineResult<Void> {
      try await guarded(.mediaWrites) { bridge, handle throws(EngineError) in
         try await bridge.like(handle, postPK: postPK)
      }
   }

   func unlike(postPK: String) async throws(EngineError) -> EngineResult<Void> {
      try await guarded(.mediaWrites) { bridge, handle throws(EngineError) in
         try await bridge.unlike(handle, postPK: postPK)
      }
   }

   func comment(postPK: String, text: String) async throws(EngineError) -> EngineResult<Engine.Comment> {
      try await guarded(.mediaWrites) { bridge, handle throws(EngineError) in
         try await bridge.comment(handle, postPK: postPK, text: text)
      }
   }

   func deleteComment(postPK: String, commentID: String) async throws(EngineError) -> EngineResult<Void> {
      try await guarded(.mediaWrites) { bridge, handle throws(EngineError) in
         try await bridge.deleteComment(handle, postPK: postPK, commentID: commentID)
      }
   }

   func deletePost(postPK: String, code: String) async throws(EngineError) -> EngineResult<Void> {
      try await guarded(.mediaWrites) { bridge, handle throws(EngineError) in
         try await bridge.deletePost(handle, postPK: postPK, code: code)
      }
   }

   func publishPhoto(imageURL: URL, caption: String) async throws(EngineError) -> EngineResult<Engine.PublishedPost> {
      try await guarded(.mediaWrites) { bridge, handle throws(EngineError) in
         try await bridge.publishPhoto(handle, imagePath: imageURL.path, caption: caption)
      }
   }

   func publishCarousel(imageURLs: [URL], caption: String) async throws(EngineError) -> EngineResult<Engine.PublishedPost> {
      let imagePaths = imageURLs.map(\.path)

      return try await guarded(.mediaWrites) { bridge, handle throws(EngineError) in
         try await bridge.publishCarousel(handle, imagePaths: imagePaths, caption: caption)
      }
   }

   // MARK: Post page extras
   // Each is read only when a person opens the part of the post page that shows it. media.page
   // costs six requests under the default Behavior, the others one each. Likers are a sample
   // with no cursor, and a replies cursor goes back to the engine exactly as it came.

   func postPage(code: String) async throws(EngineError) -> EngineResult<Engine.PostPage> {
      try await guarded(.postPage) { bridge, handle throws(EngineError) in
         try await bridge.postPage(handle, code: code)
      }
   }

   func post(pk: String) async throws(EngineError) -> EngineResult<Engine.Post> {
      try await guarded(.postByID) { bridge, handle throws(EngineError) in
         try await bridge.post(handle, pk: pk)
      }
   }

   func likers(postPK: String) async throws(EngineError) -> EngineResult<[Engine.UserSummary]> {
      try await guarded(.likers) { bridge, handle throws(EngineError) in
         try await bridge.likers(handle, postPK: postPK)
      }
   }

   func moreFromAuthor(authorID: String) async throws(EngineError) -> EngineResult<[Engine.GridTile]> {
      try await guarded(.moreFromAuthor) { bridge, handle throws(EngineError) in
         try await bridge.moreFromAuthor(handle, authorID: authorID)
      }
   }

   func replies(postPK: String, commentID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.Comment>> {
      try await guarded(.replies) { bridge, handle throws(EngineError) in
         try await bridge.replies(handle, postPK: postPK, commentID: commentID, after: cursor)
      }
   }
}
