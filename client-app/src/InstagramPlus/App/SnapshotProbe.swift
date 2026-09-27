#if DEBUG
import AppKit

// Launch with `--snapshot-dir <path>` to write a capture of every page and state, or with
// `--exercise` to drive interactions through the dummy engine and print one line per check.
// Both run on the instant timing and quit when done.
@MainActor
enum SnapshotProbe {
   private struct Shot {
      let name: String
      let appearance: NSAppearance.Name
      var capturesSheet = false
      let prepare: () async -> Void
   }

   static func runIfRequested(accounts: AccountsStore) async {
      let arguments = ProcessInfo.processInfo.arguments
      let snapshotIndex = arguments.firstIndex(of: "--snapshot-dir")
      let wantsExercise = arguments.contains("--exercise")

      guard snapshotIndex != nil || wantsExercise else {
         return
      }

      FileHandle.standardError.write(Data("probe: started\n".utf8))

      await accounts.active.gateway.engine.configure(timing: .instant)
      try? await Task.sleep(for: .seconds(1.5))

      if wantsExercise {
         await InteractionProbe(accounts: accounts).run()
      }

      if let snapshotIndex, arguments.indices.contains(snapshotIndex + 1) {
         let outputDirectory = URL(fileURLWithPath: arguments[snapshotIndex + 1], isDirectory: true)
         let session = accounts.active
         await capturePages(to: outputDirectory, navigation: session.navigation, gateway: session.gateway, home: session.home, direct: session.direct, accounts: accounts)
      }

      NSApp.terminate(nil)
   }

