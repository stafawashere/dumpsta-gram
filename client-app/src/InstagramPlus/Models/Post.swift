import Foundation

struct Post: Identifiable, Hashable, Sendable {
   enum Kind: Hashable, Sendable {
      case photo
      case carousel
      case video
   }

   let id: String
   let code: String
   let author: Account
   let location: String?
   let caption: String
   let mediaDescription: String
   let postedAt: Date
   let kind: Kind
   var likeCount: Int
   var commentCount: Int
   var shareCount: Int?
   var saveCount: Int?
   var isLiked: Bool
   var isSaved: Bool
   var mediaURL: URL?
   var hidesLikeCount = false
   var commentsDisabled = false

   var mediaSeed: String { code }
}

struct PostComment: Identifiable, Hashable, Sendable {
   let id: String
   let author: Account
   let text: String
   let postedAt: Date
   var likeCount: Int
   var isLiked: Bool
   var isPending = false
}
