import Foundation

struct Post: Identifiable, Hashable, Sendable {
   enum Kind: Hashable, Sendable {
      case photo
      case carousel
      case video
   }

   struct Location: Hashable, Sendable {
      let id: String
      let name: String
   }

   // One rendition the engine read, kept as it came so a download hands the engine the same
   // rendition back. versionType is set on video renditions only.
   struct Rendition: Hashable, Sendable {
      let url: String
      let width: Int
      let height: Int
      var versionType: Int?
   }

   struct CarouselPage: Identifiable, Hashable, Sendable {
      let id: String
      let kind: Kind
      let images: [Rendition]
      let videos: [Rendition]
   }

   let id: String
   let code: String
   let author: Account
   let location: Location?
   let caption: String
   let mediaDescription: String
   let postedAt: Date
   let kind: Kind
   var likeCount: Int
   var commentCount: Int
   var shareCount: Int?
   var saveCount: Int?

   // Nil while the like state is unknown, as after an uncertain like whose read back failed.
   var isLiked: Bool?

   // Nil where the engine does not say, which is always on the real engine today.
   var isSaved: Bool?
   var mediaURL: URL?
   var hidesLikeCount = false
   var commentsDisabled: Bool?
   var images: [Rendition] = []
   var videos: [Rendition] = []
   var videoDuration: Double?
   var carouselPages: [CarouselPage] = []
   var carouselCount: Int?
   var audioID: String?
   var audioTitle: String?

   var mediaSeed: String { code }
}

struct PostComment: Identifiable, Hashable, Sendable {
   let id: String
   let author: Account
   let text: String
   let postedAt: Date

   // Nil where the engine did not say, never read as zero or as not liked.
   var likeCount: Int?
   var isLiked: Bool?
   var isPending = false
   var parentID: String?
   var replyCount: Int?
}
