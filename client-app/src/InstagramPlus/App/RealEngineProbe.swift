#if DEBUG
import AppKit

// Live checks on the real engine, each writing captures of the window and then quitting. They
// print load states and counts, never content. Captures of a live account hold that account's
// data, so their paths belong outside the repository.
//
//    --real-profile-capture <png>          opens the own Profile page and captures it
//    --real-home-capture <directory>       waits for the first feed page on Home, writes
//                                          home.png, then opens the own Profile page and
//                                          writes profile.png
//    --real-comments <post pk>             reads the first comments page of one post and prints
//                                          its count and whether a next page exists, no capture
//    --real-inbox-capture <png>            opens Messages, waits for the inbox's first page,
//                                          prints thread and unread counts and captures it
//    --real-events-capture <png>           starts the listener through the gateway, drains it
//                                          for INSTAGRAMPLUS_EVENTS_SECONDS (default 20), stops
//                                          it, prints event counts and the listener state, and
//                                          captures Messages
//    --real-profile-tabs-capture <png>     opens the own Profile page, reads its posts grid
//                                          and highlights, then the reels, tagged and saved
//                                          tabs, prints counts and captures the page
//    --real-stories-tray-capture <png>     waits for the stories tray Home reads at launch,
//                                          prints row counts and captures Home. Refuses to run
//                                          when story reels may reach Instagram, and never
//                                          opens a reel
//    --real-search-capture <png>           opens Search, which reads the recent searches and
//                                          the first explore page, then searches one fixed
//                                          term, prints counts and captures the page
//    --real-reels-capture <png>            opens Reels, reads the first page and one more
//                                          through its cursor, prints counts and captures it
//    --real-activity-capture <png>         opens Notifications, which reads the activity feed
//                                          and the follow requests, prints counts with the rail's
//                                          suggestions and captures the page
//    --real-post-detail-capture <png>      opens the post INSTAGRAMPLUS_PROBE_POST_CODE names, which
//                                          reads it through media.page, reads its likers once,
//                                          prints counts and captures the overlay
//    --real-profile-extras-capture <png>   opens the own Profile page on its saved tab, reads the
//                                          collections, then the mutual followers and similar
//                                          accounts of INSTAGRAMPLUS_PROBE_USER_ID or the viewer,
//                                          prints counts and captures the page
//
//    --real-signin-capture <png>           drives the setup screen's own path on a fresh sessions
//                                          directory: reads the cookie file INSTAGRAMPLUS_PROBE_COOKIE_FILE
//                                          names, validates it, verifies the account, confirms it
//                                          as a person would, waits for the first feed page on Home
//                                          and captures it. Prints states and counts, no value
//    --real-resume-capture <png>           the next launch: opens the saved session with no cookie
//                                          input and waits for the first feed page on Home
//
// Each flag takes exactly one value. AppKit reads a bare trailing argument as a file to open,
// and then SwiftUI opens no window at all.
@MainActor
enum RealEngineProbe {
   static func runIfRequested(accounts: AccountsStore) async {
      let arguments = ProcessInfo.processInfo.arguments

      if let flagIndex = arguments.firstIndex(of: "--real-home-capture"), arguments.indices.contains(flagIndex + 1) {
         let directory = URL(fileURLWithPath: arguments[flagIndex + 1], isDirectory: true)
         let homeURL = directory.appendingPathComponent("home.png")
         let profileURL = directory.appendingPathComponent("profile.png")

         await captureHome(accounts: accounts, to: homeURL)
         await captureProfile(accounts: accounts, to: profileURL)
         NSApp.terminate(nil)
         return
      }

      if let flagIndex = arguments.firstIndex(of: "--real-signin-capture"), arguments.indices.contains(flagIndex + 1) {
         await signIn(accounts: accounts, to: URL(fileURLWithPath: arguments[flagIndex + 1]))
         NSApp.terminate(nil)
         return
      }

      if let flagIndex = arguments.firstIndex(of: "--real-resume-capture"), arguments.indices.contains(flagIndex + 1) {
         print("[probe] relaunch, saved accounts open: \(accounts.sessions.filter { !$0.id.isEmpty }.count)")
         await captureHome(accounts: accounts, to: URL(fileURLWithPath: arguments[flagIndex + 1]))
         NSApp.terminate(nil)
         return
      }

      if let flagIndex = arguments.firstIndex(of: "--real-inbox-capture"), arguments.indices.contains(flagIndex + 1) {
         await captureInbox(accounts: accounts, to: URL(fileURLWithPath: arguments[flagIndex + 1]))
         NSApp.terminate(nil)
         return
      }

      if let flagIndex = arguments.firstIndex(of: "--real-events-capture"), arguments.indices.contains(flagIndex + 1) {
         await runEvents(accounts: accounts, captureTo: URL(fileURLWithPath: arguments[flagIndex + 1]))
         NSApp.terminate(nil)
         return
      }

      if let flagIndex = arguments.firstIndex(of: "--real-profile-tabs-capture"), arguments.indices.contains(flagIndex + 1) {
         await captureProfileTabs(accounts: accounts, to: URL(fileURLWithPath: arguments[flagIndex + 1]))
         NSApp.terminate(nil)
         return
      }

      if let flagIndex = arguments.firstIndex(of: "--real-stories-tray-capture"), arguments.indices.contains(flagIndex + 1) {
         await captureStoriesTray(accounts: accounts, to: URL(fileURLWithPath: arguments[flagIndex + 1]))
         NSApp.terminate(nil)
         return
      }

      if let flagIndex = arguments.firstIndex(of: "--real-search-capture"), arguments.indices.contains(flagIndex + 1) {
         await captureSearch(accounts: accounts, to: URL(fileURLWithPath: arguments[flagIndex + 1]))
         NSApp.terminate(nil)
         return
      }

      if let flagIndex = arguments.firstIndex(of: "--real-reels-capture"), arguments.indices.contains(flagIndex + 1) {
         await captureReels(accounts: accounts, to: URL(fileURLWithPath: arguments[flagIndex + 1]))
         NSApp.terminate(nil)
         return
      }

      if let flagIndex = arguments.firstIndex(of: "--real-activity-capture"), arguments.indices.contains(flagIndex + 1) {
         await captureActivity(accounts: accounts, to: URL(fileURLWithPath: arguments[flagIndex + 1]))
         NSApp.terminate(nil)
         return
      }

      if let flagIndex = arguments.firstIndex(of: "--real-post-detail-capture"), arguments.indices.contains(flagIndex + 1) {
         await capturePostDetail(accounts: accounts, to: URL(fileURLWithPath: arguments[flagIndex + 1]))
         NSApp.terminate(nil)
         return
      }

      if let flagIndex = arguments.firstIndex(of: "--real-profile-extras-capture"), arguments.indices.contains(flagIndex + 1) {
         await captureProfileExtras(accounts: accounts, to: URL(fileURLWithPath: arguments[flagIndex + 1]))
         NSApp.terminate(nil)
         return
      }

      if let flagIndex = arguments.firstIndex(of: "--real-comments"), arguments.indices.contains(flagIndex + 1) {
         await readComments(accounts: accounts, postPK: arguments[flagIndex + 1])
         NSApp.terminate(nil)
         return
      }

      if let flagIndex = arguments.firstIndex(of: "--real-profile-capture"), arguments.indices.contains(flagIndex + 1) {
         await captureProfile(accounts: accounts, to: URL(fileURLWithPath: arguments[flagIndex + 1]))
         NSApp.terminate(nil)
      }
   }

