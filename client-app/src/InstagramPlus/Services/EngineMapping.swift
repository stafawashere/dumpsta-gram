import Foundation

extension Account {
   init(_ author: Engine.PostAuthor) {
      self.init(id: author.id, username: author.username, displayName: Self.displayName(author.fullName, author.username), location: nil, isVerified: author.isVerified, profilePicURL: author.profilePicURL)
   }

   init(_ author: Engine.CommentAuthor) {
      self.init(id: author.id, username: author.username, displayName: author.username, location: nil, isVerified: author.isVerified, profilePicURL: author.profilePicURL)
   }

   init(_ participant: Engine.ThreadParticipant) {
      self.init(id: participant.userID, username: participant.username, displayName: Self.displayName(participant.fullName, participant.username), location: nil, isVerified: participant.isVerified)
   }

   init(_ summary: Engine.UserSummary) {
      self.init(id: summary.id, username: summary.username, displayName: Self.displayName(summary.fullName, summary.username), location: nil, isVerified: summary.isVerified, profilePicURL: summary.profilePicURL)
   }

   init(_ profile: Engine.Profile) {
      self.init(id: profile.id, username: profile.username, displayName: Self.displayName(profile.fullName, profile.username), location: nil, isVerified: profile.isVerified, profilePicURL: profile.profilePicURL)
   }

   private static func displayName(_ fullName: String, _ username: String) -> String {
      fullName.isEmpty ? username : fullName
   }
}

// The one place the upstream's media_type numbers are read. The engine passes them through as
// sent (1, 2 and 8 measured) and has no typed media kind on its public surface, so reading them
// here is Instagram knowledge in Swift until the engine exposes one on every model that carries
// media_type.
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

extension Post.Rendition {
   init(_ image: Engine.MediaImage) {
      self.init(url: image.url, width: image.width, height: image.height)
   }

   init(_ video: Engine.VideoRendition) {
      self.init(url: video.url, width: video.width, height: video.height, versionType: video.versionType)
   }
}

extension Post {
   init(_ post: Engine.Post) {
      let imageURL = post.images.first.flatMap { URL(string: $0.url) }
      let localImageURL = imageURL?.isFileURL == true ? imageURL : nil

      let pages = post.carouselChildren.map { child in
         Post.CarouselPage(
            id: child.id,
            kind: Post.Kind(mediaType: child.mediaType),
            images: child.images.map(Post.Rendition.init),
            videos: child.videos.map(Post.Rendition.init)
         )
      }

      self.init(
         id: post.pk,
         code: post.code,
         author: Account(post.author),
         location: post.location.map { Post.Location(id: $0.id, name: $0.name) },
         caption: post.caption ?? "",
         mediaDescription: post.accessibilityCaption ?? "",
         postedAt: post.takenAt,
         kind: Post.Kind(mediaType: post.mediaType),
         likeCount: post.likeCount,
         commentCount: post.commentCount,
         shareCount: nil,
         saveCount: nil,
         isLiked: post.hasLiked,
         isSaved: post.hasSaved,
         mediaURL: localImageURL,
         hidesLikeCount: post.likeAndViewCountsDisabled,
         commentsDisabled: post.commentsDisabled,
         images: post.images.map(Post.Rendition.init),
         videos: post.videos.map(Post.Rendition.init),
         videoDuration: post.videoDuration,
         carouselPages: pages,
         carouselCount: post.carouselMediaCount,
         audioID: post.audioID,
         audioTitle: post.audioTitle
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
         likeCount: comment.likeCount,
         isLiked: comment.hasLiked,
         parentID: comment.parentCommentID,
         replyCount: comment.replyCount
      )
   }
}

