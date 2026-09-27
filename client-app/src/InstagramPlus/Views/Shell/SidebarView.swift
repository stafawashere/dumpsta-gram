import SwiftUI

struct SidebarView: View {
   @Environment(NavigationStore.self) private var navigation
   @Environment(ProfileStore.self) private var profiles
   @Environment(AccountsStore.self) private var accounts
   @Environment(DirectStore.self) private var direct
   @Environment(ActivityStore.self) private var activity

   var body: some View {
      VStack(alignment: .leading, spacing: 0) {
         Button {
            navigation.route = .home
         } label: {
            BrandMark()
         }
         .buttonStyle(.plain)
         .padding(.top, 44)
         .padding(.horizontal, 32)

         profileSummary
            .padding(.top, 36)

         Hairline()
            .padding(.top, 28)

         VStack(spacing: 0) {
            ForEach(SidebarDestination.allCases) { destination in
               SidebarRow(
                  title: destination.title,
                  symbolName: destination.symbolName,
                  selectedSymbolName: destination.selectedSymbolName,
                  isSelected: navigation.sidebarSelection == destination,
                  badgeCount: badgeCount(for: destination),
                  showsDot: destination == .notifications && activity.hasUnread
               ) {
                  navigation.open(destination)
               }
            }
         }
         .padding(.top, 20)

         Hairline()
            .padding(.horizontal, 32)
            .padding(.vertical, 12)

         SidebarRow(
            title: "Log out",
            symbolName: "rectangle.portrait.and.arrow.right",
            selectedSymbolName: "rectangle.portrait.and.arrow.right",
            isSelected: false,
            badgeCount: 0,
            showsDot: false,
            mirrorsIcon: true
         ) {
            navigation.isConfirmingLogOut = true
         }

         Spacer(minLength: 0)
      }
      .frame(maxHeight: .infinity, alignment: .top)
      .background(Palette.panel)
   }

   private func badgeCount(for destination: SidebarDestination) -> Int {
      destination == .messages ? direct.unreadCount : 0
   }

   private var profileSummary: some View {
      let viewer = profiles.viewerAccount
      let stats = profiles.viewer?.stats ?? AccountStats(postCount: 0, followerCount: 0, followingCount: 0)
      let isOnOwnProfile = navigation.route == .profile(viewer.id)

      return VStack(spacing: 0) {
         Button {
            navigation.openProfile(viewer.id)
         } label: {
            VStack(spacing: 0) {
               RingedAvatar(account: viewer, diameter: 78, style: .soft)

               Text(viewer.displayName)
                  .font(.system(size: 15, weight: .semibold))
                  .foregroundStyle(isOnOwnProfile ? Palette.accent : Palette.textPrimary)
                  .padding(.top, 14)

               Text(viewer.username)
                  .font(.system(size: 12))
                  .foregroundStyle(Palette.textSecondary)
                  .padding(.top, 3)
            }
            .contentShape(Rectangle())
         }
         .buttonStyle(.plain)

         AccountSwitcher()
            .padding(.top, 6)

         HStack(spacing: 0) {
            ProfileStat(value: stats.postCount, label: "Posts")
            ProfileStat(value: stats.followerCount, label: "Followers")
            ProfileStat(value: stats.followingCount, label: "Following")
         }
         .padding(.top, 24)
         .padding(.horizontal, 12)
      }
      .frame(maxWidth: .infinity)
   }
}

private struct ProfileStat: View {
   let value: Int
   let label: String

   var body: some View {
      VStack(spacing: 5) {
         Text(CompactCount.format(value))
            .font(.system(size: 14, weight: .semibold))
            .foregroundStyle(Palette.textPrimary)

         Text(label.uppercased())
            .font(.system(size: 9, weight: .medium))
            .tracking(1)
            .foregroundStyle(Palette.textSecondary)
      }
      .frame(maxWidth: .infinity)
      .accessibilityElement(children: .combine)
   }
}

private struct SidebarRow: View {
   let title: String
   let symbolName: String
   let selectedSymbolName: String
   let isSelected: Bool
   let badgeCount: Int
   let showsDot: Bool
   var mirrorsIcon = false
   let action: () -> Void

   @State private var isHovered = false

   var body: some View {
      let foreground = isSelected ? Palette.accent : Palette.textPrimary.opacity(0.75)
      let hasBadge = badgeCount > 0
      let showsHoverFill = isHovered && !isSelected

      Button(action: action) {
         HStack(spacing: 16) {
            Image(systemName: isSelected ? selectedSymbolName : symbolName)
               .font(.system(size: 16))
               .scaleEffect(x: mirrorsIcon ? -1 : 1)
               .frame(width: 20)
               .overlay(alignment: .bottomTrailing) {
                  if hasBadge {
                     Text(String(badgeCount))
                        .font(.system(size: 9, weight: .bold))
                        .foregroundStyle(.white)
                        .frame(minWidth: 15, minHeight: 15)
                        .background(Palette.badge, in: Circle())
                        .offset(x: 5, y: 6)
                  } else if showsDot {
                     Circle()
                        .fill(Palette.badge)
                        .frame(width: 7, height: 7)
                        .offset(x: 3, y: -12)
                  }
               }

            Text(title)
               .font(.system(size: 15, weight: isSelected ? .semibold : .regular))

            Spacer(minLength: 0)
         }
         .foregroundStyle(foreground)
         .padding(.leading, 34)
         .frame(height: 52)
         .background(showsHoverFill ? Palette.raised : Color.clear)
         .overlay(alignment: .leading) {
            if isSelected {
               Rectangle()
                  .fill(Palette.accent)
                  .frame(width: 3)
            }
         }
         .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
      .onHover { isHovered = $0 }
   }
}


private struct AccountSwitcher: View {
   @Environment(AccountsStore.self) private var accounts

   var body: some View {
      Menu {
         ForEach(accounts.sessions) { session in
            Button {
               Task { await accounts.switchTo(session.id) }
            } label: {
               let isActive = session.id == accounts.activeID
               Text(isActive ? "\(session.profiles.viewerAccount.username), current" : session.profiles.viewerAccount.username)
            }
         }

         if accounts.canAddAccount {
            Divider()

            Button("Add account") {
               Task { await accounts.addAccount() }
            }
         }
      } label: {
         HStack(spacing: 4) {
            Text(accounts.sessions.count > 1 ? "Switch account" : "Add account")
            Image(systemName: "chevron.down")
               .font(.system(size: 8, weight: .bold))
         }
         .font(.system(size: 11, weight: .medium))
         .foregroundStyle(Palette.link)
      }
      .menuStyle(.borderlessButton)
      .menuIndicator(.hidden)
      .fixedSize()
   }
}