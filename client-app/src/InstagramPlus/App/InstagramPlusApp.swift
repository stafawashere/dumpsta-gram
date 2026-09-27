import SwiftUI

@main
struct InstagramPlusApp: App {
   @State private var accounts: AccountsStore
   @AppStorage(Appearance.storageKey) private var appearance = Appearance.system

   init() {
      let storedTiming = UserDefaults.standard.string(forKey: "dummyTiming") ?? ""
      let timing = DummyEngine.Timing(rawValue: storedTiming) ?? .fast
      let accounts = AccountsStore(timing: timing)

      _accounts = State(initialValue: accounts)

      #if DEBUG
      // Started here rather than from a view, because a view's task never runs while the
      // display is asleep and the probe has to work unattended.
      Task { @MainActor in
         await SnapshotProbe.runIfRequested(accounts: accounts)
      }
      #endif
   }

   var body: some Scene {
      WindowGroup("Instagram+") {
         AccountRoot()
            .environment(accounts)
            .preferredColorScheme(appearance.colorScheme)
            .frame(minWidth: 1120, minHeight: 720)
      }
      .windowStyle(.hiddenTitleBar)
      .defaultSize(width: 1320, height: 900)
      .commands {
         CommandMenu("Go") {
            ForEach(SidebarDestination.allCases) { destination in
               Button(destination.title) {
                  accounts.active.navigation.dismissOverlays()
                  accounts.active.navigation.open(destination)
               }
               .keyboardShortcut(destination.shortcutKey, modifiers: .command)
            }

            Divider()

            Button("Profile") {
               accounts.active.navigation.openProfile(accounts.active.gateway.viewerID)
            }
            .keyboardShortcut("0", modifiers: .command)
         }

         CommandGroup(replacing: .appSettings) {
            Button("Settings") {
               accounts.active.navigation.route = .settings
            }
            .keyboardShortcut(",", modifiers: .command)
         }
      }
   }
}

struct AccountRoot: View {
   @Environment(AccountsStore.self) private var accounts

   var body: some View {
      let session = accounts.active

      RootView()
         .environment(session.navigation)
         .environment(session.gateway)
         .environment(session.home)
         .environment(session.direct)
         .environment(session.activity)
         .environment(session.reels)
         .environment(session.search)
         .environment(session.profiles)
         .id(session.id)
   }
}
