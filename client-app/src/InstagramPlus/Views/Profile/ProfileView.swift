import SwiftUI

struct ProfileView: View {
   @Environment(ProfileStore.self) private var profiles
   @Environment(DirectStore.self) private var direct
   @Environment(NavigationStore.self) private var navigation

   let accountID: Account.ID

   @State private var tab = ProfileTab.posts
   @State private var presentedList: FollowListKind?

   var body: some View {
      Group {
         if let details = profiles.details(for: accountID) {
            ScrollView {
               VStack(spacing: 0) {
                  header(details)

                  if showsHighlights(details) {
                     highlights(profiles.highlights[accountID] ?? [])
                        .padding(.top, 40)
                  }

                  content(details)
                     .padding(.top, 44)
               }
               .frame(maxWidth: 935)
               .padding(.horizontal, 40)
               .padding(.vertical, 40)
               .frame(maxWidth: .infinity)
            }
         } else {
            LoadStateContainer(state: profiles.state(for: accountID), loadingLabel: "Loading profile", notFoundTitle: "Profile unavailable", retry: reload) {
               EmptyView()
            }
         }
      }
      .task {
         await profiles.load(accountID)
      }
      .sheet(item: $presentedList) { kind in
         FollowListSheet(kind: kind, accountID: accountID)
      }
   }

   private func reload() {
      Task { await profiles.load(accountID) }
   }

   private func header(_ details: ProfileDetails) -> some View {
      let account = details.account
      let isViewer = profiles.isViewer(account.id)
      let canOpenLists = !isLocked(details)

      return HStack(alignment: .top, spacing: 72) {
         RingedAvatar(account: account, diameter: 150, style: isViewer ? .soft : .solid, showsRing: !isViewer)
            .padding(.leading, 40)

         VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 10) {
               Text(account.username)
                  .font(.system(size: 20))
                  .foregroundStyle(Palette.textPrimary)

               if account.isVerified {
                  VerifiedBadge(size: 16)
               }

               actionButtons(details, isViewer: isViewer)
                  .padding(.leading, 12)
            }

            HStack(spacing: 36) {
               stat(details.stats.postCount, "posts")

               Button {
                  presentedList = .followers
               } label: {
                  stat(details.stats.followerCount, "followers")
               }
               .buttonStyle(.plain)
               .disabled(!canOpenLists)

               Button {
                  presentedList = .following
               } label: {
                  stat(details.stats.followingCount, "following")
               }
               .buttonStyle(.plain)
               .disabled(!canOpenLists)
            }

            VStack(alignment: .leading, spacing: 4) {
               Text(account.displayName)
                  .font(.system(size: 14, weight: .semibold))

               if let category = details.category {
                  Text(category)
                     .font(.system(size: 14))
                     .foregroundStyle(Palette.textSecondary)
               }

               if !details.bio.isEmpty {
                  Text(details.bio)
                     .font(.system(size: 14))
                     .fixedSize(horizontal: false, vertical: true)
               }

               if let website = details.website {
                  Text(website)
                     .font(.system(size: 14, weight: .semibold))
                     .foregroundStyle(Palette.link)
               }

               if details.followsViewer, !isViewer {
                  Text("Follows you")
                     .font(.system(size: 12, weight: .medium))
                     .foregroundStyle(Palette.textSecondary)
                     .padding(.horizontal, 8)
                     .padding(.vertical, 3)
                     .background(Palette.raised, in: RoundedRectangle(cornerRadius: 5))
                     .padding(.top, 6)
               }
            }
            .foregroundStyle(Palette.textPrimary)
         }