extension ProfileTile {
   init(_ tile: Engine.GridTile) {
      self.init(id: tile.pk, code: tile.code, kind: Post.Kind(tile.kind), likeCount: tile.likeCount, commentCount: tile.commentCount, images: tile.images.map(Post.Rendition.init))
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
         followsViewer: profile.friendshipStatus?.followedBy,
         isFollowing: profile.friendshipStatus?.following,
         hasRequestedFollow: profile.friendshipStatus?.outgoingRequest,
         isBlocking: profile.friendshipStatus?.blocking,
         isMuting: profile.friendshipStatus?.muting,
         isCloseFriend: profile.friendshipStatus?.isBestie
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
   init(_ message: Engine.Message, viewerID: Account.ID) {
      // Who sent it and who reacted is the engine's answer, never worked out here.
      let senderID = message.isFromViewer == true ? viewerID : (message.sender.igid ?? message.sender.fbid)
      let imageURL = message.media.lazy.compactMap(\.stillURL).first.flatMap(URL.init(string:))
      let text = message.text ?? ""
      // A message with neither text nor a picture, a voice clip or a kind the engine names as
      // other, is named rather than drawn as an empty bubble.
      let fallbackText = imageURL == nil ? "A message Instagram+ cannot show yet" : ""

      self.init(
         id: message.id,
         senderID: senderID,
         text: text.isEmpty ? fallbackText : text,
         sentAt: message.sentAt,
         reactionCount: message.reactions.count,
         viewerReacted: message.reactions.contains { $0.isFromViewer == true },
         repliedToID: message.repliedToMessageID,
         imageURL: imageURL
      )
   }
}

extension Hashtag {
   init(_ hashtag: Engine.Hashtag) {
      self.init(name: hashtag.name, postCount: hashtag.postCount)
   }

   init(_ header: Engine.HashtagHeader) {
      self.init(name: header.name, postCount: nil)
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
   // A tray row keeps the engine's nil where it has no unseen flag or item count. The engine
   // states its unseen rule from seen_at only as an inference in a docstring, not as a property,
   // so it is not applied here.
   init(_ entry: Engine.StoryTrayEntry) {
      self.init(author: Account(entry.user), itemCount: entry.itemCount, postedAt: entry.latestAt, hasUnseenItems: entry.hasUnseen, seenAt: entry.seenAt)
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
         isSaved: reel.post.hasSaved,
         audioID: reel.audioID ?? reel.post.audioID,
         images: reel.post.images.map(Post.Rendition.init),
         videos: reel.post.videos.map(Post.Rendition.init)
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

extension Engine.GridTile.Kind {
   init(mediaType: Int) {
      switch Post.Kind(mediaType: mediaType) {
         case .photo: self = .photo
         case .carousel: self = .carousel
         case .video: self = .video
      }
   }
}

extension StoryFrames {
   init(_ reel: Engine.StoryReel) {
      let frames = reel.items.map { item in
         // MediaView loads a file or an https address and shows its placeholder for anything else.
         let imageURL = item.images.first.flatMap { URL(string: $0.url) }

         return StoryFrames.Frame(id: item.id, postedAt: item.takenAt, isVideo: Post.Kind(mediaType: item.mediaType) == .video, mediaURL: imageURL)
      }

      self.init(reelID: reel.id, title: reel.title, frames: frames)
   }
}

extension UntypedActivity {
   init(_ entry: Engine.UntypedActivityEntry) {
      let actor = entry.accountID.flatMap { accountID in
         entry.accountUsername.map { Account(id: accountID, username: $0, displayName: $0, location: nil) }
      }

      self.init(id: entry.id, rawKind: entry.rawKind, text: entry.text, actor: actor, occurredAt: entry.occurredAt, mediaCode: entry.mediaCode)
   }
}

extension SavedCollection {
   init(_ collection: Engine.SavedCollection) {
      let coverURL = collection.coverURLs.first.flatMap(URL.init(string:))
      self.init(id: collection.id, name: collection.name, isAllPosts: collection.kind == .allPosts, mediaCount: collection.mediaCount, coverURL: coverURL)
   }
}

extension ProfileTile {
   init(_ post: Engine.Post) {
      self.init(id: post.pk, code: post.code, kind: Post.Kind(mediaType: post.mediaType), likeCount: post.likeCount, commentCount: post.commentCount, images: post.images.map(Post.Rendition.init))
   }
}

extension AudioPageContent {
   init(_ page: Engine.AudioPage, fallbackTitle: String) {
      self.init(
         title: page.audio?.title ?? fallbackTitle,
         artist: page.audio?.artist,
         clipsCount: page.clipsCount,
         isRestricted: page.isRestricted,
         clips: page.clips.map(ProfileTile.init)
      )
   }
}

extension TopSearchRow {
   init?(_ result: Engine.SearchResult) {
      if let summary = result.account {
         self.init(id: "account." + summary.id, content: .account(Account(summary)))
      } else if let keyword = result.keyword {
         self.init(id: "keyword." + keyword, content: .keyword(keyword))
      } else {
         return nil
      }
   }
}

extension Engine.MessageMedia {
   // The address a still picture can be drawn from: the picture itself, or a video's preview.
   // A voice clip has none.
   var stillURL: String? {
      switch kind {
         case .image, .sticker, .sharePreview, .animatedImage:
            url

         case .video:
            previewURL

         case .audio:
            nil
      }
   }
}
