import Foundation

struct Reel: Identifiable, Hashable, Sendable {
   let id: String
   let code: String
   let author: Account
   let caption: String
   let audioTitle: String
   var likeCount: Int
   var commentCount: Int
   var shareCount: Int?
   var isLiked: Bool?
   var isSaved: Bool?

   // The audio's id as the engine gave it, which its audio page takes. Nil where the reel
   // carries no audio model.
   var audioID: String?

   // The renditions the engine read with the reel, as they came.
   var images: [Post.Rendition] = []
   var videos: [Post.Rendition] = []

   var posterURL: URL? {
      images.first.flatMap { URL(string: $0.url) }
   }
}
