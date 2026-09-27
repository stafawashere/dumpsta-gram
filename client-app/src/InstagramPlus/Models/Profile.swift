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
