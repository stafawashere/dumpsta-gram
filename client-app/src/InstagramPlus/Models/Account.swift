struct Account: Identifiable, Hashable, Sendable {
   let id: String
   let username: String
   let displayName: String
   let location: String?
   var isVerified = false

   var initials: String {
      let words = displayName.split(separator: " ").prefix(2)
      let letters = words.compactMap { $0.first }
      let hasLetters = !letters.isEmpty

      guard hasLetters else {
         return String(username.prefix(1)).uppercased()
      }

      return String(letters).uppercased()
   }
}

struct AccountStats: Hashable, Sendable {
   var postCount: Int
   var followerCount: Int
   var followingCount: Int
}
