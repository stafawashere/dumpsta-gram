import SwiftUI

@main
struct InstagramPlusApp: App {
   @State private var navigation: NavigationStore
   @State private var gateway: EngineGateway
   @State private var home: HomeStore
   @State private var direct: DirectStore
   @State private var activity: ActivityStore
   @State private var reels: ReelsStore
   @State private var search: SearchStore
   @State private var profiles: ProfileStore
   @AppStorage(Appearance.storageKey) private var appearance = Appearance.system

   init() {
      let storedTiming = UserDefaults.standard.string(forKey: "dummyTiming") ?? ""
      let timing = DummyEngine.Timing(rawValue: storedTiming) ?? .fast
      let gateway = EngineGateway(engine: DummyEngine(timing: timing))
      let navigation = NavigationStore()
      let home = HomeStore(gateway: gateway)
      let direct = DirectStore(gateway: gateway)

      _navigation = State(initialValue: navigation)
      _gateway = State(initialValue: gateway)
      _home = State(initialValue: home)
      _direct = State(initialValue: direct)
      _activity = State(initialValue: ActivityStore(gateway: gateway))
      _reels = State(initialValue: ReelsStore(gateway: gateway))
      _search = State(initialValue: SearchStore(gateway: gateway))
      _profiles = State(initialValue: ProfileStore(gateway: gateway))

      #if DEBUG
      // Started here rather than from a view, because a view's task never runs while the
      // display is asleep and the probe has to work unattended.
      let probeStores = (navigation, gateway, home, direct)
      Task { @MainActor in
         await SnapshotProbe.runIfRequested(navigation: probeStores.0, gateway: probeStores.1, home: probeStores.2, direct: probeStores.3)
      }
      #endif
   }

   var body: some Scene {
      WindowGroup("Instagram+") {
         RootView()
            .environment(navigation)
            .environment(gateway)
            .environment(home)
            .environment(direct)
            .environment(activity)
            .environment(reels)
            .environment(search)
            .environment(profiles)
            .preferredColorScheme(appearance.colorScheme)
            .frame(minWidth: 1120, minHeight: 720)
      }
      .windowStyle(.hiddenTitleBar)
      .defaultSize(width: 1320, height: 900)
      .commands {
         CommandMenu("Go") {
            ForEach(SidebarDestination.allCases) { destination in
               Button(destination.title) {
                  navigation.dismissOverlays()
                  navigation.open(destination)
               }
               .keyboardShortcut(destination.shortcutKey, modifiers: .command)
            }

            Divider()

            Button("Profile") {
               navigation.openProfile(gateway.viewerID)
            }
            .keyboardShortcut("0", modifiers: .command)
         }

         CommandGroup(replacing: .appSettings) {
            Button("Settings") {
               navigation.route = .settings
            }
            .keyboardShortcut(",", modifiers: .command)
         }
      }
   }
}
