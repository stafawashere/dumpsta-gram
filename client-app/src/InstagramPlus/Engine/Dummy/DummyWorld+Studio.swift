import Foundation

extension DummyWorld {
   // A second account for the switcher: the same people seen from a small studio account that
   // follows the primary one, so switching visibly changes feed, inbox and profile.
   static func seedStudio() -> DummyWorld {
      let primary = seed()

      var users = primary.users
      users["studio"] = User(
         id: "studio",
         username: "vera.studio",
         fullName: "Vera Cherry Studio",
         biography: "Prints and commissions. Run by @vera.cherry.",
         category: "Art studio",
         externalURL: "veracherry.photo/prints",
         isVerified: false,
         isPrivate: false,
         followerCount: 2_140,
         followingCount: 3,
         clipsCount: 0
      )

      var world = DummyWorld(
         viewerID: "studio",
         users: users,
         followingIDs: ["viewer", "ilse.brandt", "mais.designer"],
         followerIDs: ["viewer", "ilse.brandt", "anghelina"],
         outgoingRequestIDs: [],
         incomingRequestIDs: [],
         posts: primary.posts,
         feedOrder: primary.feedOrder.filter { pk in
            let author = primary.posts[pk]?.authorID
            return author == "ilse.brandt" || author == "masudur.rahman"
         },
         comments: primary.comments,
         threads: [:],
         messages: [:],
         notes: [],
         stories: [StoryRecord(userID: "viewer", itemCount: 3, latestAt: .now.addingTimeInterval(-3_600), isSeen: false)],
         activity: [],
         highlights: [:],
         suggestedIDs: ["shea.lewis", "perdana", "stubka"],
         pendingReplies: [],
         nextSerial: 5_000
      )

      for index in 0..<6 {
         let pk = "g.studio.\(index)"
         world.posts[pk] = PostRecord(
            pk: pk,
            code: "C" + String(pk.hashValueStable, radix: 36),
            authorID: "studio",
            caption: "Print \(index + 1) of the harbour series. #prints #film",
            takenAt: .now.addingTimeInterval(Double(-86_400 * (index + 1))),
            location: "Bremen, Germany",
            accessibilityCaption: nil,
            kind: index % 3 == 1 ? .carousel : .photo,
            imageURL: "dummy://media/" + pk,
            likeCount: 40 + index * 13,
            hasLiked: false,
            hasSaved: false,
            hidesCounts: false,
            commentsDisabled: false,
            isReel: false,
            audioTitle: nil
         )
      }

      world.threads["t.studio.vera"] = ThreadRecord(fbid: "t.studio.vera", participantIDs: ["viewer"], name: nil, isMuted: false, isPinned: true, isUnread: true)
      world.messages["t.studio.vera"] = [
         world.appendMessageRecord(threadFBID: "t.studio.vera", senderID: "viewer", text: "Can you post the harbour prints today?", minutesAgo: 30),
      ]

      return world
   }

   func appendMessageRecord(threadFBID: String, senderID: String, text: String, minutesAgo: Double) -> Engine.Message {
      let sender = users[senderID]

      return Engine.Message(
         id: "mid.\(threadFBID).\(Int(minutesAgo))",
         threadFBID: threadFBID,
         sender: Engine.MessageSender(fbid: sender?.fbid ?? senderID, igid: senderID, name: sender?.fullName),
         text: text,
         sentAt: .now.addingTimeInterval(-minutesAgo * 60),
         contentType: "text",
         reactions: [],
         repliedToMessageID: nil,
         offlineThreadingID: nil
      )
   }
}
