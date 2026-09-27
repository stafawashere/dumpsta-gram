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
      let prepare: () async -> Void
   }

   static func runIfRequested(navigation: NavigationStore, gateway: EngineGateway, home: HomeStore, direct: DirectStore) async {
      let arguments = ProcessInfo.processInfo.arguments
      let snapshotIndex = arguments.firstIndex(of: "--snapshot-dir")
      let wantsExercise = arguments.contains("--exercise")

      guard snapshotIndex != nil || wantsExercise else {
         return
      }

      FileHandle.standardError.write(Data("probe: started\n".utf8))

      await gateway.engine.configure(timing: .instant)
      try? await Task.sleep(for: .seconds(1.5))

      if wantsExercise {
         await InteractionProbe(navigation: navigation, gateway: gateway, home: home, direct: direct).run()
      }

      if let snapshotIndex, arguments.indices.contains(snapshotIndex + 1) {
         let outputDirectory = URL(fileURLWithPath: arguments[snapshotIndex + 1], isDirectory: true)
         await capturePages(to: outputDirectory, navigation: navigation, gateway: gateway, home: home)
      }

      NSApp.terminate(nil)
   }

   private static func capturePages(to outputDirectory: URL, navigation: NavigationStore, gateway: EngineGateway, home: HomeStore) async {
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
         Shot(name: "notice", appearance: .aqua) {
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
      ]

      for shot in shots {
         NSApp.appearance = NSAppearance(named: shot.appearance)
         await shot.prepare()
         try? await Task.sleep(for: .milliseconds(1_200))
         capture(to: outputDirectory.appendingPathComponent("\(shot.name).png"))
      }
   }

   private static func capture(to fileURL: URL) {
      guard let contentView = NSApp.windows.first(where: { $0.isVisible })?.contentView else {
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
   let navigation: NavigationStore
   let gateway: EngineGateway
   let home: HomeStore
   let direct: DirectStore

   private func check(_ name: String, _ passed: Bool, _ detail: String = "") {
      let suffix = detail.isEmpty ? "" : " (\(detail))"
      let line = "exercise: \(passed ? "PASS" : "FAIL") \(name)\(suffix)\n"
      FileHandle.standardError.write(Data(line.utf8))
   }

   func run() async {
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
      faults.unrecognisedRejectionOnNextWrite = false
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
         let newest = direct.messages(in: threadID).last

         if newest?.senderID != gateway.viewerID {
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
}
#endif