   // The setup screen's path without the clicking: the same validation, the same
   // verifyBrowserSession and confirmPending the buttons call. The probe reads its cookies from a
   // file and prints no value.
   private static func signIn(accounts: AccountsStore, to outputURL: URL) async {
      guard let path = ProcessInfo.processInfo.environment["INSTAGRAMPLUS_PROBE_COOKIE_FILE"] else {
         print("[probe] sign-in needs INSTAGRAMPLUS_PROBE_COOKIE_FILE")
         return
      }

      print("[probe] fresh launch, saved accounts open: \(accounts.sessions.filter { !$0.id.isEmpty }.count), session \(describe(accounts.active.gateway.session))")

      guard case .success(let material) = PythonEngineFactory.readCookieFile(URL(fileURLWithPath: path)) else {
         print("[probe] the cookie file could not be read")
         return
      }

      let report = SessionCookieInput(sessionID: material.sessionID, userID: material.userID, csrfToken: material.csrfToken).check()
      print("[probe] form validation accepted: \(report.cleaned != nil), problem fields: \(report.problems.keys.map(\.rawValue).sorted())")

      guard let cleaned = report.cleaned else {
         return
      }

      switch await accounts.verifyBrowserSession(cleaned) {
         case .needsConfirmation(let pending):
            print("[probe] verify read the account back, username present: \(!pending.account.username.isEmpty), avatar present: \(pending.account.profilePicURL != nil), followers \(pending.followerCount)")
            await accounts.confirmPending()

         case .routedToState:
            print("[probe] verify routed to a state view: \(describe(accounts.active.gateway.session))")
            return

         case .rejected(let problem):
            print("[probe] verify rejected: \(problem)")
            return
      }

      let session = accounts.active
      print("[probe] confirmed, account installed: \(!session.id.isEmpty), session \(describe(session.gateway.session))")
      await captureHome(accounts: accounts, to: outputURL)
   }

