import Foundation

// The in-memory account state DummyEngine reads and writes. It stands in for Instagram's side
// of the conversation, so every write here is visible to the next read, the way it would be
// upstream.
struct DummyWorld: Sendable {
   struct User: Sendable {
      let id: String
      let username: String
      let fullName: String
      let biography: String
      let category: String?
      let externalURL: String?
      let isVerified: Bool
      let isPrivate: Bool
      var followerCount: Int
      var followingCount: Int
      let clipsCount: Int

      var fbid: String { "fb." + id }
   }

   struct PostRecord: Sendable {
      let pk: String
      let code: String
      let authorID: String
      let caption: String
      let takenAt: Date
      let location: String?
      let accessibilityCaption: String?
      let kind: Engine.GridTile.Kind
      let imageURL: String
      var likeCount: Int
      var hasLiked: Bool
      var hasSaved: Bool
      var hidesCounts: Bool
      var commentsDisabled: Bool
      var isReel: Bool
      var audioTitle: String?
   }

   struct ThreadRecord: Sendable {
      let fbid: String
      let participantIDs: [String]
      let name: String?
      var isMuted: Bool
      var isPinned: Bool
      var isUnread: Bool
      var isRequest = false
   }

   struct StoryRecord: Sendable {
      let userID: String
      let itemCount: Int
      let latestAt: Date
      var isSeen: Bool
   }

   struct PendingReply: Sendable {
      let dueAt: Date
      let threadFBID: String
      let senderID: String
      let text: String
   }

   let viewerID: String
   var users: [String: User]
   var followingIDs: Set<String>
   var followerIDs: Set<String>
   var outgoingRequestIDs: Set<String>
   var incomingRequestIDs: [String]
   var posts: [String: PostRecord]
   var feedOrder: [String]
   var comments: [String: [Engine.Comment]]
   var threads: [String: ThreadRecord]
   var messages: [String: [Engine.Message]]
   var notes: [Engine.Note]
   var stories: [StoryRecord]
   var activity: [Engine.ActivityEntry]
   var highlights: [String: [Engine.Highlight]]
   var suggestedIDs: [String]
   var pendingReplies: [PendingReply]
   var nextSerial: Int
   var closeFriendIDs: Set<String> = []
   var blockedIDs: Set<String> = []
   var mutedIDs: Set<String> = []
   var hiddenPostPKs: Set<String> = []
   var archivedStoryCount = 0

   mutating func makeID(_ prefix: String) -> String {
      nextSerial += 1
      return "\(prefix)\(nextSerial)"
   }

   func user(_ id: String) -> User? {
      users[id]
   }

   func userID(forFBID fbid: String) -> String? {
      users.values.first { $0.fbid == fbid }?.id
   }

   func summary(_ id: String) -> Engine.UserSummary? {
      guard let user = users[id] else {
         return nil
      }

      return Engine.UserSummary(id: user.id, username: user.username, fullName: user.fullName, isVerified: user.isVerified, isPrivate: user.isPrivate)
   }

   func author(_ id: String) -> Engine.PostAuthor? {
      guard let user = users[id] else {
         return nil
      }

      return Engine.PostAuthor(
         id: user.id,
         username: user.username,
         fullName: user.fullName,
         profilePicURL: "dummy://avatar/" + user.id,
         isPrivate: user.isPrivate,
         isVerified: user.isVerified,
         isFollowing: followingIDs.contains(user.id)
      )
   }

   func enginePost(_ pk: String) -> Engine.Post? {
      guard let record = posts[pk], let author = author(record.authorID) else {
         return nil
      }

      let isCarousel = record.kind == .carousel
      let mediaType = record.kind == .video ? 2 : (isCarousel ? 8 : 1)

      return Engine.Post(
         id: record.pk + "_" + record.authorID,
         pk: record.pk,
         code: record.code,
         author: author,
         caption: record.caption.isEmpty ? nil : record.caption,
         takenAt: record.takenAt,
         likeCount: record.likeCount,
         commentCount: comments[pk]?.count ?? 0,
         hasLiked: record.hasLiked,
         isSeen: false,
         mediaType: mediaType,
         images: [Engine.MediaImage(url: record.imageURL, width: 1080, height: 1080)],
         carouselMediaCount: isCarousel ? 3 : nil,
         accessibilityCaption: record.accessibilityCaption,
         likeAndViewCountsDisabled: record.hidesCounts,
         location: record.location,
         hasSaved: record.hasSaved,
         commentsDisabled: record.commentsDisabled
      )
   }

   func tile(_ pk: String) -> Engine.GridTile? {
      guard let record = posts[pk] else {
         return nil
      }

      return Engine.GridTile(pk: record.pk, code: record.code, kind: record.kind, likeCount: record.likeCount, commentCount: comments[pk]?.count ?? 0)
   }

   func postPK(forCode code: String) -> String? {
      posts.values.first { $0.code == code }?.pk
   }

