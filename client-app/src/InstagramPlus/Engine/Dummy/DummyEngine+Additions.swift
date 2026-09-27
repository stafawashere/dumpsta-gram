import AppKit
import Foundation

extension DummyEngine {
   // MARK: Real surface additions

   func publishCarousel(imageURLs: [URL], caption: String) async throws(EngineError) -> EngineResult<Engine.PublishedPost> {
      try await perform("publish_carousel", kind: .write) { () throws(EngineError) -> Engine.PublishedPost in
         guard let firstURL = imageURLs.first, imageURLs.count >= 2 else {
            throw .upstreamRejected(code: "carousel_needs_two_images")
         }

         return insertOwnPost(imageURL: firstURL, caption: caption, kind: .carousel)
      }
   }

   func insertOwnPost(imageURL: URL, caption: String, kind: Engine.GridTile.Kind) -> Engine.PublishedPost {
      let pk = world.makeID("local.")
      let code = "C" + String(pk.hashValueStable, radix: 36)

      world.posts[pk] = DummyWorld.PostRecord(
         pk: pk,
         code: code,
         authorID: viewerID,
         caption: caption,
         takenAt: .now,
         location: nil,
         accessibilityCaption: imageURL.lastPathComponent,
         kind: kind,
         imageURL: imageURL.absoluteString,
         likeCount: 0,
         hasLiked: false,
         hasSaved: false,
         hidesCounts: false,
         commentsDisabled: false,
         isReel: false,
         audioTitle: nil
      )
      world.feedOrder.insert(pk, at: 0)

      return Engine.PublishedPost(id: pk + "_" + viewerID, pk: pk, code: code, takenAt: .now)
   }

   // The engine downloads a rendition's URL to disk. The dummy's remote media has no bytes, so it
   // renders a placeholder image of the rendition's size instead, and copies a local image as is.
   func download(image: Engine.MediaImage, to destination: URL) async throws(EngineError) -> EngineResult<URL> {
      try await perform("media.download", kind: .read) { () throws(EngineError) -> URL in
         do {
            if FileManager.default.fileExists(atPath: destination.path) {
               try FileManager.default.removeItem(at: destination)
            }

            if let source = URL(string: image.url), source.isFileURL {
               try FileManager.default.copyItem(at: source, to: destination)
            } else {
               try Self.placeholderPNG(seed: image.url, width: image.width, height: image.height).write(to: destination)
            }
         } catch {
            throw .transportFailure
         }

         return destination
      }
   }

   private static func placeholderPNG(seed: String, width: Int, height: Int) throws -> Data {
      let hue = Double(seed.hashValueStable % 360) / 360
      let top = NSColor(hue: hue, saturation: 0.45, brightness: 0.85, alpha: 1).cgColor
      let bottom = NSColor(hue: hue, saturation: 0.6, brightness: 0.45, alpha: 1).cgColor
      let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!

      guard
         let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: 0, space: colorSpace, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue),
         let gradient = CGGradient(colorsSpace: colorSpace, colors: [top, bottom] as CFArray, locations: [0, 1])
      else {
         throw CocoaError(.fileWriteUnknown)
      }

      context.drawLinearGradient(gradient, start: CGPoint(x: 0, y: height), end: CGPoint(x: width, y: 0), options: [])

      guard let image = context.makeImage() else {
         throw CocoaError(.fileWriteUnknown)
      }

      let bitmap = NSBitmapImageRep(cgImage: image)
      guard let data = bitmap.representation(using: .png, properties: [:]) else {
         throw CocoaError(.fileWriteUnknown)
      }