   private static func captureHome(accounts: AccountsStore, to outputURL: URL) async {
      let session = accounts.active

      print("[probe] opening Home")
      session.navigation.route = .home

      let state = await settle(session) { session.home.feedState }
      let postCount = session.home.orderedPosts.count
      let unshownCount = session.home.unshownFeedItemCount

      print("[probe] feed state \(describe(state)), posts \(postCount), units not shown \(unshownCount), more pages \(session.home.hasMorePosts), session \(describe(session.gateway.session))")

      // Lets the cards lay out before the capture.
      try? await Task.sleep(for: .seconds(3))
      capture(to: outputURL)
   }

   private static func captureInbox(accounts: AccountsStore, to outputURL: URL) async {
      let session = accounts.active
      let direct = session.direct

      print("[probe] opening Messages")
      session.navigation.route = .messages

      let state = await settle(session) { direct.inboxState }
      let unreadThreads = direct.threads.filter(\.isUnread).count
      let engineUnread = direct.unreadThreadCount.map(String.init) ?? "not read"

      print("[probe] inbox state \(describe(state)), threads \(direct.threads.count), unread threads in page \(unreadThreads), engine unread count \(engineUnread), listener \(describe(direct.listener)), session \(describe(session.gateway.session))")

      try? await Task.sleep(for: .seconds(3))
      capture(to: outputURL)
   }

   private static func runEvents(accounts: AccountsStore, captureTo outputURL: URL) async {
      let session = accounts.active
      let direct = session.direct
      let environment = ProcessInfo.processInfo.environment
      let seconds = environment["INSTAGRAMPLUS_EVENTS_SECONDS"].flatMap(Double.init) ?? 20

      session.navigation.route = .messages
      await direct.startListening()
      print("[probe] listener \(describe(direct.listener)) after start, session \(describe(session.gateway.session))")

      let deadline = Date().addingTimeInterval(seconds)
      while Date() < deadline, direct.isListening {
         try? await Task.sleep(for: .milliseconds(500))
      }

      let handledBeforeStop = direct.eventsHandled
      let stateBeforeStop = describe(direct.listener)
      await direct.stopListening()

      print("[probe] events handled \(handledBeforeStop), watermark present \(direct.eventsWatermark != nil), listener \(stateBeforeStop) before stop, \(describe(direct.listener)) after stop, session \(describe(session.gateway.session))")

      if let reason = direct.listenerProblem {
         print("[probe] listener stop reason: \(reason)")
      }

      capture(to: outputURL)
   }

   private static func readComments(accounts: AccountsStore, postPK: String) async {
      let gateway = accounts.active.gateway
      let engine = gateway.client

      print("[probe] reading the first comments page")

      let outcome = await gateway.read("comments") { () async throws(EngineError) in
         try await engine.comments(postPK: postPK, after: nil)
      }

      switch outcome {
         case .success(let page):
            print("[probe] comments state loaded, items \(page.items.count), more pages \(page.hasNextPage), cursor present \(page.endCursor != nil), session \(describe(gateway.session))")

         case .failure(let error):
            print("[probe] comments state failed, \(error), session \(describe(gateway.session))")

         case .halted:
            print("[probe] comments state halted, session \(describe(gateway.session))")
      }
   }

