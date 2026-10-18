import Foundation

struct ProfileDetails: Hashable, Sendable {
   let account: Account
   var stats: AccountStats
   let category: String?
   let bio: String
   let website: String?
   let isPrivate: Bool

   // Nil where the engine gave no friendship status, as on the viewer's own profile, so an
   // unknown relationship is never shown as a settled one.
   let followsViewer: Bool?
   var isFollowing: Bool?
   var hasRequestedFollow: Bool?
   var isBlocking: Bool?
   var isMuting: Bool?
   var isCloseFriend: Bool?
}

struct Highlight: Identifiable, Hashable, Sendable {
   let id: String
   let title: String
}

struct ProfileTile: Identifiable, Hashable, Sendable {
   let id: String
   let code: String
   let kind: Post.Kind
   let likeCount: Int
   let commentCount: Int?
   var images: [Post.Rendition] = []

   var imageURL: URL? {
      images.first.flatMap { URL(string: $0.url) }
   }
}


struct Hashtag: Identifiable, Hashable, Sendable {
   let name: String

   // Nil where the engine gives no count, as search.hashtag does.
   let postCount: Int?

   var id: String { name }
}

struct Place: Identifiable, Hashable, Sendable {
   let id: String
   let name: String
   let postCount: Int
}
struct SavedCollection: Identifiable, Hashable, Sendable {
   let id: String
   let name: String
   let isAllPosts: Bool
   let mediaCount: Int?
   let coverURL: URL?
}
