import Foundation

struct ActivityItem: Identifiable, Hashable, Sendable {
   enum Kind: Hashable, Sendable {
      case likedPost
      case likedComment(String)
      case commented(String)
      case mentioned(String)
      case followed
   }

   let id: String
   let kind: Kind
   let actors: [Account]
   let occurredAt: Date
   let mediaCode: String?
}
