import Foundation

// Swift mirrors of the engine's public models, field for field with engine/tests/public_surface.txt
// at 1.1.0. The bridge decodes into these on the Python queue. Types marked proposed have no
// counterpart in the engine yet and exist so the dummy engine can serve pages the engine cannot.
enum Engine {
   struct Page<Item: Sendable>: Sendable {
      let items: [Item]
      let hasNextPage: Bool
      let endCursor: String?
   }

   struct MediaImage: Sendable, Hashable {
      let url: String
      let width: Int
      let height: Int
   }

   struct PostAuthor: Sendable, Hashable {
      let id: String
      let username: String
      let fullName: String
      let profilePicURL: String
      let isPrivate: Bool
      let isVerified: Bool
      let isFollowing: Bool?
   }

   enum FeedItemKind: String, Sendable {
      case post = "media"
      case storiesTray = "stories_netego"
      case suggestedUsers = "suggested_users"
      case ad = "ad"
      case endOfFeed = "end_of_feed_demarcator"
   }

   struct FeedItem: Sendable {
      let kind: FeedItemKind
      let post: Post?
   }

   struct Post: Sendable, Hashable {
      let id: String
      let pk: String
      let code: String
      let author: PostAuthor
      let caption: String?
      let takenAt: Date
      let likeCount: Int
      let commentCount: Int
      let hasLiked: Bool
      let isSeen: Bool
      let mediaType: Int
      let images: [MediaImage]
      let carouselMediaCount: Int?
      let accessibilityCaption: String?
      let likeAndViewCountsDisabled: Bool

      // Proposed. Not in the 1.1.0 surface.
      let location: String?
      let hasSaved: Bool?
      let commentsDisabled: Bool?
   }

   struct CommentAuthor: Sendable, Hashable {
      let id: String
      let username: String
      let isVerified: Bool
      let profilePicURL: String
   }

   struct Comment: Sendable, Hashable {
      let id: String
      let author: CommentAuthor
      let text: String
      let createdAt: Date
      let likeCount: Int?
      let hasLiked: Bool?
      let parentCommentID: String?
      let replyCount: Int?
   }

   struct FriendshipStatus: Sendable, Hashable {
      let following: Bool
      let followedBy: Bool
      let outgoingRequest: Bool
      let incomingRequest: Bool
      let blocking: Bool
      let muting: Bool
      let isBestie: Bool
      let isRestricted: Bool
   }

   struct Profile: Sendable, Hashable {
      let id: String
      let username: String
      let fullName: String
      let biography: String
      let category: String?
      let externalURL: String?
      let followerCount: Int
      let followingCount: Int
      let mediaCount: Int
      let totalClipsCount: Int
      let isPrivate: Bool
      let isVerified: Bool
      let profilePicURL: String
      let friendshipStatus: FriendshipStatus?
   }

   struct ThreadParticipant: Sendable, Hashable {
      let userID: String
      let username: String
      let fullName: String
      let isVerified: Bool
   }

   struct DirectThread: Sendable, Hashable {
      let threadFBID: String
      let title: String
      let participants: [ThreadParticipant]
      let isGroup: Bool
      let isUnread: Bool
      let isMarkedUnread: Bool
      let isMuted: Bool
      let isPinned: Bool
      let lastActivityAt: Date
      let lastMessageID: String?
      let snippet: String?
   }

   struct MessageSender: Sendable, Hashable {
      let fbid: String
      let igid: String?
      let name: String?
   }

   struct Reaction: Sendable, Hashable {
      let emoji: String
      let senderFBID: String

      static let heart = "\u{2764}\u{FE0F}"
   }

   struct Message: Sendable, Hashable {
      let id: String
      let threadFBID: String
      let sender: MessageSender
      let text: String?
      let sentAt: Date
      let contentType: String
      let reactions: [Reaction]
      let repliedToMessageID: String?
      let offlineThreadingID: String?
   }

   struct SentMessage: Sendable, Hashable {
      let id: String
      let offlineThreadingID: String
      let threadFBID: String
      let sentAt: Date
   }

   enum NoteAudience: Int, Sendable, CaseIterable {
      case mutualFollows = 0
      case closeFriends = 1
   }

   struct Note: Sendable, Hashable {
      let id: String
      let authorID: String
      let authorUsername: String?
      let text: String
      let audience: NoteAudience
      let createdAt: Date
   }

   struct UnreadCounts: Sendable, Hashable {
      let inbox: Int
      let pending: Int
   }

   struct MessageRequests: Sendable {
      let pending: [DirectThread]
      let spam: [DirectThread]
   }

   struct PublishedPost: Sendable, Hashable {
      let id: String
      let pk: String
      let code: String
      let takenAt: Date
   }

   enum Event: Sendable {
      case newMessage(Message)
      case eventsDropped(count: Int?, threadFBID: String?)
      case listenerStopped(ListenerStopReason)
   }

   enum ListenerStopReason: Sendable, Equatable {
      case checkpoint(Checkpoint)
      case error(EngineError)
   }

   // Proposed. Everything below has no method in the 1.1.0 surface.

   struct UserSummary: Sendable, Hashable {
      let id: String
      let username: String
      let fullName: String
      let isVerified: Bool
      let isPrivate: Bool
   }

   struct StoryTrayEntry: Sendable, Hashable {
      let user: UserSummary
      let itemCount: Int
      let latestAt: Date
      let hasUnseen: Bool
   }

   struct Highlight: Sendable, Hashable {
      let id: String
      let title: String
      let itemCount: Int
   }

   struct GridTile: Sendable, Hashable {
      enum Kind: Sendable, Hashable {
         case photo
         case carousel
         case video
      }

      let pk: String
      let code: String
      let kind: Kind
      let likeCount: Int
      let commentCount: Int
   }

   struct Reel: Sendable, Hashable {
      let post: Post
      let audioTitle: String
      let playCount: Int
   }

   struct ActivityEntry: Sendable, Hashable {
      enum Kind: Sendable, Hashable {
         case likedPost
         case likedComment(String)
         case commented(String)
         case mentioned(String)
         case followed
      }

      let id: String
      let kind: Kind
      let users: [UserSummary]
      let occurredAt: Date
      let mediaCode: String?
   }

   struct ProfileActivity: Sendable, Hashable {
      let recentFollowers: [UserSummary]
      let activeFollowerCount: Int
   }
}
