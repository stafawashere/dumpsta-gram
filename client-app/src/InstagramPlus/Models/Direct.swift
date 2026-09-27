import Foundation

struct DirectThread: Identifiable, Hashable, Sendable {
   let id: String
   let participants: [Account]
   let title: String
   let isGroup: Bool
   var isUnread: Bool
   var isMuted: Bool
   var lastActivity: Date
   var snippet: String?
   var lastSenderIsViewer: Bool
}

struct DirectMessage: Identifiable, Hashable, Sendable {
   enum Delivery: Hashable, Sendable {
      case sent
      case sending
      case failed
      case uncertain
   }

   var id: String
   let senderID: Account.ID
   let text: String
   let sentAt: Date
   var reactionCount: Int
   var delivery: Delivery = .sent
}

struct Note: Identifiable, Hashable, Sendable {
   let id: String
   let author: Account
   let text: String
   let isCloseFriends: Bool
   let postedAt: Date
}
