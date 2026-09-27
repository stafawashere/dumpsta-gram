struct ProfileDetails: Hashable, Sendable {
   let account: Account
   var stats: AccountStats
   let category: String?
   let bio: String
   let website: String?
   let isPrivate: Bool
   let followsViewer: Bool
   var isFollowing: Bool
   var hasRequestedFollow: Bool
   var isBlocking = false
   var isMuting = false
   var isCloseFriend = false
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
   let commentCount: Int
}


struct Hashtag: Identifiable, Hashable, Sendable {
   let name: String
   let postCount: Int

   var id: String { name }
}

struct Place: Identifiable, Hashable, Sendable {
   let id: String
   let name: String
   let postCount: Int
}