   func profile(_ id: String) -> Engine.Profile? {
      guard let user = users[id] else {
         return nil
      }

      let isViewer = id == viewerID
      let status: Engine.FriendshipStatus? = isViewer ? nil : Engine.FriendshipStatus(
         following: followingIDs.contains(id),
         followedBy: followerIDs.contains(id),
         outgoingRequest: outgoingRequestIDs.contains(id),
         incomingRequest: incomingRequestIDs.contains(id),
         blocking: blockedIDs.contains(id),
         muting: mutedIDs.contains(id),
         isBestie: closeFriendIDs.contains(id),
         isRestricted: false
      )

      let postCount = posts.values.filter { $0.authorID == id && !$0.isReel }.count

      return Engine.Profile(
         id: user.id,
         username: user.username,
         fullName: user.fullName,
         biography: user.biography,
         category: user.category,
         externalURL: user.externalURL,
         followerCount: user.followerCount,
         followingCount: user.followingCount,
         mediaCount: postCount,
         totalClipsCount: user.clipsCount,
         isPrivate: user.isPrivate,
         isVerified: user.isVerified,
         profilePicURL: "dummy://avatar/" + user.id,
         friendshipStatus: status
      )
   }

   func isHiddenFromViewer(_ userID: String) -> Bool {
      blockedIDs.contains(userID) || mutedIDs.contains(userID)
   }

   func hashtags(in caption: String) -> [String] {
      caption
         .split(whereSeparator: { $0 == " " || $0 == "\n" })
         .filter { $0.hasPrefix("#") && $0.count > 1 }
         .map { $0.dropFirst().lowercased().trimmingCharacters(in: .punctuationCharacters) }
   }

   func placeID(for location: String) -> String {
      location.lowercased().filter { $0.isLetter || $0.isNumber }
   }

   mutating func setCommentLiked(_ liked: Bool, postPK: String, commentID: String) -> Bool {
      guard let index = comments[postPK]?.firstIndex(where: { $0.id == commentID }) else {
         return false
      }

      let original = comments[postPK]![index]
      let wasLiked = original.hasLiked ?? false
      let delta = (liked ? 1 : 0) - (wasLiked ? 1 : 0)

      comments[postPK]![index] = Engine.Comment(
         id: original.id,
         author: original.author,
         text: original.text,
         createdAt: original.createdAt,
         likeCount: (original.likeCount ?? 0) + delta,
         hasLiked: liked,
         parentCommentID: original.parentCommentID,
         replyCount: original.replyCount
      )

      return true
   }

   mutating func setReaction(_ emoji: String?, threadFBID: String, messageID: String) -> Bool {
      guard let index = messages[threadFBID]?.firstIndex(where: { $0.id == messageID }) else {
         return false
      }

      let viewerFBID = users[viewerID]?.fbid ?? viewerID
      var message = messages[threadFBID]![index]
      var reactions = message.reactions.filter { $0.senderFBID != viewerFBID }

      if let emoji {
         reactions.append(Engine.Reaction(emoji: emoji, senderFBID: viewerFBID))
      }

      message = Engine.Message(
         id: message.id,
         threadFBID: message.threadFBID,
         sender: message.sender,
         text: message.text,
         sentAt: message.sentAt,
         contentType: message.contentType,
         reactions: reactions,
         repliedToMessageID: message.repliedToMessageID,
         offlineThreadingID: message.offlineThreadingID,
         mediaURL: message.mediaURL
      )
      messages[threadFBID]![index] = message
      return true
   }

   func canSeePosts(of userID: String) -> Bool {
      guard let user = users[userID] else {
         return false
      }

      let isViewer = userID == viewerID
      let isFollowing = followingIDs.contains(userID)
      return !user.isPrivate || isViewer || isFollowing
   }

   func engineThread(_ fbid: String) -> Engine.DirectThread? {
      guard let thread = threads[fbid] else {
         return nil
      }

      let participants = thread.participantIDs.compactMap { id -> Engine.ThreadParticipant? in
         guard let user = users[id] else {
            return nil
         }

         return Engine.ThreadParticipant(userID: user.id, username: user.username, fullName: user.fullName, isVerified: user.isVerified)
      }

      let lastMessage = messages[fbid]?.last
      let title = thread.name ?? participants.map(\.fullName).joined(separator: ", ")

      return Engine.DirectThread(
         threadFBID: fbid,
         title: title,
         participants: participants,
         isGroup: participants.count > 1,
         isUnread: thread.isUnread,
         isMarkedUnread: false,
         isMuted: thread.isMuted,
         isPinned: thread.isPinned,
         lastActivityAt: lastMessage?.sentAt ?? .distantPast,
         lastMessageID: lastMessage?.id,
         snippet: lastMessage?.text
      )
   }

   mutating func appendMessage(threadFBID: String, senderID: String, text: String?, offlineThreadingID: String?, replyingTo: String? = nil, mediaURL: String? = nil) -> Engine.Message {
      let sender = users[senderID]
      let message = Engine.Message(
         id: makeID("mid."),
         threadFBID: threadFBID,
         sender: Engine.MessageSender(fbid: sender?.fbid ?? senderID, igid: senderID, name: sender?.fullName),
         text: text,
         sentAt: .now,
         contentType: mediaURL == nil ? "text" : "media",
         reactions: [],
         repliedToMessageID: replyingTo,
         offlineThreadingID: offlineThreadingID,
         mediaURL: mediaURL
      )

      messages[threadFBID, default: []].append(message)

      let isFromOther = senderID != viewerID
      if isFromOther {
         threads[threadFBID]?.isUnread = true
      }

      return message
   }
}