   private static func capturePages(to outputDirectory: URL, navigation: NavigationStore, gateway: EngineGateway, home: HomeStore, direct: DirectStore, accounts: AccountsStore) async {
      try? FileManager.default.createDirectory(at: outputDirectory, withIntermediateDirectories: true)

      let viewerID = gateway.viewerID
      let firstStoryID = home.stories.first?.id
      let firstPostCode = home.orderedPosts.first?.code
      var faults = DummyEngine.Faults()

      let shots = [
         Shot(name: "home-light", appearance: .aqua) { navigation.route = .home },
         Shot(name: "home-dark", appearance: .darkAqua) { navigation.route = .home },
         Shot(name: "reels", appearance: .darkAqua) { navigation.route = .reels },
         Shot(name: "messages-light", appearance: .aqua) { navigation.route = .messages },
         Shot(name: "messages-dark", appearance: .darkAqua) { navigation.route = .messages },
         Shot(name: "search", appearance: .aqua) { navigation.route = .search },
         Shot(name: "search-results", appearance: .aqua) {
            navigation.route = .search
            navigation.searchQuery = "li"
         },
         Shot(name: "notifications", appearance: .aqua) {
            navigation.searchQuery = ""
            navigation.route = .notifications
         },
         Shot(name: "create", appearance: .aqua) { navigation.route = .create },
         Shot(name: "profile-own", appearance: .aqua) { navigation.route = .profile(viewerID) },
         Shot(name: "profile-other-dark", appearance: .darkAqua) { navigation.route = .profile("shea.lewis") },
         Shot(name: "profile-private", appearance: .aqua) { navigation.route = .profile("lina.park") },
         Shot(name: "settings", appearance: .aqua) { navigation.route = .settings },
         Shot(name: "post-detail", appearance: .aqua) {
            navigation.route = .home
            navigation.presentedPostCode = firstPostCode
         },
         Shot(name: "story", appearance: .darkAqua) {
            navigation.presentedPostCode = nil
            navigation.presentedStoryAuthorID = firstStoryID
         },
         Shot(name: "hashtag", appearance: .aqua) {
            navigation.dismissOverlays()
            navigation.route = .hashtag("travel")
         },
         Shot(name: "place", appearance: .aqua) { navigation.route = .place(id: "lisbon", name: "Lisbon, Portugal") },
         Shot(name: "search-tags", appearance: .aqua) {
            navigation.route = .search
            navigation.searchQuery = "film"
         },
         Shot(name: "archive", appearance: .aqua) {
            navigation.searchQuery = ""
            navigation.route = .archive
         },
         Shot(name: "close-friends", appearance: .aqua) { navigation.route = .relationships(.closeFriends) },
         Shot(name: "highlight", appearance: .darkAqua) {
            navigation.route = .profile(viewerID)
            navigation.presentedHighlight = PresentedHighlight(owner: Account(id: viewerID, username: "vera.cherry", displayName: "Vera Cherry", location: nil), highlight: Highlight(id: "h.viewer.Lisbon", title: "Lisbon"), itemCount: 4)
         },
         Shot(name: "conversation", appearance: .aqua) {
            navigation.dismissOverlays()
            navigation.route = .messages
            await direct.select("t.lisbon")
         },
         Shot(name: "request", appearance: .aqua) {
            await direct.loadRequests()
            await direct.select("t.req.web")
         },
         Shot(name: "share-sheet", appearance: .aqua, capturesSheet: true) {
            navigation.route = .home
            if let pk = home.orderedPosts.first?.id {
               navigation.share(postPK: pk)
            }
         },
         Shot(name: "new-message-sheet", appearance: .aqua, capturesSheet: true) {
            navigation.sharing = nil
            try? await Task.sleep(for: .milliseconds(600))
            navigation.isComposingMessage = true
         },
         Shot(name: "edit-profile-sheet", appearance: .aqua, capturesSheet: true) {
            navigation.isComposingMessage = false
            try? await Task.sleep(for: .milliseconds(600))
            navigation.isEditingProfile = true
         },
         Shot(name: "notice", appearance: .aqua) {
            navigation.isEditingProfile = false
            navigation.dismissOverlays()
            gateway.post(Notice(tone: .warning, title: "Could not confirm the like", message: "It may have gone through. Instagram+ is checking instead of trying again."))
         },
         Shot(name: "checkpoint", appearance: .aqua) {
            faults.checkpointOnNextRequest = true
            await gateway.engine.configure(faults: faults)
            await home.loadMore()
            await home.load()
         },
         Shot(name: "revoked", appearance: .aqua) {
            await gateway.resumeAfterCheckpoint()
            faults.checkpointOnNextRequest = false
            faults.sessionRevoked = true
            await gateway.engine.configure(faults: faults)
            try? await Task.sleep(for: .seconds(1))
            await home.load()
         },
         Shot(name: "session-setup", appearance: .aqua) {
            gateway.acknowledgeRevoked()
         },
         Shot(name: "studio-account", appearance: .aqua) {
            await accounts.addAccount()
            await accounts.active.gateway.engine.configure(timing: .instant)
            try? await Task.sleep(for: .seconds(1))
         },
      ]

      for shot in shots {
         NSApp.appearance = NSAppearance(named: shot.appearance)
         await shot.prepare()
         try? await Task.sleep(for: .milliseconds(1_200))
         capture(to: outputDirectory.appendingPathComponent("\(shot.name).png"), sheet: shot.capturesSheet)
      }
   }

   private static func capture(to fileURL: URL, sheet: Bool = false) {
      let window = sheet
         ? NSApp.windows.first { $0.isVisible && $0.sheetParent != nil }
         : NSApp.windows.first { $0.isVisible && $0.sheetParent == nil }

      guard let contentView = window?.contentView else {
         print("snapshot: no visible window")
         return
      }

      guard let bitmap = contentView.bitmapImageRepForCachingDisplay(in: contentView.bounds) else {
         print("snapshot: could not allocate bitmap")
         return
      }

      contentView.cacheDisplay(in: contentView.bounds, to: bitmap)

      guard let pngData = bitmap.representation(using: .png, properties: [:]) else {
         print("snapshot: could not encode png")
         return
      }

      do {
         try pngData.write(to: fileURL)
         print("snapshot: wrote \(fileURL.lastPathComponent) \(bitmap.pixelsWide)x\(bitmap.pixelsHigh)")
      } catch {
         print("snapshot: write failed \(error)")
      }
   }
}

@MainActor
private struct InteractionProbe {
   let accounts: AccountsStore