   // Home reads the tray on its own at launch, so this only waits for that read. A reel read
   // sends a visible mark-seen write under the default Behavior, so this refuses to run unless
   // the capability list is set and leaves story reels out, and it never opens the viewer.
   private static func captureStoriesTray(accounts: AccountsStore, to outputURL: URL) async {
      let listed = ProcessInfo.processInfo.environment["INSTAGRAMPLUS_ENGINE_CAPABILITIES"]
      let reelCapability = PythonEngine.Capability.storyReels.rawValue
      let mayOpenReel = listed.map { $0.split(separator: ",").contains { $0.trimmingCharacters(in: .whitespaces) == reelCapability } } ?? true

      guard !mayOpenReel else {
         print("[probe] refusing, story reels are allowed to reach Instagram and a reel read marks a story seen")
         return
      }

      let session = accounts.active
      let home = session.home

      print("[probe] opening Home for the stories tray")
      session.navigation.route = .home

      let state = await settle(session) { home.storiesState }
      let unknownSeenState = home.stories.filter { !home.isSeenStateKnown($0.id) }.count
      let viewerOpened = session.navigation.presentedStoryAuthorID != nil

      print("[probe] stories tray state \(describe(state)), rows \(home.stories.count), rows without a seen state \(unknownSeenState), viewer opened \(viewerOpened), session \(describe(session.gateway.session))")

      try? await Task.sleep(for: .seconds(3))
      capture(to: outputURL)
   }

   // Reads the own profile's posts grid and highlights as the page does, then the reels, tagged
   // and saved tabs one after another, and captures the page on its posts tab.
   private static func captureProfileTabs(accounts: AccountsStore, to outputURL: URL) async {
      let session = accounts.active
      let profiles = session.profiles
      let viewerID = session.gateway.viewerID

      print("[probe] opening the own profile, viewer id present: \(!viewerID.isEmpty)")
      session.navigation.openProfile(viewerID)

      let profileState = await settle(session) { profiles.profileStates[viewerID] ?? .idle }
      let postsState = await settle(session) { profiles.tileState(for: viewerID, tab: .posts) }
      let highlightState = await settle(session) { profiles.highlightState(for: viewerID) }
      let highlightCount = profiles.highlights[viewerID]?.count ?? 0

      print("[probe] profile state \(describe(profileState)), posts state \(describe(postsState)), highlights state \(describe(highlightState)), posts \(profiles.tiles(for: viewerID, tab: .posts).count), more posts \(profiles.hasMoreTiles(for: viewerID, tab: .posts)), highlights \(highlightCount)")

      for tab in [ProfileTab.reels, .tagged, .saved] {
         guard session.gateway.session == .active else {
            break
         }

         await profiles.loadTiles(viewerID, tab: tab)
         let tiles = profiles.tiles(for: viewerID, tab: tab)
         let withoutCommentCount = tiles.filter { !profiles.isCommentCountKnown($0.id) }.count

         print("[probe] \(tab.rawValue) state \(describe(profiles.tileState(for: viewerID, tab: tab))), tiles \(tiles.count), without a comment count \(withoutCommentCount)")
      }

      print("[probe] session \(describe(session.gateway.session))")

      try? await Task.sleep(for: .seconds(3))
      capture(to: outputURL)
   }

   // Searches one fixed term, IG_E2_SEARCH_QUERY when set and the literal "instagram"
   // otherwise, as the engine's own search probes do. The term is never printed. Opening Search
   // also reads the recent searches and the first explore page.
   private static func captureSearch(accounts: AccountsStore, to outputURL: URL) async {
      let session = accounts.active
      let search = session.search
      let query = ProcessInfo.processInfo.environment["IG_E2_SEARCH_QUERY"].flatMap { $0.isEmpty ? nil : $0 } ?? "instagram"

      print("[probe] opening Search")
      session.navigation.route = .search

      let recentState = await settle(session) { search.recentState }
      let exploreState = await settle(session) { search.exploreState }

      session.navigation.searchQuery = query

      let resultsState = await settle(session) { search.resultsState }

      // The tag and place searches follow the account search.
      try? await Task.sleep(for: .seconds(1))

      print("[probe] search state \(describe(resultsState)), accounts \(search.results.count), tag search \(describe(search.tagSearchState)), place search \(describe(search.placeSearchState))")
      print("[probe] recent state \(describe(recentState)), recent accounts \(search.recent.count), recent keywords \(search.recentKeywords.count), recent without details \(search.recentWithoutDetailsCount)")
      print("[probe] explore state \(describe(exploreState)), tiles \(search.exploreTiles.count), more pages \(search.hasMoreExplore), session \(describe(session.gateway.session))")

      try? await Task.sleep(for: .seconds(3))
      capture(to: outputURL)
   }

