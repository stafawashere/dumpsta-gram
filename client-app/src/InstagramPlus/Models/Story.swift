import Foundation

struct Story: Identifiable, Hashable, Sendable {
   let author: Account
   let itemCount: Int
   let postedAt: Date
   var hasUnseenItems: Bool

   var id: String { author.id }
}