   private var gateway: EngineGateway { accounts.active.gateway }
   private var home: HomeStore { accounts.active.home }
   private var direct: DirectStore { accounts.active.direct }
   private var profiles: ProfileStore { accounts.active.profiles }
   private var search: SearchStore { accounts.active.search }

   private func check(_ name: String, _ passed: Bool, _ detail: String = "") {
      let suffix = detail.isEmpty ? "" : " (\(detail))"
      let line = "exercise: \(passed ? "PASS" : "FAIL") \(name)\(suffix)\n"
      FileHandle.standardError.write(Data(line.utf8))
   }

   private func temporaryImage(_ name: String) -> URL {
      let url = FileManager.default.temporaryDirectory.appendingPathComponent("probe-\(name).png")
      let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 8, pixelsHigh: 8, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
      try? bitmap.representation(using: .png, properties: [:])?.write(to: url)
      return url
   }

   func run() async {
      await runCore()
      await runAdditions()
   }

   private func runCore() async {
      await home.load()
      check("feed loads its first page", home.feedState == .loaded && home.orderedPosts.count == DummyEngine.feedPageSize, "\(home.orderedPosts.count) posts")

      await home.loadMore()
      check("pagination appends the next page", home.orderedPosts.count == DummyEngine.feedPageSize * 2, "\(home.orderedPosts.count) posts")

      guard let target = home.orderedPosts.first(where: { !$0.isLiked }) else {
         check("an unliked post exists", false)
         return
      }

      await home.toggleLike(postPK: target.id)
      let likedCount = await gateway.engine.world.posts[target.id]?.likeCount
      check("a like reaches the engine", await gateway.engine.world.posts[target.id]?.hasLiked == true && likedCount == target.likeCount + 1)

      var faults = DummyEngine.Faults()
      faults.outcomeUnknownOnNextWrite = true
      await gateway.engine.configure(faults: faults)
      await home.toggleLike(postPK: target.id)
      let upstreamLiked = await gateway.engine.world.posts[target.id]?.hasLiked
      check("an uncertain unlike is read back, not resent", home.post(pk: target.id)?.isLiked == upstreamLiked && upstreamLiked == false)

      faults.outcomeUnknownOnNextWrite = false
      faults.transportFailureRate = 1
      await gateway.engine.configure(faults: faults)
      await home.toggleLike(postPK: target.id)
      check("a failed like is rolled back", home.post(pk: target.id)?.isLiked == false)
      faults.transportFailureRate = 0
      await gateway.engine.configure(faults: faults)

      await direct.loadInbox()
      check("the inbox loads and the listener starts", direct.inboxState == .loaded && direct.isListening, "\(direct.threads.count) threads")

      let threadID = "t.ben"
      await direct.select(threadID)
      let beforeCount = direct.messages(in: threadID).count
      await direct.send("probe message", to: threadID)
      let sent = direct.messages(in: threadID).last
      check("a sent message settles as sent", sent?.delivery == .sent && direct.messages(in: threadID).count == beforeCount + 1)

      var replyArrived = false
      for _ in 0..<30 {
         try? await Task.sleep(for: .seconds(1))

         if direct.messages(in: threadID).last?.senderID != gateway.viewerID {
            replyArrived = true
            break
         }
      }
      check("a reply arrives through the event buffer", replyArrived)

      faults.unrecognisedRejectionOnNextWrite = true
      await gateway.engine.configure(faults: faults)
      await direct.send("rejected", to: threadID)
      await direct.send("refused without sending", to: threadID)
      let status = await gateway.engine.status()
      let refusedLocally = status.requests.first?.outcome.contains("nothing sent") == true
      check("an unrecognised rejection stops later writes", status.writesStopped && refusedLocally)
      await gateway.engine.reconnect()

      faults = DummyEngine.Faults()
      faults.checkpointOnNextRequest = true
      await gateway.engine.configure(faults: faults)
      await home.load()
      let isCheckpointed = if case .checkpoint = gateway.session { true } else { false }
      check("a checkpoint halts the session", isCheckpointed)

      let requestsBefore = await gateway.engine.status().requests.count
      await home.load()
      let requestsAfter = await gateway.engine.status().requests.count
      check("nothing is sent while checkpointed", requestsBefore == requestsAfter)

      await gateway.resumeAfterCheckpoint()
      check("resuming after the browser check reactivates", gateway.session == .active)

      await gateway.engine.configure(timing: .parity)
      let parityStart = Date.now
      async let firstRead: Void = home.loadStories()
      async let secondRead: Void = home.loadStories()
      _ = await (firstRead, secondRead)
      let parityElapsed = Date.now.timeIntervalSince(parityStart)
      check("parity spaces two reads at least 1.3 s apart", parityElapsed >= 1.3, String(format: "%.1fs", parityElapsed))
      await gateway.engine.configure(timing: .instant)
   }