   // Opens Reels, waits for the first page, then reads one more page through the cursor the
   // first page returned, and captures the page.
   private static func captureReels(accounts: AccountsStore, to outputURL: URL) async {
      let session = accounts.active
      let reels = session.reels

      print("[probe] opening Reels")
      session.navigation.route = .reels

      let state = await settle(session) { reels.state }
      let firstPageCount = reels.reels.count
      let hadMore = reels.hasMoreReels

      if hadMore, session.gateway.session == .active {
         await reels.loadMore()
      }

      let withoutSaveState = reels.reels.filter { !reels.isSaveStateKnown($0.id) }.count

      print("[probe] reels state \(describe(state)), first page \(firstPageCount), more after first \(hadMore), after second page \(reels.reels.count), without a saved state \(withoutSaveState), session \(describe(session.gateway.session))")

      try? await Task.sleep(for: .seconds(3))
      capture(to: outputURL)
   }

   // Opens Notifications, which reads the activity feed and then the follow requests. Home
   // reads the rail's suggestions at launch. Reading the feed marks nothing seen.
   private static func captureActivity(accounts: AccountsStore, to outputURL: URL) async {
      let session = accounts.active
      let activity = session.activity
      let home = session.home

      print("[probe] opening Notifications")
      session.navigation.route = .notifications

      let state = await settle(session) { activity.state }

      // The follow requests read runs after the feed read settles.
      try? await Task.sleep(for: .seconds(8))

      let suggestionsState = await settle(session) { home.suggestionsState }
      let actorlessRows = activity.untypedItems.filter { $0.actor == nil }.count

      print("[probe] activity state \(describe(state)), typed rows \(activity.items.count), untyped rows \(activity.untypedItems.count), untyped rows without an account \(actorlessRows), engine reports unseen \(activity.engineReportsUnseen.map(String.init) ?? "not read")")
      print("[probe] follow requests \(activity.followRequests.count), suggestions state \(describe(suggestionsState)), suggestions \(home.suggestions.count), session \(describe(session.gateway.session))")

      try? await Task.sleep(for: .seconds(3))
      capture(to: outputURL)
   }

   // Opens one post the way the overlay does, which reads it through media.page with its first
   // comments and the author's grid, then reads its likers once as the likes sheet does.
   private static func capturePostDetail(accounts: AccountsStore, to outputURL: URL) async {
      let session = accounts.active
      let home = session.home
      let listedCode = ProcessInfo.processInfo.environment["INSTAGRAMPLUS_PROBE_POST_CODE"].flatMap { $0.isEmpty ? nil : $0 }

      // On the dummy a seeded post off the feed's first page stands in, so the overlay reads it
      // cold through media.page as it does on the real engine.
      let dummyCode = await session.gateway.dummy?.world.posts["p.spice"]?.code

      guard let code = listedCode ?? dummyCode else {
         print("[probe] refusing, INSTAGRAMPLUS_PROBE_POST_CODE is not set")
         return
      }

      print("[probe] engine \(session.gateway.dummy == nil ? "real" : "dummy"), post already held \(home.post(code: code) != nil)")

      print("[probe] opening the post")
      session.navigation.showPost(code: code)

      let detailState = await settle(session) { home.detailState(code: code) }

      guard let post = home.post(code: code) else {
         print("[probe] post state \(describe(detailState)), post found false, posts held \(home.heldPostCount), session \(describe(session.gateway.session))")
         return
      }

      let commentCount = home.comments(for: post.id).count
      let authorGridCount = home.authorGrid(of: post.author.id).count

      print("[probe] post state \(describe(detailState)), code as read matches the one asked \(post.code == code), comments \(commentCount), more comments \(home.hasMoreComments(for: post.id)), author grid \(authorGridCount), audio present \(post.audioID != nil), like state known \(post.isLiked != nil)")

      if session.gateway.session == .active {
         await home.loadLikers(postPK: post.id)
      }

      print("[probe] likers state \(describe(home.likerState(of: post.id))), likers \(home.likers(of: post.id).count), session \(describe(session.gateway.session))")

      try? await Task.sleep(for: .seconds(3))
      capture(to: outputURL)
   }

