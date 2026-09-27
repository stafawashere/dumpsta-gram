struct Reel: Identifiable, Hashable, Sendable {
   let id: String
   let code: String
   let author: Account
   let caption: String
   let audioTitle: String
   var likeCount: Int
   var commentCount: Int
   var shareCount: Int?
   var isLiked: Bool
   var isSaved: Bool
}
