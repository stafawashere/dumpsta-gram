import Foundation

extension Account {
   init(_ author: Engine.PostAuthor) {
      self.init(id: author.id, username: author.username, displayName: Self.displayName(author.fullName, author.username), location: nil, isVerified: author.isVerified)
   }

   init(_ author: Engine.CommentAuthor) {
      self.init(id: author.id, username: author.username, displayName: author.username, location: nil, isVerified: author.isVerified)
   }

   init(_ participant: Engine.ThreadParticipant) {
      self.init(id: participant.userID, username: participant.username, displayName: Self.displayName(participant.fullName, participant.username), location: nil, isVerified: participant.isVerified)
   }

   init(_ summary: Engine.UserSummary) {
      self.init(id: summary.id, username: summary.username, displayName: Self.displayName(summary.fullName, summary.username), location: nil, isVerified: summary.isVerified)
   }

   init(_ profile: Engine.Profile) {
      self.init(id: profile.id, username: profile.username, displayName: Self.displayName(profile.fullName, profile.username), location: nil, isVerified: profile.isVerified)
   }

   private static func displayName(_ fullName: String, _ username: String) -> String {
      fullName.isEmpty ? username : fullName
   }
}

extension Post.Kind {
   init(mediaType: Int) {
      switch mediaType {
         case 2: self = .video
         case 8: self = .carousel
         default: self = .photo
      }
   }

   init(_ kind: Engine.GridTile.Kind) {
      switch kind {
         case .photo: self = .photo
         case .carousel: self = .carousel
         case .video: self = .video
      }
   }
}

extension Post {
   init(_ post: Engine.Post) {
      let imageURL = post.images.first.flatMap { URL(string: $0.url) }
      let localImageURL = imageURL?.isFileURL == true ? imageURL : nil

      self.init(
         id: post.pk,
         code: post.code,
         author: Account(post.author),
         location: post.location,
         caption: post.caption ?? "",
         mediaDescription: post.accessibilityCaption ?? "",
         postedAt: post.takenAt,
         kind: Post.Kind(mediaType: post.mediaType),
         likeCount: post.likeCount,
         commentCount: post.commentCount,
         shareCount: nil,
         saveCount: nil,
         isLiked: post.hasLiked,
         isSaved: post.hasSaved ?? false,
         mediaURL: localImageURL,
         hidesLikeCount: post.likeAndViewCountsDisabled,
         commentsDisabled: post.commentsDisabled ?? false,
         imageURL: post.images.first?.url,
         carouselCount: post.carouselMediaCount
      )
   }
}

extension PostComment {
   init(_ comment: Engine.Comment) {
      self.init(
         id: comment.id,
         author: Account(comment.author),
         text: comment.text,
         postedAt: comment.createdAt,
         likeCount: comment.likeCount ?? 0,
         isLiked: comment.hasLiked ?? false,
         parentID: comment.parentCommentID
      )
   }
}

extension ProfileTile {
   init(_ tile: Engine.GridTile) {
      self.init(id: tile.pk, code: tile.code, kind: Post.Kind(tile.kind), likeCount: tile.likeCount, commentCount: tile.commentCount)
   }
}

extension ProfileDetails {
   init(_ profile: Engine.Profile) {
      self.init(
         account: Account(profile),
         stats: AccountStats(postCount: profile.mediaCount, followerCount: profile.followerCount, followingCount: profile.followingCount),
         category: profile.category,
         bio: profile.biography,
         website: profile.externalURL,
         isPrivate: profile.isPrivate,
         followsViewer: profile.friendshipStatus?.followedBy ?? false,
         isFollowing: profile.friendshipStatus?.following ?? false,
         hasRequestedFollow: profile.friendshipStatus?.outgoingRequest ?? false,
         isBlocking: profile.friendshipStatus?.blocking ?? false,
         isMuting: profile.friendshipStatus?.muting ?? false,
         isCloseFriend: profile.friendshipStatus?.isBestie ?? false
      )
   }
}

extension DirectThread {
   init(_ thread: Engine.DirectThread, viewerID: String) {
      self.init(
         id: thread.threadFBID,
         participants: thread.participants.map(Account.init),
         title: thread.title,
         isGroup: thread.isGroup,
         isUnread: thread.isUnread,
         isMuted: thread.isMuted,
         lastActivity: thread.lastActivityAt,
         snippet: thread.snippet,
         lastSenderIsViewer: false
      )
   }
}

extension DirectMessage {
   init(_ message: Engine.Message, viewerFBID: String?) {
      let senderID = message.sender.igid ?? message.sender.fbid
      let imageURL = message.mediaURL.flatMap(URL.init(string:))
      let fallbackText = imageURL == nil ? "Unsupported message" : ""

      self.init(
         id: message.id,
         senderID: senderID,
         text: message.text ?? fallbackText,
         sentAt: message.sentAt,
         reactionCount: message.reactions.count,
         viewerReacted: message.reactions.contains { $0.senderFBID == viewerFBID },
         repliedToID: message.repliedToMessageID,
         imageURL: imageURL
      )
   }
}

extension Hashtag {
   init(_ hashtag: Engine.Hashtag) {
      self.init(name: hashtag.name, postCount: hashtag.postCount)
   }
}

extension Place {
   init(_ place: Engine.Place) {
      self.init(id: place.id, name: place.name, postCount: place.postCount)
   }
}

extension Note {
   init(_ note: Engine.Note, author: Account) {
      self.init(id: note.id, author: author, text: note.text, isCloseFriends: note.audience == .closeFriends, postedAt: note.createdAt)
   }
}

extension Story {
   init(_ entry: Engine.StoryTrayEntry) {
      self.init(author: Account(entry.user), itemCount: entry.itemCount, postedAt: entry.latestAt, hasUnseenItems: entry.hasUnseen)
   }
}

extension Reel {
   init(_ reel: Engine.Reel) {
      self.init(
         id: reel.post.pk,
         code: reel.post.code,
         author: Account(reel.post.author),
         caption: reel.post.caption ?? "",
         audioTitle: reel.audioTitle,
         likeCount: reel.post.likeCount,
         commentCount: reel.post.commentCount,
         shareCount: nil,
         isLiked: reel.post.hasLiked,
         isSaved: reel.post.hasSaved ?? false
      )
   }
}

extension ActivityItem {
   init(_ entry: Engine.ActivityEntry) {
      let kind: ActivityItem.Kind = switch entry.kind {
         case .likedPost: .likedPost
         case .likedComment(let text): .likedComment(text)
         case .commented(let text): .commented(text)
         case .mentioned(let text): .mentioned(text)
         case .followed: .followed
      }

      self.init(id: entry.id, kind: kind, actors: entry.users.map(Account.init), occurredAt: entry.occurredAt, mediaCode: entry.mediaCode)
   }
}
