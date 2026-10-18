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

      // The live post detail check also runs on the dummy, so its store path can be checked
      // without a request.
      if arguments.contains("--real-post-detail-capture") {
         await accounts.active.gateway.dummyEngine.configure(timing: .instant)
         await RealEngineProbe.runIfRequested(accounts: accounts)
         return
      }

      guard snapshotIndex != nil || wantsExercise else {
         return
      }

      FileHandle.standardError.write(Data("probe: started\n".utf8))

      await accounts.active.gateway.dummyEngine.configure(timing: .instant)
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
            await gateway.dummyEngine.configure(faults: faults)
            await home.loadMore()
            await home.load()
         },
         Shot(name: "revoked", appearance: .aqua) {
            await gateway.resumeAfterCheckpoint()
            faults.checkpointOnNextRequest = false
            faults.sessionRevoked = true
            await gateway.dummyEngine.configure(faults: faults)
            try? await Task.sleep(for: .seconds(1))
            await home.load()
         },
         Shot(name: "session-setup", appearance: .aqua) {
            gateway.acknowledgeRevoked()
         },
         Shot(name: "studio-account", appearance: .aqua) {
            await accounts.addAccount()
            await accounts.active.gateway.dummyEngine.configure(timing: .instant)
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
private final class InteractionProbe {
   static let expectedCheckCount = 36

   let accounts: AccountsStore

   private var passed = 0
   private var failed = 0

   init(accounts: AccountsStore) {
      self.accounts = accounts
   }

   private var gateway: EngineGateway { accounts.active.gateway }
   private var home: HomeStore { accounts.active.home }
   private var direct: DirectStore { accounts.active.direct }
   private var profiles: ProfileStore { accounts.active.profiles }
   private var search: SearchStore { accounts.active.search }

   private func check(_ name: String, _ didPass: Bool, _ detail: String = "") {
      if didPass {
         passed += 1
      } else {
         failed += 1
      }

      let suffix = detail.isEmpty ? "" : " (\(detail))"
      let line = "exercise: \(didPass ? "PASS" : "FAIL") \(name)\(suffix)\n"
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
      await runSignIn()

      let summary = "exercise summary: PASS \(passed) FAIL \(failed) of \(Self.expectedCheckCount) expected\n"
      FileHandle.standardError.write(Data(summary.utf8))
   }

   private func runCore() async {
      await home.load()
      check("feed loads its first page", home.feedState == .loaded && home.orderedPosts.count == DummyEngine.feedPageSize, "\(home.orderedPosts.count) posts")

      await home.loadMore()
      check("pagination appends the next page", home.orderedPosts.count == DummyEngine.feedPageSize * 2, "\(home.orderedPosts.count) posts")

      guard let target = home.orderedPosts.first(where: { $0.isLiked == false }) else {
         check("an unliked post exists", false)
         return
      }

      await home.toggleLike(postPK: target.id)
      let likedCount = await gateway.dummyEngine.world.posts[target.id]?.likeCount
      check("a like reaches the engine", await gateway.dummyEngine.world.posts[target.id]?.hasLiked == true && likedCount == target.likeCount + 1)

      var faults = DummyEngine.Faults()
      faults.outcomeUnknownOnNextWrite = true
      await gateway.dummyEngine.configure(faults: faults)
      await home.toggleLike(postPK: target.id)
      let upstreamLiked = await gateway.dummyEngine.world.posts[target.id]?.hasLiked
      check("an uncertain unlike is read back, not resent", home.post(pk: target.id)?.isLiked == upstreamLiked && upstreamLiked == false)

      faults.outcomeUnknownOnNextWrite = false
      faults.transportFailureRate = 1
      await gateway.dummyEngine.configure(faults: faults)
      await home.toggleLike(postPK: target.id)
      check("a failed like is rolled back", home.post(pk: target.id)?.isLiked == false)
      faults.transportFailureRate = 0
      await gateway.dummyEngine.configure(faults: faults)

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
      await gateway.dummyEngine.configure(faults: faults)
      await direct.send("rejected", to: threadID)
      await direct.send("refused without sending", to: threadID)
      let status = await gateway.dummyEngine.status()
      let refusedLocally = status.requests.first?.outcome.contains("nothing sent") == true
      check("an unrecognised rejection stops later writes", status.writesStopped && refusedLocally)
      await gateway.dummyEngine.reconnect()

      faults = DummyEngine.Faults()
      faults.checkpointOnNextRequest = true
      await gateway.dummyEngine.configure(faults: faults)
      await home.load()
      let isCheckpointed = if case .checkpoint = gateway.session { true } else { false }
      check("a checkpoint halts the session", isCheckpointed)

      let requestsBefore = await gateway.dummyEngine.status().requests.count
      await home.load()
      let requestsAfter = await gateway.dummyEngine.status().requests.count
      check("nothing is sent while checkpointed", requestsBefore == requestsAfter)

      await gateway.resumeAfterCheckpoint()
      check("resuming after the browser check reactivates", gateway.session == .active)

      await gateway.dummyEngine.configure(timing: .parity)
      let parityStart = Date.now
      async let firstRead: Void = home.loadStories()
      async let secondRead: Void = home.loadStories()
      _ = await (firstRead, secondRead)
      let parityElapsed = Date.now.timeIntervalSince(parityStart)
      check("parity spaces two reads at least 1.3 s apart", parityElapsed >= 1.3, String(format: "%.1fs", parityElapsed))
      await gateway.dummyEngine.configure(timing: .instant)
   }

   // The sign-in states: what the setup form accepts and refuses, that no cookie value reaches an
   // error message, how the session row words the age, and where a revoked session and a
   // checkpoint route. A throwaway gateway is used so the account under test is not disturbed.
   private func runSignIn() async {
      let goodSession = "1234567890%3AabcDEFghiJKL%3A28%3AAYexample0000"
      let goodToken = "aBcDeFgHiJkLmNoPqRsTuVwXyZ012345"
      let good = SessionCookieInput(sessionID: goodSession, userID: "1234567890", csrfToken: goodToken).check()
      check("sign-in: a well formed paste is accepted", good.cleaned != nil && good.problems.isEmpty)

      let quoted = SessionCookieInput(sessionID: "\"\(goodSession)\";", userID: " 1234567890 ", csrfToken: "\(goodToken)\n").check()
      check("sign-in: quotes, a semicolon and spaces are stripped", quoted.cleaned == good.cleaned)

      let named = SessionCookieInput(sessionID: "sessionid=\(goodSession)", userID: "ds_user_id=1234567890", csrfToken: goodToken).check()
      check("sign-in: a pasted name=value pair is refused per field", named.cleaned == nil && named.problems[.sessionID] != nil && named.problems[.userID] != nil && named.problems[.csrfToken] == nil)

      let malformed = SessionCookieInput(sessionID: "short", userID: "12ab", csrfToken: "bad token!").check()
      check("sign-in: short, non numeric and spaced values are refused", malformed.cleaned == nil && malformed.problems.count == 3)

      let leaky = SessionCookieInput(sessionID: "SECRETSESSIONVALUE with a space", userID: "SECRETUSER", csrfToken: "SECRETTOKEN!").check()
      let messages = leaky.problems.values.joined(separator: " ")
      check("sign-in: an error message never holds a pasted value", !leaky.problems.isEmpty && !messages.contains("SECRET"))

      let untouched = SessionCookieInput(sessionID: "", userID: "", csrfToken: "").check()
      check("sign-in: an empty form shows no errors and cannot continue", untouched.problems.isEmpty && untouched.cleaned == nil)

      let refreshedAt = await gateway.engine.sessionRefreshedAt()
      let now = Date()
      let isAgeKnown = refreshedAt.map { SessionAge.describe(refreshedAt: $0, now: now) == "Refreshed 2 d ago" } ?? false
      check("sign-in: the session row words an age and a missing one", isAgeKnown && SessionAge.describe(refreshedAt: nil) == "Not refreshed yet")

      let throwaway = EngineGateway(engine: DummyEngine(timing: .instant, world: .seed()))
      throwaway.handle(.authenticationFailed, label: "the session", isWrite: false)
      check("sign-in: a refused session routes to the revoked state", throwaway.session == .revoked)
   }

   private func runAdditions() async {
      let engine = gateway.dummyEngine

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
      if let comment = home.comments(for: commentPost.id).first(where: { $0.isLiked == false }) {
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

      let followTarget = "anghelina"
      await profiles.toggleFollow(followTarget)
      let followedUpstream = await engine.world.followingIDs.contains(followTarget)
      check("a follow reaches the engine", followedUpstream && profiles.isFollowing(followTarget))

      await profiles.toggleFollow(followTarget)
      let stillFollowedUpstream = await engine.world.followingIDs.contains(followTarget)
      check("an unfollow reaches the engine", followedUpstream && !stillFollowedUpstream && !profiles.isFollowing(followTarget))

      await search.loadHashtag("travel")
      check("a hashtag page loads posts", !search.tiles(for: "tag:travel").isEmpty, "\(search.tiles(for: "tag:travel").count) posts")

      let primaryViewer = gateway.viewerID
      await accounts.addAccount()
      let switched = accounts.active.gateway.viewerID != primaryViewer
      await accounts.switchTo(primaryViewer)
      check("adding an account switches to it and back", switched && accounts.active.gateway.viewerID == primaryViewer && accounts.sessions.count == 2)

      let sessionEngines = accounts.sessions.compactMap { $0.gateway.dummy.map(ObjectIdentifier.init) }
      let hasEngineForEverySession = sessionEngines.count == accounts.sessions.count
      let hasDistinctEngines = Set(sessionEngines).count == accounts.sessions.count
      let hasDistinctViewers = Set(accounts.sessions.map(\.gateway.viewerID)).count == accounts.sessions.count
      let hasTwoSessions = accounts.sessions.count == 2
      let hasOwnClients = hasTwoSessions && hasEngineForEverySession && hasDistinctEngines && hasDistinctViewers
      check("adding a second account gets its own engine client", hasOwnClients, "\(Set(sessionEngines).count) clients for \(accounts.sessions.count) sessions")

      guard let addedSession = accounts.sessions.first(where: { $0.id != primaryViewer }), let addedEngine = addedSession.gateway.dummy else {
         check("removing an account closes its client", false, "no second account")
         return
      }

      // Stand in for the engine's Session.save, in the exercise's own sessions directory.
      let fileManager = FileManager.default
      try? fileManager.createDirectory(at: PythonEngineFactory.sessionsDirectory, withIntermediateDirectories: true)

      for sessionFile in accounts.sessions.compactMap(\.sessionFile) {
         try? Data("{}".utf8).write(to: sessionFile)
      }

      let addedFile = addedSession.sessionFile
      let primaryFile = accounts.active.sessionFile
      let addedFileWasWritten = addedFile.map { fileManager.fileExists(atPath: $0.path) } ?? false

      let primaryEngine = accounts.active.gateway.dummyEngine
      let addedClosesBefore = await addedEngine.closeCount
      let primaryClosesBefore = await primaryEngine.closeCount
      await accounts.remove(addedSession.id)
      let addedClosesAfter = await addedEngine.closeCount
      let primaryClosesAfter = await primaryEngine.closeCount
      let closedOnce = addedClosesAfter == addedClosesBefore + 1
      let primaryUntouched = primaryClosesAfter == primaryClosesBefore
      let isForgotten = accounts.sessions.count == 1 && accounts.activeID == primaryViewer
      let closesOnlyItsClient = closedOnce && primaryUntouched && isForgotten
      check("removing an account closes its client", closesOnlyItsClient, "closed \(addedClosesAfter - addedClosesBefore) time(s)")

      let addedFileIsGone = addedFile.map { !fileManager.fileExists(atPath: $0.path) } ?? false
      let primaryFileRemains = primaryFile.map { fileManager.fileExists(atPath: $0.path) } ?? false
      let deletesOnlyItsFile = addedFileWasWritten && addedFileIsGone && primaryFileRemains
      check("removing an account deletes only its own session file", deletesOnlyItsFile, "removed gone \(addedFileIsGone), other kept \(primaryFileRemains)")

      if let primaryFile {
         try? fileManager.removeItem(at: primaryFile)
      }
   }
}
#endif
