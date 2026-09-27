import SwiftUI

struct RootView: View {
   static let headerHeight: CGFloat = 78

   @Environment(NavigationStore.self) private var navigation
   @Environment(EngineGateway.self) private var gateway
   @Environment(HomeStore.self) private var home
   @Environment(ProfileStore.self) private var profiles
   @Environment(DirectStore.self) private var direct

   var body: some View {
      Group {
         switch gateway.session {
            case .active:
               signedInShell

            case .checkpoint(let checkpoint):
               CheckpointView(checkpoint: checkpoint)

            case .revoked:
               SessionRevokedView()

            case .signedOut:
               SessionSetupView()
         }
      }
      .overlay {
         NoticeStack()
      }
      .background(Palette.window)
      .ignoresSafeArea()
   }

   private var signedInShell: some View {
      @Bindable var navigation = navigation

      return HStack(spacing: 0) {
         SidebarView()
            .frame(width: 240)

         Hairline(axis: .vertical)

         VStack(spacing: 0) {
            TopBarView()
               .frame(height: Self.headerHeight)
               .background(Palette.panel)

            Hairline()

            page
               .frame(maxWidth: .infinity, maxHeight: .infinity)
         }
         .background(Palette.canvas)

         if navigation.showsRightRail {
            Hairline(axis: .vertical)

            RightRailView()
               .frame(width: 280)
         }
      }
      .overlay {
         overlays
      }
      .animation(.easeOut(duration: 0.18), value: navigation.isShowingOverlay)
      .task(id: gateway.sessionGeneration) {
         await home.load()
         await profiles.load(gateway.viewerID, includingContent: false)
         await direct.loadInbox()
      }
      .alert("Log out of Instagram+?", isPresented: $navigation.isConfirmingLogOut) {
         Button("Log out", role: .destructive) {
            navigation.dismissOverlays()

            Task {
               await direct.stopListening()
               await gateway.signOut()
            }
         }

         Button("Cancel", role: .cancel) {}
      } message: {
         Text("You will need to connect a browser session again to use the app.")
      }
   }

   @ViewBuilder
   private var page: some View {
      switch navigation.route {
         case .home: HomeFeedView()
         case .reels: ReelsView()
         case .messages: MessagesView()
         case .search: SearchView()
         case .notifications: NotificationsView()
         case .create: CreateView()
         case .settings: SettingsView()
         case .profile(let accountID): ProfileView(accountID: accountID).id(accountID)
      }
   }

   @ViewBuilder
   private var overlays: some View {
      if let authorID = navigation.presentedStoryAuthorID {
         StoryViewer(initialAuthorID: authorID)
            .transition(.opacity)
      } else if let postCode = navigation.presentedPostCode {
         PostDetailView(postCode: postCode)
            .id(postCode)
            .transition(.opacity)
      }
   }
}
