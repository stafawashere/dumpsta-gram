import SwiftUI

@main
struct InstagramPlusApp: App {
   @State private var accounts: AccountsStore
   @AppStorage(Appearance.storageKey) private var appearance = Appearance.system

   // The engine is picked at launch, see EngineSelection in Bridge/EngineFactory.swift:
   // --engine real|dummy, INSTAGRAMPLUS_ENGINE=real|dummy, or the developer section's choice for
   // the next launch. Real is the default, and --exercise and --snapshot-dir run on the dummy.
   init() {
      let process = ProcessInfo.processInfo
      let storedChoice = UserDefaults.standard.string(forKey: EngineSelection.nextLaunchKey)
      let selection = EngineSelection.resolve(arguments: process.arguments, environment: process.environment, storedChoice: storedChoice)
      let accounts: AccountsStore

      switch selection {
         case .dummy:
            let storedTiming = UserDefaults.standard.string(forKey: "dummyTiming") ?? ""
            let timing = DummyEngine.Timing(rawValue: storedTiming) ?? .fast
            accounts = AccountsStore(timing: timing)

         case .real:
            // Line buffered, so a launch whose output goes to a log file keeps its lines if it is stopped.
            setvbuf(stdout, nil, _IOLBF, 0)
            print("[engine] real engine selected")
            accounts = AccountsStore(source: .real(PythonEngineFactory.launchBlocking(environment: process.environment)))
      }

      _accounts = State(initialValue: accounts)

      #if DEBUG
      // Started here rather than from a view, because a view's task never runs while the
      // display is asleep and the probe has to work unattended.
      if selection == .dummy {
         Task { @MainActor in
            await SnapshotProbe.runIfRequested(accounts: accounts)
         }
      } else {
         Task { @MainActor in
            await RealEngineProbe.runIfRequested(accounts: accounts)
         }
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
      @Bindable var accounts = accounts
      let session = accounts.active

      if let runtimeProblem = accounts.runtimeProblem {
         EngineUnavailableView(problem: runtimeProblem)
      } else {
         RootView()
            .environment(session.navigation)
            .environment(session.gateway)
            .environment(session.home)
            .environment(session.direct)
            .environment(session.activity)
            .environment(session.reels)
            .environment(session.search)
            .environment(session.profiles)
            .sheet(isPresented: $accounts.isAddingAccount) {
               SessionSetupView(isAddingAccount: true)
                  .environment(session.navigation)
                  .environment(session.gateway)
                  .environment(accounts)
                  .frame(width: 560, height: 720)
            }
            .id(session.id)
      }
   }
}
