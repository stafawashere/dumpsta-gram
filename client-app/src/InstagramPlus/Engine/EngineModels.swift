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
      case exploreStory = "explore_story"
      case bloksUnit = "bloks_netego"
      case icebreakers = "abra_icebreakers_in_feed_unit"
      case adForAd = "ad4ad_in_webfeed"
   }

   struct FeedItem: Sendable {
      let kind: FeedItemKind
      let post: Post?
   }

   struct VideoRendition: Sendable, Hashable {
      let url: String
      let width: Int
      let height: Int
      let versionType: Int
   }

   // Location.id is what feeds.location takes. The engine's lat and lng are not carried, since no
   // page shows them.
   struct Location: Sendable, Hashable {
      let id: String
      let name: String
   }

   // mediaType is the upstream's number as the engine passes it through. See Post.Kind.
   struct CarouselChild: Sendable, Hashable {
      let id: String
      let pk: String
      let mediaType: Int
      let images: [MediaImage]
      let videos: [VideoRendition]
      let videoDuration: Double?
   }

   // One Post or one PostDetail. PostDetail carries no is_seen, so isSeen is nil when the post
   // was read by its code.
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
      let isSeen: Bool?
      let mediaType: Int
      let images: [MediaImage]
      let carouselMediaCount: Int?
      let accessibilityCaption: String?
      let likeAndViewCountsDisabled: Bool
      let location: Location?

      // Not on the engine's Post or PostDetail. Nil from the real engine, and never guessed.
      let hasSaved: Bool?
      let commentsDisabled: Bool?

      var videos: [VideoRendition] = []
      var videoDuration: Double? = nil
      var carouselChildren: [CarouselChild] = []

      // MediaAudio.audio_id and its title, which feeds.audio and feeds.audio_clips take. Nil
      // where the post carries no audio model.
      var audioID: String? = nil
      var audioTitle: String? = nil
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
      var senderIGID: String? = nil
      // The engine's answer to "did the viewer react", nil when the read could not tell.
      var isFromViewer: Bool? = nil

      static let heart = "\u{2764}\u{FE0F}"
   }

   struct Message: Sendable, Hashable {
      let id: String
      let threadFBID: String
      let sender: MessageSender
      let text: String?
      let sentAt: Date
      let contentType: String
      var reactions: [Reaction]
      let repliedToMessageID: String?
      let offlineThreadingID: String?
      // The engine's answer to "did the viewer send this", nil when the read could not tell.
      var isFromViewer: Bool? = nil
      // The engine's MessageKind value, the upstream content type name, or "other".
      var kind: String = "other"
      var media: [MessageMedia] = []
   }

   struct MessageMedia: Sendable, Hashable {
      enum Kind: String, Sendable {
         case image
         case video
         case audio
         case animatedImage = "animated_image"
         case sticker
         case sharePreview = "share_preview"
      }

      let kind: Kind
      let url: String
      var previewURL: String? = nil
      var width: Int? = nil
      var height: Int? = nil
      var durationMS: Int? = nil
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
      case internalOnly = 2
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
      var profilePicURL: String? = nil
   }

   // The engine's TrayReel carries neither an item count nor an unseen flag, so both are nil on
   // the real engine rather than guessed from its dates. seenAt is TrayReel.seen_at as it came.
   struct StoryTrayEntry: Sendable, Hashable {
      let user: UserSummary
      let itemCount: Int?
      let latestAt: Date
      let hasUnseen: Bool?
      var seenAt: Date? = nil
   }

   struct Highlight: Sendable, Hashable {
      let id: String
      let title: String
      let itemCount: Int?
   }

   struct StoryItem: Sendable, Hashable {
      let id: String
      let pk: String
      let ownerID: String
      let mediaType: Int
      let takenAt: Date
      let expiringAt: Date
      let images: [MediaImage]
      let videoDuration: Double?
      let canReply: Bool
   }

   // One live reel or one highlight, every item in it, as stories.reel and stories.highlight
   // return it.
   struct StoryReel: Sendable, Hashable {
      let id: String
      let ownerID: String
      let ownerUsername: String
      let title: String?
      let latestItemAt: Date
      let items: [StoryItem]
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

      // Nil where the engine model has no comment count, as on SavedPost.
      let commentCount: Int?

      // The renditions the engine gave for the tile, as they came. Empty where it gave none.
      var images: [MediaImage] = []
   }

   struct Reel: Sendable, Hashable {
      let post: Post
      let audioTitle: String
      let playCount: Int

      // False on the real engine, whose reels feed carries no play count.
      var isPlayCountKnown = true
      var audioID: String? = nil
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

   struct Hashtag: Sendable, Hashable {
      let name: String
      let postCount: Int
   }

   struct Place: Sendable, Hashable {
      let id: String
      let name: String
      let postCount: Int
   }

   // What search.recent answers. The engine carries a payload only for account and keyword
   // entries. A hashtag or a place entry arrives as its kind alone.
   struct RecentSearch: Sendable, Hashable {
      enum Kind: String, Sendable {
         case account = "user"
         case keyword = "keyword"
         case hashtag = "hashtag"
         case place = "place"
      }

      let kind: Kind
      let account: UserSummary?
      let keyword: String?
   }

   // One activity row whose kind the engine gives only as the upstream's own string. The app
   // shows the engine's line and kind as they came, because mapping them onto
   // ActivityEntry.Kind would put Instagram knowledge in Swift.
   struct UntypedActivityEntry: Sendable, Hashable {
      let id: String
      let rawKind: String
      let text: String
      let accountID: String?
      let accountUsername: String?
      let occurredAt: Date
      let mediaCode: String?
   }

   // The activity feed as one read of it answers. hasUnseen is nil where nothing says whether
   // the viewer has seen it.
   struct ActivityFeed: Sendable, Hashable {
      let entries: [ActivityEntry]
      let untyped: [UntypedActivityEntry]
      let hasUnseen: Bool?
   }

   struct Relationships: Sendable, Hashable {
      let closeFriendIDs: [String]
      let blockedIDs: [String]
      let mutedIDs: [String]
      var closeFriends: [UserSummary] = []
      var blocked: [UserSummary] = []

      // The engine has no muted accounts read, so mutedIDs is empty on it for want of a source.
      var isMutedListKnown = true
   }

   // Added after 1.1.0, the engine capabilities no page used before.

   // media.page, the post, its first comments page and the author's grid in one read.
   struct PostPage: Sendable {
      let post: Post
      let comments: Page<Comment>
      let authorGrid: [GridTile]
   }

   // profiles.mutual_followers answers its first page only, with whether more exist.
   struct MutualFollowers: Sendable, Hashable {
      let accounts: [UserSummary]
      let hasMore: Bool
   }

   struct SavedCollection: Sendable, Hashable {
      enum Kind: String, Sendable {
         case allPosts = "IGAllMediaAutoCollection"
         case audio = "XDTAudioAutoCollection"
         case other = "other"
      }

      let id: String
      let name: String
      let kind: Kind
      let mediaCount: Int?
      let coverURLs: [String]
   }

   struct SavedCollections: Sendable, Hashable {
      let collections: [SavedCollection]
      let hasMore: Bool
   }

   struct MediaAudio: Sendable, Hashable {
      let audioID: String
      let title: String
      let artist: String
      let isExplicit: Bool
   }

   // feeds.audio. The audio is nil where the engine read none, and the cursor goes back to
   // feeds.audio_clips exactly as it came.
   struct AudioPage: Sendable {
      let audio: MediaAudio?
      let clips: [Post]
      let clipsCount: Int
      let isRestricted: Bool
      let hasNextPage: Bool
      let endCursor: String?
   }

   // One row of search.top. Hashtag and place rows carry no payload in the engine.
   struct SearchResult: Sendable, Hashable {
      enum Kind: String, Sendable {
         case account = "user"
         case keyword = "keyword"
         case hashtag = "hashtag"
         case place = "place"
      }

      let kind: Kind
      let account: UserSummary?
      let keyword: String?
      let position: Int?
   }

   // search.keyword answers its first page only, with whether more exist.
   struct KeywordResults: Sendable, Hashable {
      let posts: [GridTile]
      let hasMore: Bool
   }

   // search.hashtag, the header of an exact tag. The engine gives no post count.
   struct HashtagHeader: Sendable, Hashable {
      let id: String
      let name: String
   }
}