   // Opens the own profile on its saved tab and reads the collections, then the mutual followers
   // and similar accounts of INSTAGRAMPLUS_PROBE_USER_ID, or of the viewer when it is unset.
   private static func captureProfileExtras(accounts: AccountsStore, to outputURL: URL) async {
      let session = accounts.active
      let profiles = session.profiles
      let viewerID = session.gateway.viewerID
      let targetID = ProcessInfo.processInfo.environment["INSTAGRAMPLUS_PROBE_USER_ID"].flatMap { $0.isEmpty ? nil : $0 } ?? viewerID

      print("[probe] opening the own profile, viewer id present: \(!viewerID.isEmpty), target is viewer: \(targetID == viewerID)")
      session.navigation.openProfile(viewerID)

      let profileState = await settle(session) { profiles.profileStates[viewerID] ?? .idle }

      // The gateway halts every read after a checkpoint, so a stop partway sends nothing more.
      await profiles.loadCollections()
      await profiles.loadMutualFollowers(targetID)
      await profiles.loadSimilarAccounts(targetID)

      let mutualCount = profiles.mutualFollowers[targetID]?.count ?? 0
      let similarCount = profiles.similarAccounts[targetID]?.count ?? 0
      let countedCollections = profiles.collections.filter { $0.mediaCount != nil }.count

      print("[probe] profile state \(describe(profileState)), collections state \(describe(profiles.collectionsState)), collections \(profiles.collections.count), with a count \(countedCollections), more \(profiles.hasMoreCollections)")
      print("[probe] mutual state \(describe(profiles.mutualFollowerState(for: targetID))), mutual \(mutualCount), more \(profiles.mutualFollowersHaveMore.contains(targetID)), similar state \(describe(profiles.similarAccountState(for: targetID))), similar \(similarCount), session \(describe(session.gateway.session))")

      try? await Task.sleep(for: .seconds(3))
      capture(to: outputURL)
   }

   private static func captureProfile(accounts: AccountsStore, to outputURL: URL) async {
      let session = accounts.active
      let viewerID = session.gateway.viewerID

      print("[probe] opening the own profile, viewer id present: \(!viewerID.isEmpty)")
      session.navigation.openProfile(viewerID)

      let state = await settle(session) { session.profiles.profileStates[viewerID] ?? .idle }
      print("[probe] profile state \(describe(state)), session \(describe(session.gateway.session))")

      // Lets the avatar and the header lay out before the capture.
      try? await Task.sleep(for: .seconds(3))
      capture(to: outputURL)
   }

   private static func settle(_ session: AccountSession, _ currentState: () -> LoadState) async -> LoadState {
      let deadline = Date().addingTimeInterval(90)
      var state = currentState()

      while Date() < deadline {
         state = currentState()
         let hasSettled = state == .loaded || state == .notFound || state.isFailure
         let sessionStopped = session.gateway.session != .active

         if hasSettled || sessionStopped {
            break
         }

         try? await Task.sleep(for: .milliseconds(250))
      }

      return state
   }

   private static func describe(_ state: LoadState) -> String {
      switch state {
         case .idle: "idle"
         case .loading: "loading"
         case .loaded: "loaded"
         case .notFound: "notFound"
         case .failed: "failed"
      }
   }

   private static func describe(_ listener: DirectStore.ListenerState) -> String {
      switch listener {
         case .idle: "idle"
         case .listening: "listening"
         case .stopped: "stopped"
      }
   }

   private static func describe(_ session: SessionState) -> String {
      switch session {
         case .active: "active"
         case .checkpoint: "checkpoint"
         case .revoked: "revoked"
         case .signedOut: "signedOut"
      }
   }

   private static func capture(to fileURL: URL) {
      guard let contentView = NSApp.windows.first(where: { $0.isVisible && $0.sheetParent == nil })?.contentView else {
         print("[probe] no visible window")
         return
      }

      guard let bitmap = contentView.bitmapImageRepForCachingDisplay(in: contentView.bounds) else {
         print("[probe] could not allocate a bitmap")
         return
      }

      contentView.cacheDisplay(in: contentView.bounds, to: bitmap)

      guard let pngData = bitmap.representation(using: .png, properties: [:]) else {
         print("[probe] could not encode the capture")
         return
      }

      do {
         try pngData.write(to: fileURL)
         print("[probe] wrote \(fileURL.lastPathComponent) \(bitmap.pixelsWide)x\(bitmap.pixelsHigh)")
      } catch {
         print("[probe] capture write failed")
      }
   }
}

private extension LoadState {
   var isFailure: Bool {
      if case .failed = self {
         return true
      }

      return false
   }
}
#endif
