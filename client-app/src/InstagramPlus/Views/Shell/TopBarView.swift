import SwiftUI

struct TopBarView: View {
   @Environment(NavigationStore.self) private var navigation

   var body: some View {
      @Bindable var navigation = navigation
      let hasQuery = !navigation.searchQuery.isEmpty

      HStack(spacing: 24) {
         HStack(spacing: 10) {
            Image(systemName: "magnifyingglass")
               .font(.system(size: 13))
               .foregroundStyle(Palette.textSecondary)

            TextField("Search", text: $navigation.searchQuery)
               .textFieldStyle(.plain)
               .font(.system(size: 14))
               .onSubmit { navigation.route = .search }

            if hasQuery {
               Button {
                  navigation.searchQuery = ""
               } label: {
                  Image(systemName: "xmark.circle.fill")
                     .foregroundStyle(Palette.textTertiary)
               }
               .buttonStyle(.plain)
               .accessibilityLabel("Clear search")
            }
         }
         .padding(.horizontal, 18)
         .frame(maxWidth: 420, minHeight: 40)
         .background(Palette.raised, in: Capsule())
         .onChange(of: navigation.searchQuery) { _, newQuery in
            let startedTyping = !newQuery.isEmpty
            let isElsewhere = navigation.route != .search
            let shouldOpenSearch = startedTyping && isElsewhere

            if shouldOpenSearch {
               navigation.route = .search
            }
         }

         Spacer(minLength: 0)

         PendingWritesPill()

         CreatePostButton {
            navigation.route = .create
         }

         if !navigation.showsRightRail {
            HeaderActions()
         }
      }
      .padding(.horizontal, 48)
   }
}

struct CreatePostButton: View {
   let action: () -> Void

   var body: some View {
      Button(action: action) {
         HStack(spacing: 8) {
            Image(systemName: "plus")
               .font(.system(size: 12, weight: .bold))

            Text("Create new post")
               .font(.system(size: 14, weight: .semibold))
         }
         .foregroundStyle(.white)
         .padding(.horizontal, 22)
         .frame(height: 40)
         .background(Palette.createGradient, in: Capsule())
         .shadow(color: Color(hex: 0xE0567A).opacity(0.35), radius: 10, y: 4)
         .contentShape(Capsule())
      }
      .buttonStyle(.plain)
   }
}

struct HeaderActions: View {
   @Environment(NavigationStore.self) private var navigation
   @Environment(EngineGateway.self) private var gateway
   @Environment(DirectStore.self) private var direct
   @Environment(ActivityStore.self) private var activity
   @Environment(\.colorScheme) private var colorScheme
   @AppStorage(Appearance.storageKey) private var appearance = Appearance.system

   var body: some View {
      let isDark = colorScheme == .dark
      let unreadMessagesColor: Color? = direct.unreadCount > 0 ? Palette.accent : nil
      let unreadActivityColor: Color? = activity.hasUnread ? Palette.online : nil

      HStack(spacing: 14) {
         CircleIconButton(symbolName: "paperplane", accessibilityTitle: "Messages", indicatorColor: unreadMessagesColor) {
            navigation.route = .messages
         }

         CircleIconButton(symbolName: "bell", accessibilityTitle: "Notifications", indicatorColor: unreadActivityColor) {
            navigation.route = .notifications
         }

         CircleIconButton(symbolName: isDark ? "sun.max" : "moon", accessibilityTitle: isDark ? "Light mode" : "Dark mode") {
            appearance = Appearance.opposite(of: colorScheme)
         }

         Menu {
            Button("Your profile") {
               navigation.openProfile(gateway.viewerID)
            }

            Button("Settings") {
               navigation.route = .settings
            }

            Divider()

            Button("Log out") {
               navigation.isConfirmingLogOut = true
            }
         } label: {
            Image(systemName: "line.3.horizontal")
               .font(.system(size: 17))
               .foregroundStyle(Palette.textPrimary)
         }
         .menuStyle(.borderlessButton)
         .menuIndicator(.hidden)
         .fixedSize()
         .frame(width: 32, height: 42)
         .accessibilityLabel("More")
      }
   }
}