   private func runAdditions() async {
      let engine = gateway.engine

      let urls = [temporaryImage("a"), temporaryImage("b")]
      let published = await home.publish(imageURLs: urls, caption: "probe carousel #probetag")
      let newest = home.orderedPosts.first
      check("a two image post publishes as a carousel", published && newest?.kind == .carousel && newest?.caption.contains("probe carousel") == true)

      await direct.loadRequests()
      let requestCount = direct.requests.count
      await direct.resolveRequest("t.req.web", accept: true)
      let acceptedUpstream = await engine.world.threads["t.req.web"]?.isRequest == false
      check("accepting a request moves it into the inbox", acceptedUpstream && direct.requests.count == requestCount - 1 && direct.threads.contains { $0.id == "t.req.web" })

      await direct.select("t.shea")
      if let first = direct.messages(in: "t.shea").first(where: { !$0.viewerReacted }) {
         await direct.toggleReaction(first.id, in: "t.shea")
         let reactions = await engine.world.messages["t.shea"]?.first { $0.id == first.id }?.reactions.count ?? 0
         check("a reaction reaches the engine", reactions > 0 && direct.message(first.id, in: "t.shea")?.viewerReacted == true)
      } else {
         check("a message without a reaction exists", false)
      }

      await direct.select("t.lisbon")
      let firstPage = direct.messages(in: "t.lisbon").count
      await direct.loadOlder("t.lisbon")
      check("older messages load above the first page", direct.messages(in: "t.lisbon").count > firstPage, "\(firstPage) then \(direct.messages(in: "t.lisbon").count)")

      let didCreate = await direct.createThread(with: [Account(id: "stubka", username: "stubka", displayName: "Stubka", location: nil)])
      check("a new conversation is created and selected", didCreate && direct.selectedThread?.participants.first?.id == "stubka")

      guard let commentPost = home.post(pk: "p.castle") ?? home.orderedPosts.first else {
         check("a post with comments exists", false)
         return
      }

      await home.loadComments(postPK: commentPost.id)
      if let comment = home.comments(for: commentPost.id).first(where: { !$0.isLiked }) {
         await home.toggleCommentLike(comment.id, on: commentPost.id)
         let upstream = await engine.world.comments[commentPost.id]?.first { $0.id == comment.id }?.hasLiked
         check("a comment like reaches the engine", upstream == true)

         await home.reply("probe reply", to: comment.id, on: commentPost.id, viewer: profiles.viewerAccount)
         let reply = home.comments(for: commentPost.id).last
         check("a reply is threaded under its parent", reply?.parentID == comment.id && reply?.isPending == false)
      }

      await profiles.setBlocked("ben.schade", blocked: true)
      await home.load()
      let feedAuthors = Set(home.orderedPosts.map(\.author.id))
      check("blocking removes the author from the feed", !feedAuthors.contains("ben.schade") && profiles.details(for: "ben.schade")?.isBlocking == true)
      await profiles.setBlocked("ben.schade", blocked: false)

      await search.loadHashtag("travel")
      check("a hashtag page loads posts", !search.tiles(for: "tag:travel").isEmpty, "\(search.tiles(for: "tag:travel").count) posts")

      let primaryViewer = gateway.viewerID
      await accounts.addAccount()
      let switched = accounts.active.gateway.viewerID != primaryViewer
      await accounts.switchTo(primaryViewer)
      check("adding an account switches to it and back", switched && accounts.active.gateway.viewerID == primaryViewer && accounts.sessions.count == 2)
   }
}
#endif