      return data
   }

   // MARK: Posts and comments

   func hidePost(postPK: String) async throws(EngineError) -> EngineResult<Void> {
      try await perform("hide_post (proposed)", kind: .write) { () throws(EngineError) in
         world.hiddenPostPKs.insert(postPK)
      }
   }

   func sharePost(postPK: String, threadFBIDs: [String]) async throws(EngineError) -> EngineResult<Void> {
      try await perform("share_post (proposed)", kind: .write) { () throws(EngineError) in
         guard let code = world.posts[postPK]?.code else {
            throw .notFound
         }

         for threadFBID in threadFBIDs where world.threads[threadFBID] != nil {
            _ = world.appendMessage(threadFBID: threadFBID, senderID: viewerID, text: "https://www.instagram.com/p/\(code)/", offlineThreadingID: nil)
         }
      }
   }

   func likeComment(postPK: String, commentID: String, liked: Bool) async throws(EngineError) -> EngineResult<Void> {
      try await perform(liked ? "like_comment (proposed)" : "unlike_comment (proposed)", kind: .write) { () throws(EngineError) in
         guard world.setCommentLiked(liked, postPK: postPK, commentID: commentID) else {
            throw .notFound
         }
      }
   }

   func replyToComment(postPK: String, parentCommentID: String, text: String) async throws(EngineError) -> EngineResult<Engine.Comment> {
      try await perform("reply_to_comment (proposed)", kind: .write) { () throws(EngineError) -> Engine.Comment in
         guard world.comments[postPK]?.contains(where: { $0.id == parentCommentID }) == true else {
            throw .notFound
         }

         let viewer = world.users[viewerID]!
         let reply = Engine.Comment(
            id: world.makeID("c."),
            author: Engine.CommentAuthor(id: viewer.id, username: viewer.username, isVerified: viewer.isVerified, profilePicURL: "dummy://avatar/" + viewer.id),
            text: text,
            createdAt: .now,
            likeCount: 0,
            hasLiked: false,
            parentCommentID: parentCommentID,
            replyCount: 0
         )

         world.comments[postPK, default: []].append(reply)
         return reply
      }
   }

   // MARK: Direct

   func resolveMessageRequest(threadFBID: String, accept: Bool) async throws(EngineError) -> EngineResult<Void> {
      try await perform(accept ? "accept_request (proposed)" : "delete_request (proposed)", kind: .write) { () throws(EngineError) in
         guard world.threads[threadFBID]?.isRequest == true else {
            throw .notFound
         }

         if accept {
            world.threads[threadFBID]?.isRequest = false
         } else {
            world.threads[threadFBID] = nil
            world.messages[threadFBID] = nil
         }
      }
   }

   func createThread(userIDs: [String]) async throws(EngineError) -> EngineResult<Engine.DirectThread> {
      try await perform("create_thread (proposed)", kind: .write) { () throws(EngineError) -> Engine.DirectThread in
         let participants = userIDs.filter { world.users[$0] != nil && $0 != viewerID }

         guard !participants.isEmpty else {
            throw .notFound
         }

         let existing = world.threads.values.first { record in
            let sameMembers = Set(record.participantIDs) == Set(participants)
            return sameMembers && !record.isRequest
         }

         if let existing, let thread = world.engineThread(existing.fbid) {
            return thread
         }

         let fbid = world.makeID("t.")
         world.threads[fbid] = DummyWorld.ThreadRecord(fbid: fbid, participantIDs: participants, name: nil, isMuted: false, isPinned: false, isUnread: false)
         world.messages[fbid] = []

         guard let thread = world.engineThread(fbid) else {
            throw .schemaChanged(path: "thread")
         }

         return thread
      }
   }

   func react(threadFBID: String, messageID: String, emoji: String?) async throws(EngineError) -> EngineResult<Void> {
      try await perform(emoji == nil ? "unreact (proposed)" : "react (proposed)", kind: .write) { () throws(EngineError) in
         guard world.setReaction(emoji, threadFBID: threadFBID, messageID: messageID) else {
            throw .notFound
         }
      }
   }

   func sendReply(threadFBID: String, text: String, replyingTo messageID: String) async throws(EngineError) -> EngineResult<Engine.SentMessage> {
      let result = try await perform("send_reply (proposed)", kind: .write) { () throws(EngineError) -> Engine.SentMessage in
         guard world.threads[threadFBID] != nil else {
            throw .notFound
         }

         let offlineThreadingID = String(Int.random(in: 1_000_000_000...9_999_999_999))
         let message = world.appendMessage(threadFBID: threadFBID, senderID: viewerID, text: text, offlineThreadingID: offlineThreadingID, replyingTo: messageID)
         return Engine.SentMessage(id: message.id, offlineThreadingID: offlineThreadingID, threadFBID: threadFBID, sentAt: message.sentAt)
      }

      if case .value = result {
         scheduleReply(in: threadFBID)
      }

      return result
   }

   func sendPhoto(threadFBID: String, imageURL: URL) async throws(EngineError) -> EngineResult<Engine.SentMessage> {
      try await perform("send_photo (proposed)", kind: .write) { () throws(EngineError) -> Engine.SentMessage in
         guard world.threads[threadFBID] != nil else {
            throw .notFound
         }

         let offlineThreadingID = String(Int.random(in: 1_000_000_000...9_999_999_999))
         let message = world.appendMessage(threadFBID: threadFBID, senderID: viewerID, text: nil, offlineThreadingID: offlineThreadingID, mediaURL: imageURL.absoluteString)
         return Engine.SentMessage(id: message.id, offlineThreadingID: offlineThreadingID, threadFBID: threadFBID, sentAt: message.sentAt)
      }
   }

   func setThreadMuted(threadFBID: String, muted: Bool) async throws(EngineError) -> EngineResult<Void> {
      try await perform(muted ? "mute_thread (proposed)" : "unmute_thread (proposed)", kind: .write) { () throws(EngineError) in
         guard world.threads[threadFBID] != nil else {
            throw .notFound
         }

         world.threads[threadFBID]?.isMuted = muted
      }
   }

   // MARK: Stories

   func publishStory(imageURL: URL) async throws(EngineError) -> EngineResult<Void> {
      try await perform("publish_story (proposed)", kind: .write) { () throws(EngineError) in
         if let index = world.stories.firstIndex(where: { $0.userID == viewerID }) {
            let record = world.stories.remove(at: index)
            world.stories.insert(DummyWorld.StoryRecord(userID: viewerID, itemCount: record.itemCount + 1, latestAt: .now, isSeen: false), at: 0)
         } else {
            world.stories.insert(DummyWorld.StoryRecord(userID: viewerID, itemCount: 1, latestAt: .now, isSeen: false), at: 0)
         }

         world.archivedStoryCount += 1
      }
   }

   func likeStory(userID: String) async throws(EngineError) -> EngineResult<Void> {
      try await perform("like_story (proposed)", kind: .write) { () throws(EngineError) in
         guard world.stories.contains(where: { $0.userID == userID }) else {
            throw .notFound
         }
      }
   }

   func archivedStories() async throws(EngineError) -> EngineResult<[Engine.GridTile]> {
      try await perform("archived_stories (proposed)", kind: .read) { () throws(EngineError) -> [Engine.GridTile] in
         (0..<world.archivedStoryCount).map { index in
            Engine.GridTile(pk: "archive.\(index)", code: "archive.\(index)", kind: .photo, likeCount: 0, commentCount: 0)
         }
      }
   }

   // MARK: Profile and relationships

   func editProfile(fullName: String, biography: String, externalURL: String?) async throws(EngineError) -> EngineResult<Engine.Profile> {
      try await perform("edit_profile (proposed)", kind: .write) { () throws(EngineError) -> Engine.Profile in
         guard let user = world.users[viewerID] else {
            throw .notFound
         }

         world.users[viewerID] = DummyWorld.User(
            id: user.id,
            username: user.username,
            fullName: fullName,
            biography: biography,
            category: user.category,
            externalURL: externalURL,
            isVerified: user.isVerified,
            isPrivate: user.isPrivate,
            followerCount: user.followerCount,
            followingCount: user.followingCount,
            clipsCount: user.clipsCount
         )

         guard let profile = world.profile(viewerID) else {
            throw .notFound
         }

         return profile
      }
   }

   func removeFollower(userID: String) async throws(EngineError) -> EngineResult<Void> {
      try await perform("remove_follower (proposed)", kind: .write) { () throws(EngineError) in
         let wasFollower = world.followerIDs.remove(userID) != nil

         if wasFollower {
            world.users[viewerID]?.followerCount -= 1
         }
      }
   }

   func relationships() async throws(EngineError) -> EngineResult<Engine.Relationships> {
      try await perform("relationships (proposed)", kind: .read) { () throws(EngineError) -> Engine.Relationships in
         Engine.Relationships(
            closeFriendIDs: world.closeFriendIDs.sorted(),
            blockedIDs: world.blockedIDs.sorted(),
            mutedIDs: world.mutedIDs.sorted()
         )
      }
   }

   func setCloseFriend(userID: String, included: Bool) async throws(EngineError) -> EngineResult<Void> {
      try await perform(included ? "add_close_friend (proposed)" : "remove_close_friend (proposed)", kind: .write) { () throws(EngineError) in
         if included {
            world.closeFriendIDs.insert(userID)
         } else {
            world.closeFriendIDs.remove(userID)
         }
      }
   }

   // A block also ends the follow in both directions, as it does on Instagram.
   func setBlocked(userID: String, blocked: Bool) async throws(EngineError) -> EngineResult<Void> {
      try await perform(blocked ? "block (proposed)" : "unblock (proposed)", kind: .write) { () throws(EngineError) in
         guard world.users[userID] != nil else {
            throw .notFound
         }

         guard blocked else {
            world.blockedIDs.remove(userID)
            return
         }

         world.blockedIDs.insert(userID)
         world.closeFriendIDs.remove(userID)

         if world.followingIDs.remove(userID) != nil {
            world.users[userID]?.followerCount -= 1
            world.users[viewerID]?.followingCount -= 1
         }

         if world.followerIDs.remove(userID) != nil {
            world.users[viewerID]?.followerCount -= 1
         }
      }
   }

   func setMuted(userID: String, muted: Bool) async throws(EngineError) -> EngineResult<Void> {
      try await perform(muted ? "mute (proposed)" : "unmute (proposed)", kind: .write) { () throws(EngineError) in
         if muted {
            world.mutedIDs.insert(userID)
         } else {
            world.mutedIDs.remove(userID)
         }
      }
   }

   // MARK: Tags and places

   func searchTags(query: String) async throws(EngineError) -> EngineResult<[Engine.Hashtag]> {
      try await perform("search_tags (proposed)", kind: .read) { () throws(EngineError) -> [Engine.Hashtag] in
         let needle = query.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "#"))
         var counts: [String: Int] = [:]

         for record in world.posts.values {
            for tag in world.hashtags(in: record.caption) where tag.contains(needle) {
               counts[tag, default: 0] += 1
            }
         }

         return counts
            .map { Engine.Hashtag(name: $0.key, postCount: $0.value * 1_700) }
            .sorted { $0.postCount > $1.postCount }
      }
   }

   func searchPlaces(query: String) async throws(EngineError) -> EngineResult<[Engine.Place]> {
      try await perform("search_places (proposed)", kind: .read) { () throws(EngineError) -> [Engine.Place] in
         let needle = query.lowercased()
         var counts: [String: Int] = [:]

         for record in world.posts.values {
            guard let location = record.location, location.lowercased().contains(needle) else {
               continue
            }

            counts[location, default: 0] += 1
         }

         return counts
            .map { Engine.Place(id: world.placeID(for: $0.key), name: $0.key, postCount: $0.value * 900) }
            .sorted { $0.postCount > $1.postCount }
      }
   }

   func hashtagPosts(name: String) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try await perform("hashtag_posts (proposed)", kind: .read) { () throws(EngineError) -> Engine.Page<Engine.GridTile> in
         let tag = name.lowercased()
         let tiles = world.posts.values
            .filter { world.hashtags(in: $0.caption).contains(tag) && world.canSeePosts(of: $0.authorID) && !world.isHiddenFromViewer($0.authorID) }
            .sorted { $0.likeCount > $1.likeCount }
            .compactMap { world.tile($0.pk) }

         return Engine.Page(items: tiles, hasNextPage: false, endCursor: nil)
      }
   }

   func placePosts(placeID: String) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>> {
      try await perform("place_posts (proposed)", kind: .read) { () throws(EngineError) -> Engine.Page<Engine.GridTile> in
         let tiles = world.posts.values
            .filter { record in
               let matches = record.location.map { world.placeID(for: $0) == placeID } ?? false
               return matches && world.canSeePosts(of: record.authorID) && !world.isHiddenFromViewer(record.authorID)
            }
            .sorted { $0.takenAt > $1.takenAt }
            .compactMap { world.tile($0.pk) }

         return Engine.Page(items: tiles, hasNextPage: false, endCursor: nil)
      }
   }
}
