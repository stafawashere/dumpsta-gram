import Foundation

extension DummyWorld {
   static let cannedReplies = [
      "Ha, yes",
      "Wait really?",
      "Send me the photo",
      "On my way",
      "That is so good",
      "Let me check and get back to you",
      "Tomorrow works",
   ]

   static func seed() -> DummyWorld {
      func ago(_ minutes: Double) -> Date {
         Date.now.addingTimeInterval(-minutes * 60)
      }

      func user(_ id: String, _ username: String, _ fullName: String, bio: String = "", category: String? = nil, url: String? = nil, verified: Bool = false, isPrivate: Bool = false, followers: Int, following: Int, clips: Int = 0) -> User {
         User(id: id, username: username, fullName: fullName, biography: bio, category: category, externalURL: url, isVerified: verified, isPrivate: isPrivate, followerCount: followers, followingCount: following, clipsCount: clips)
      }

      let people = [
         user("viewer", "vera.cherry", "Vera Cherry", bio: "Slow travel, film grain and harbour towns.\nBased in Bremen, usually somewhere else.", category: "Photographer", url: "veracherry.photo", followers: 37_200, following: 989, clips: 6),
         user("perdana", "perdana", "Perdana", bio: "Coffee roaster. Jakarta.", followers: 4_100, following: 380, clips: 12),
         user("ben.schade", "ben.schade", "Ben Schade", bio: "Ferries, fog and 35mm.", followers: 2_340, following: 401),
         user("stubka", "stubka", "Stubka", bio: "Prague.", followers: 980, following: 512),
         user("shea.lewis", "shea.lewis", "Shea Lewis", bio: "Writing my way along the Atlantic coast.", category: "Travel writer", verified: true, followers: 128_000, following: 612, clips: 40),
         user("sumesh", "sumesh.k", "Sumesh", bio: "Kochi.", followers: 1_450, following: 700),
         user("noor.aziz", "noor.aziz", "Noor Aziz", bio: "Amman to anywhere.", followers: 3_020, following: 820),
         user("masudur.rahman", "travelsfever", "Masudur Rahman", bio: "Tag #travelsfever to be featured.\nNew picks every day.", category: "Travel community", verified: true, followers: 890_000, following: 210, clips: 120),
         user("ilse.brandt", "ilse.brandt", "Ilse Brandt", bio: "Zines and prints, Vienna.", followers: 5_600, following: 430),
         user("tomas.vidal", "tomas.vidal", "Tomas Vidal", bio: "Valencia by bike, every Saturday.", category: "Tour guide", followers: 6_800, following: 530),
         user("webuistylist", "webuistylist", "Webuistylist", followers: 12_000, following: 90),
         user("anghelina", "anghelina", "Anghelina", bio: "Sibiu.", followers: 2_200, following: 640),
         user("mais.designer", "mais.designer", "Mais Designer", bio: "Kerning is a feeling.", category: "Designer", followers: 18_400, following: 300, clips: 22),
         user("lina.park", "lina.park", "Lina Park", bio: "Seoul. Coffee first.", isPrivate: true, followers: 1_020, following: 388),
         user("josh.esport", "josh.esport", "Josh eSport", bio: "Desk setups and cable crimes.", category: "Gaming creator", followers: 240_000, following: 150, clips: 300),
      ]

      var world = DummyWorld(
         viewerID: "viewer",
         users: Dictionary(uniqueKeysWithValues: people.map { ($0.id, $0) }),
         followingIDs: ["shea.lewis", "ben.schade", "masudur.rahman", "perdana", "stubka", "sumesh", "noor.aziz", "tomas.vidal"],
         followerIDs: ["shea.lewis", "ben.schade", "lina.park", "josh.esport", "noor.aziz", "anghelina"],
         outgoingRequestIDs: [],
         incomingRequestIDs: ["webuistylist", "perdana"],
         posts: [:],
         feedOrder: [],
         comments: [:],
         threads: [:],
         messages: [:],
         notes: [],
         stories: [],
         activity: [],
         highlights: [:],
         suggestedIDs: ["webuistylist", "anghelina", "mais.designer", "lina.park", "josh.esport"],
         pendingReplies: [],
         nextSerial: 1000
      )

      func addPost(_ pk: String, by authorID: String, caption: String, minutesAgo: Double, likes: Int, location: String? = nil, alt: String? = nil, kind: Engine.GridTile.Kind = .photo, liked: Bool = false, reelAudio: String? = nil) {
         world.posts[pk] = PostRecord(
            pk: pk,
            code: "C" + String(pk.hashValueStable, radix: 36),
            authorID: authorID,
            caption: caption,
            takenAt: ago(minutesAgo),
            location: location,
            accessibilityCaption: alt,
            kind: kind,
            imageURL: "dummy://media/" + pk,
            likeCount: likes,
            hasLiked: liked,
            hasSaved: false,
            hidesCounts: false,
            commentsDisabled: false,
            isReel: reelAudio != nil,
            audioTitle: reelAudio
         )
      }

      addPost("p.castle", by: "masudur.rahman", caption: "Apply for a feature following the link in our bio and we will publish your photos in our account: @travelsfever", minutesAgo: 180, likes: 28_500, location: "Bremen, Germany", alt: "coastal castle ruins")
      addPost("p.rooftops", by: "shea.lewis", caption: "Golden hour from the Alfama rooftops. Three days in and I already want to move here. #lisbon #travel", minutesAgo: 45, likes: 12_100, location: "Lisbon, Portugal", alt: "rooftops at sunset")
      addPost("p.harbour", by: "ben.schade", caption: "Morning ferry across the Elbe. The fog lifted right as we left the dock. #film #35mm", minutesAgo: 600, likes: 4_870, location: "Hamburg, Germany", alt: "harbour in morning fog", liked: true)
      addPost("p.roast", by: "perdana", caption: "New Flores lot on the roaster today. Notes of cacao and plum. #coffee", minutesAgo: 900, likes: 1_320, location: "Jakarta, Indonesia", alt: "coffee beans cooling", kind: .carousel)
      addPost("p.tram", by: "tomas.vidal", caption: "Saturday ride group, 22 of us this week.", minutesAgo: 1_500, likes: 640, location: "Valencia, Spain", alt: "cyclists by the beach")
      addPost("p.zine", by: "ilse.brandt", caption: "Issue four is at the printer.", minutesAgo: 2_100, likes: 980, location: "Vienna, Austria", alt: "stack of printed zines")
      addPost("p.dunes", by: "noor.aziz", caption: "Wadi Rum at first light.", minutesAgo: 2_900, likes: 3_400, location: "Wadi Rum, Jordan", alt: "red sand dunes")
      addPost("p.bridge", by: "stubka", caption: "Charles Bridge before the crowds.", minutesAgo: 3_600, likes: 760, location: "Prague, Czechia", alt: "stone bridge at dawn")
      addPost("p.spice", by: "sumesh", caption: "Market run.", minutesAgo: 4_400, likes: 510, location: "Kochi, India", alt: "spice market stalls")

      world.feedOrder = ["p.rooftops", "p.castle", "p.harbour", "p.roast", "p.tram", "p.zine", "p.dunes", "p.bridge", "p.spice"]

      addPost("r.tram", by: "shea.lewis", caption: "Tram 28 at 7am before the crowds wake up.", minutesAgo: 300, likes: 84_200, kind: .video, reelAudio: "Original audio")
      addPost("r.coffee", by: "perdana", caption: "Three pours, one bean. Which would you pick?", minutesAgo: 700, likes: 12_900, kind: .video, liked: true, reelAudio: "Perdana, Original audio")
      addPost("r.setup", by: "josh.esport", caption: "Desk setup tour, part two. Cable management edition.", minutesAgo: 1_200, likes: 230_000, kind: .video, reelAudio: "Lo-fi Study Loop")
      addPost("r.type", by: "mais.designer", caption: "Kerning is a feeling. Here is how I check it.", minutesAgo: 2_000, likes: 5_430, kind: .video, reelAudio: "Original audio")

      let gridKinds: [Engine.GridTile.Kind] = [.photo, .photo, .carousel, .video, .photo, .carousel]
      let gridTags = ["#travel #film", "#streetphotography", "#coffee #morning", "#lisbon #travel", "#film #35mm", "#architecture"]
      let gridPlaces: [String?] = ["Lisbon, Portugal", nil, "Hamburg, Germany", nil, "Prague, Czechia", "Bremen, Germany", nil]
      for person in people {
         let count = person.id == "viewer" ? 15 : 9

         for index in 0..<count {
            let pk = "g.\(person.id).\(index)"
            let likes = 120 + (index * 7_919 + person.id.count * 131) % 30_000
            let tags = gridTags[(index + person.id.count) % gridTags.count]
            addPost(pk, by: person.id, caption: tags, minutesAgo: Double(3_000 + index * 2_400), likes: likes, location: gridPlaces[(index * 3 + person.id.count) % gridPlaces.count], kind: gridKinds[(index + person.id.count) % gridKinds.count])
         }
      }

      func comment(_ id: String, by authorID: String, _ text: String, minutesAgo: Double, likes: Int, liked: Bool = false) -> Engine.Comment {
         let author = world.users[authorID]!
         return Engine.Comment(
            id: id,
            author: Engine.CommentAuthor(id: author.id, username: author.username, isVerified: author.isVerified, profilePicURL: "dummy://avatar/" + author.id),
            text: text,
            createdAt: ago(minutesAgo),
            likeCount: likes,
            hasLiked: liked,
            parentCommentID: nil,
            replyCount: 0
         )
      }

      world.comments["p.castle"] = [
         comment("c1", by: "anghelina", "The light on the left wall is unreal.", minutesAgo: 150, likes: 42),
         comment("c2", by: "tomas.vidal", "Which coast is this? Adding it to the list.", minutesAgo: 120, likes: 8),
         comment("c3", by: "lina.park", "Submitted mine last week, fingers crossed.", minutesAgo: 30, likes: 3, liked: true),
      ]
      world.comments["p.rooftops"] = [
         comment("c4", by: "noor.aziz", "Told you. Nobody leaves Lisbon on time.", minutesAgo: 40, likes: 19),
         comment("c5", by: "ilse.brandt", "Miradouro de Santa Luzia?", minutesAgo: 20, likes: 2),
      ]
      world.comments["p.harbour"] = [
         comment("c6", by: "stubka", "That fog line is perfect.", minutesAgo: 500, likes: 5),
      ]

      func thread(_ fbid: String, with participantIDs: [String], name: String? = nil, unread: Bool = false, muted: Bool = false, _ lines: [(String, String, Double)]) {
         world.threads[fbid] = ThreadRecord(fbid: fbid, participantIDs: participantIDs, name: name, isMuted: muted, isPinned: false, isUnread: unread)
         world.messages[fbid] = lines.map { senderID, text, minutesAgo in
            let sender = world.users[senderID]!
            return Engine.Message(
               id: "mid.\(fbid).\(Int(minutesAgo))",
               threadFBID: fbid,
               sender: Engine.MessageSender(fbid: sender.fbid, igid: sender.id, name: sender.fullName),
               text: text,
               sentAt: ago(minutesAgo),
               contentType: "text",
               reactions: [],
               repliedToMessageID: nil,
               offlineThreadingID: nil
            )
         }
      }

      thread("t.shea", with: ["shea.lewis"], unread: true, [
         ("shea.lewis", "Are you still coming to Lisbon in October?", 1_500),
         ("viewer", "Yes, landing on the 12th.", 1_490),
         ("viewer", "Send me the name of that bakery again", 1_489),
         ("shea.lewis", "Manteigaria, the one on Rua do Loreto.", 1_400),
         ("shea.lewis", "Just posted the rooftop shots", 12),
         ("shea.lewis", "Tell me which one you like best", 11),
      ])
      thread("t.lisbon", with: ["shea.lewis", "noor.aziz", "tomas.vidal"], name: "Weekend in Lisbon", [
         ("tomas.vidal", "I booked the tram tour for Saturday morning.", 300),
         ("noor.aziz", "How early is morning", 290),
         ("tomas.vidal", "Nine.", 288),
         ("viewer", "I will be there at ten.", 280),
      ])
      thread("t.ben", with: ["ben.schade"], muted: true, [
         ("viewer", "Loved the ferry photo.", 2_900),
         ("ben.schade", "Thanks! Shot it on the 62 line.", 2_880),
      ])
      thread("t.ilse", with: ["ilse.brandt"], [
         ("ilse.brandt", "Can I use your Vienna photo for the zine?", 8_000),
         ("viewer", "Of course, credit @vera.cherry.", 7_900),
      ])
      thread("t.lina", with: ["lina.park"], [
         ("lina.park", "Hey! Saw you in the travelsfever feature.", 20_000),
      ])

      thread("t.req.web", with: ["webuistylist"], [
         ("webuistylist", "Hi! We feature photographers every week. Interested?", 600),
      ])
      world.threads["t.req.web"]?.isRequest = true
      thread("t.req.josh", with: ["josh.esport"], [
         ("josh.esport", "yo, can I use your desk photo in a video", 3_000),
      ])
      world.threads["t.req.josh"]?.isRequest = true

      let olderLines = (0..<30).map { index -> (String, String, Double) in
         let senders = ["tomas.vidal", "noor.aziz", "shea.lewis", "viewer"]
         return (senders[index % senders.count], "Planning message \(index + 1)", Double(9_000 - index * 200))
      }
      let lisbonLines = world.messages["t.lisbon"] ?? []
      thread("t.lisbon", with: ["shea.lewis", "noor.aziz", "tomas.vidal"], name: "Weekend in Lisbon", olderLines)
      world.messages["t.lisbon"]? += lisbonLines

      world.closeFriendIDs = ["shea.lewis", "noor.aziz"]
      world.archivedStoryCount = 12

      if let heartIndex = world.messages["t.shea"]?.firstIndex(where: { $0.text?.hasPrefix("Manteigaria") == true }) {
         let original = world.messages["t.shea"]![heartIndex]
         world.messages["t.shea"]![heartIndex] = Engine.Message(
            id: original.id,
            threadFBID: original.threadFBID,
            sender: original.sender,
            text: original.text,
            sentAt: original.sentAt,
            contentType: original.contentType,
            reactions: [Engine.Reaction(emoji: Engine.Reaction.heart, senderFBID: "fb.viewer")],
            repliedToMessageID: nil,
            offlineThreadingID: nil
         )
      }

      world.notes = [
         Engine.Note(id: "n1", authorID: "shea.lewis", authorUsername: "shea.lewis", text: "Lisbon until Sunday", audience: .mutualFollows, createdAt: ago(120)),
         Engine.Note(id: "n2", authorID: "noor.aziz", authorUsername: "noor.aziz", text: "who is up for sunrise hike", audience: .closeFriends, createdAt: ago(400)),
         Engine.Note(id: "n3", authorID: "ben.schade", authorUsername: "ben.schade", text: "film is expensive", audience: .mutualFollows, createdAt: ago(900)),
      ]

      world.stories = ["perdana", "ben.schade", "stubka", "shea.lewis", "sumesh", "noor.aziz"].enumerated().map { position, userID in
         StoryRecord(userID: userID, itemCount: 2 + position % 3, latestAt: ago(Double(40 + position * 95)), isSeen: false)
      }

      func entry(_ id: String, _ kind: Engine.ActivityEntry.Kind, _ userIDs: [String], minutesAgo: Double, media: String?) -> Engine.ActivityEntry {
         Engine.ActivityEntry(id: id, kind: kind, users: userIDs.compactMap { world.summary($0) }, occurredAt: ago(minutesAgo), mediaCode: media.flatMap { world.posts[$0]?.code })
      }

      world.activity = [
         entry("a1", .likedPost, ["shea.lewis", "noor.aziz"], minutesAgo: 8, media: "g.viewer.1"),
         entry("a2", .commented("This one belongs in a gallery."), ["anghelina"], minutesAgo: 55, media: "g.viewer.1"),
         entry("a3", .followed, ["lina.park"], minutesAgo: 190, media: nil),
         entry("a4", .mentioned("@vera.cherry you need to see this place"), ["tomas.vidal"], minutesAgo: 1_900, media: "p.tram"),
         entry("a5", .likedComment("Which coast is this?"), ["masudur.rahman"], minutesAgo: 3_000, media: "p.castle"),
         entry("a6", .followed, ["josh.esport"], minutesAgo: 5_200, media: nil),
         entry("a7", .likedPost, ["ben.schade", "stubka", "sumesh"], minutesAgo: 9_000, media: "g.viewer.3"),
         entry("a8", .followed, ["mais.designer"], minutesAgo: 20_000, media: nil),
         entry("a9", .commented("Saving this for our trip."), ["ilse.brandt"], minutesAgo: 50_000, media: "g.viewer.5"),
      ]

      world.highlights["viewer"] = ["Lisbon", "Norway", "Film", "Prints"].map { Engine.Highlight(id: "h.viewer." + $0, title: $0, itemCount: 4) }
      for userID in ["shea.lewis", "masudur.rahman", "ben.schade", "lina.park", "tomas.vidal"] {
         world.highlights[userID] = ["Trips", "Friends", "Food"].map { Engine.Highlight(id: "h.\(userID).\($0)", title: $0, itemCount: 3) }
      }

      for pk in ["g.shea.lewis.2", "p.dunes", "g.mais.designer.4"] {
         world.posts[pk]?.hasSaved = true
      }

      return world
   }
}

extension String {
   // String.hashValue is randomised per launch, and shortcodes have to stay put across runs.
   var hashValueStable: Int {
      unicodeScalars.reduce(5_381) { ($0 &* 33 &+ Int($1.value)) & 0x7FFF_FFFF }
   }
}
