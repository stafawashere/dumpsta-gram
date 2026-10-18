import Foundation

struct Story: Identifiable, Hashable, Sendable {
   let author: Account
   let itemCount: Int?
   let postedAt: Date

   // Nil where the engine does not say whether the viewer has seen the newest item.
   var hasUnseenItems: Bool?
   var seenAt: Date?

   var id: String { author.id }
}