         Spacer(minLength: 0)
      }
   }

   @ViewBuilder
   private func actionButtons(_ details: ProfileDetails, isViewer: Bool) -> some View {
      if isViewer {
         PrimaryButton(title: "Edit profile", isProminent: false) {}
            .help("Editing a profile is not in the engine yet")

         PrimaryButton(title: "View archive", isProminent: false) {}
            .help("The archive is not in the engine yet")

         Button {
            navigation.route = .settings
         } label: {
            Image(systemName: "gearshape")
               .font(.system(size: 18))
               .foregroundStyle(Palette.textPrimary)
         }
         .buttonStyle(.plain)
         .accessibilityLabel("Settings")
      } else {
         let isFollowing = details.isFollowing
         let isRequested = details.hasRequestedFollow
         let isPending = profiles.isPending(details.account.id)
         let title = isFollowing ? "Following" : (isRequested ? "Requested" : "Follow")

         PrimaryButton(title: title, isProminent: !isFollowing && !isRequested) {
            Task { await profiles.toggleFollow(details.account.id) }
         }
         .disabled(isPending)
         .opacity(isPending ? 0.6 : 1)

         PrimaryButton(title: "Message", isProminent: false) {
            Task {
               let didOpen = await direct.openThread(with: details.account)

               if didOpen {
                  navigation.route = .messages
               }
            }
         }
      }
   }

   private func stat(_ value: Int, _ label: String) -> some View {
      Text("\(Text(CompactCount.format(value)).fontWeight(.semibold)) \(label)")
         .font(.system(size: 15))
         .foregroundStyle(Palette.textPrimary)
   }

   private func highlights(_ highlights: [Highlight]) -> some View {
      HStack(spacing: 36) {
         ForEach(highlights) { highlight in
            VStack(spacing: 10) {
               MediaView(seed: highlight.id, cornerRadius: 40)
                  .frame(width: 70, height: 70)
                  .padding(4)
                  .overlay(Circle().strokeBorder(Palette.hairline, lineWidth: 1))

               Text(highlight.title)
                  .font(.system(size: 12, weight: .semibold))
                  .foregroundStyle(Palette.textPrimary)
            }
            .help("Viewing highlights is not built yet")
         }

         Spacer(minLength: 0)
      }
      .padding(.leading, 40)
   }

   private func isLocked(_ details: ProfileDetails) -> Bool {
      let isViewer = profiles.isViewer(details.account.id)
      return details.isPrivate && !isViewer && !details.isFollowing
   }

   private func showsHighlights(_ details: ProfileDetails) -> Bool {
      let hasHighlights = !(profiles.highlights[accountID] ?? []).isEmpty
      return hasHighlights && !isLocked(details)
   }

   @ViewBuilder
   private func content(_ details: ProfileDetails) -> some View {
      let isViewer = profiles.isViewer(details.account.id)

      if isLocked(details) {
         VStack(spacing: 0) {
            Hairline()

            EmptyStateView(
               symbolName: "lock",
               title: "This account is private",
               message: "Follow this account to see their photos and videos."
            )
            .frame(height: 320)
         }
      } else {
         let tabs = ProfileTab.allCases.filter { $0 != .saved || isViewer }

         VStack(spacing: 0) {
            HStack(spacing: 60) {
               ForEach(tabs) { option in
                  TabButton(tab: option, isSelected: option == tab) {
                     tab = option
                  }
               }
            }
            .frame(maxWidth: .infinity)
            .overlay(alignment: .top) { Hairline() }

            let tiles = profiles.tiles(for: accountID, tab: tab)

            LoadStateContainer(state: profiles.tileState(for: accountID, tab: tab), retry: loadTab) {
               if tiles.isEmpty {
                  EmptyStateView(symbolName: tab.symbolName, title: "No \(tab.title.lowercased()) yet", message: emptyMessage(for: tab, isViewer: isViewer))
                     .frame(height: 320)
               } else {
                  TileGrid(tiles: tiles, isTall: tab == .reels)
               }
            }
         }
         .task(id: tab) {
            let hasLoaded = profiles.tileState(for: accountID, tab: tab).hasLoaded

            if !hasLoaded {
               await profiles.loadTiles(accountID, tab: tab)
            }
         }
      }
   }

   private func loadTab() {
      Task { await profiles.loadTiles(accountID, tab: tab) }
   }

   private func emptyMessage(for tab: ProfileTab, isViewer: Bool) -> String {
      switch tab {
         case .posts: isViewer ? "Share your first photo from the Create page." : "When they share photos, they will appear here."
         case .reels: "Reels shared here will appear on the profile."
         case .saved: "Save photos and videos that you want to see again."
         case .tagged: "Photos and videos this account is tagged in will appear here."
      }
   }
}

private struct TabButton: View {
   let tab: ProfileTab
   let isSelected: Bool
   let action: () -> Void

   var body: some View {
      Button(action: action) {
         HStack(spacing: 6) {
            Image(systemName: tab.symbolName)
               .font(.system(size: 11))

            Text(tab.title.uppercased())
               .font(.system(size: 12, weight: .semibold))
               .tracking(1)
         }
         .foregroundStyle(isSelected ? Palette.textPrimary : Palette.textSecondary)
         .frame(height: 52)
         .overlay(alignment: .top) {
            if isSelected {
               Rectangle()
                  .fill(Palette.textPrimary)
                  .frame(height: 1)
            }
         }
         .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
   }
}

private struct FollowListSheet: View {
   @Environment(ProfileStore.self) private var profiles
   @Environment(NavigationStore.self) private var navigation
   @Environment(\.dismiss) private var dismiss

   let kind: FollowListKind
   let accountID: Account.ID

   @State private var state = LoadState.idle
   @State private var accounts: [Account] = []

   var body: some View {
      VStack(spacing: 0) {
         HStack {
            Text(kind.title)
               .font(.system(size: 16, weight: .semibold))

            Spacer()

            Button("Done") { dismiss() }
               .keyboardShortcut(.cancelAction)
         }
         .padding(16)

         Hairline()

         LoadStateContainer(state: state, loadingLabel: "Loading \(kind.title.lowercased())", retry: { Task { await load() } }) {
            ScrollView {
               VStack(spacing: 2) {
                  ForEach(accounts) { account in
                     HStack(spacing: 12) {
                        Avatar(account: account, diameter: 40)

                        VStack(alignment: .leading, spacing: 2) {
                           Text(account.username)
                              .font(.system(size: 13, weight: .semibold))

                           Text(account.displayName)
                              .font(.system(size: 12))
                              .foregroundStyle(Palette.textSecondary)
                        }

                        Spacer()

                        if !profiles.isViewer(account.id) {
                           let isFollowing = profiles.isFollowing(account.id)

                           PrimaryButton(title: isFollowing ? "Following" : "Follow", isProminent: !isFollowing) {
                              Task { await profiles.toggleFollow(account.id) }
                           }
                           .disabled(profiles.isPending(account.id))
                        }
                     }
                     .padding(.horizontal, 16)
                     .padding(.vertical, 8)
                     .contentShape(Rectangle())
                     .onTapGesture {
                        dismiss()
                        navigation.openProfile(account.id)
                     }
                  }
               }
               .padding(.vertical, 8)
            }
         }
      }
      .frame(width: 400, height: 480)
      .task { await load() }
   }

   private func load() async {
      state = .loading

      switch await profiles.followList(kind, of: accountID) {
         case .success(let loaded):
            accounts = loaded
            state = .loaded

         case .failure(.notFound):
            state = .notFound

         case .failure(let error):
            state = .failed(HomeStore.describe(error))

         case .halted:
            state = .idle
      }
   }
}
