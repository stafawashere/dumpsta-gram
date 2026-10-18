import AppKit
import SwiftUI

struct ProfileView: View {
   @Environment(ProfileStore.self) private var profiles
   @Environment(DirectStore.self) private var direct
   @Environment(NavigationStore.self) private var navigation

   let accountID: Account.ID

   @State private var tab = ProfileTab.posts
   @State private var presentedList: FollowListKind?
   @State private var isShowingSimilar = false

   var body: some View {
      Group {
         if let details = profiles.details(for: accountID) {
            ScrollView {
               VStack(spacing: 0) {
                  header(details)

                  if isShowingSimilar, !profiles.isViewer(accountID) {
                     similarAccountsRow
                        .padding(.top, 32)
                  }

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

               if details.followsViewer == true, !isViewer {
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

            if !isViewer, !isLocked(details) {
               mutualFollowersLine(for: account.id)
            }
         }

         Spacer(minLength: 0)
      }
   }

   @ViewBuilder
   private func actionButtons(_ details: ProfileDetails, isViewer: Bool) -> some View {
      if isViewer {
         PrimaryButton(title: "Edit profile", isProminent: false) {
            navigation.isEditingProfile = true
         }

         PrimaryButton(title: "View archive", isProminent: false) {
            navigation.route = .archive
         }

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
         let isFollowing = details.isFollowing == true
         let isRequested = details.hasRequestedFollow == true
         let isPending = profiles.isPending(details.account.id)
         let isRelationshipKnown = profiles.isRelationshipKnown(details.account.id)
         let isBlocking = details.isBlocking == true
         let title = isFollowing ? "Following" : (isRequested ? "Requested" : "Follow")

         if !isBlocking {
            PrimaryButton(title: title, isProminent: !isFollowing && !isRequested) {
               Task { await profiles.toggleFollow(details.account.id) }
            }
            .disabled(isPending || !isRelationshipKnown)
            .opacity(isPending || !isRelationshipKnown ? 0.6 : 1)
            .help(isRelationshipKnown ? "" : "Instagram+ could not read whether you follow this account")
         }

         if !isBlocking {
            PrimaryButton(title: "Message", isProminent: false) {
               Task {
                  let didOpen = await direct.openThread(with: details.account)

                  if didOpen {
                     navigation.route = .messages
                  }
               }
            }
         }

         Button {
            isShowingSimilar.toggle()

            if isShowingSimilar {
               Task { await profiles.loadSimilarAccounts(details.account.id) }
            }
         } label: {
            Image(systemName: isShowingSimilar ? "person.2.fill" : "person.2")
               .font(.system(size: 14))
               .foregroundStyle(Palette.textPrimary)
         }
         .buttonStyle(.plain)
         .help("Similar accounts")
         .accessibilityLabel("Similar accounts")

         Menu {
            if isBlocking {
               Button("Unblock") {
                  Task { await profiles.setBlocked(details.account.id, blocked: false) }
               }
            } else {
               Button(details.isCloseFriend == true ? "Remove from close friends" : "Add to close friends") {
                  Task { await profiles.setCloseFriend(details.account.id, included: details.isCloseFriend != true) }
               }
               .disabled(details.isCloseFriend == nil)

               Button(details.isMuting == true ? "Unmute" : "Mute") {
                  Task { await profiles.setMuted(details.account.id, muted: details.isMuting != true) }
               }
               .disabled(details.isMuting == nil)

               // The engine gives no profile address, so none is built here.
               Button("Copy profile link (unavailable)") {}
                  .disabled(true)

               Divider()

               Button("Block", role: .destructive) {
                  Task { await profiles.setBlocked(details.account.id, blocked: true) }
               }
            }
         } label: {
            Image(systemName: "ellipsis")
               .font(.system(size: 16, weight: .bold))
               .foregroundStyle(Palette.textPrimary)
         }
         .menuStyle(.borderlessButton)
         .menuIndicator(.hidden)
         .fixedSize()
         .accessibilityLabel("More options")
      }
   }

   // Mutual followers are read when a person asks, never with the profile.
   @ViewBuilder
   private func mutualFollowersLine(for accountID: Account.ID) -> some View {
      let state = profiles.mutualFollowerState(for: accountID)
      let mutual = profiles.mutualFollowers[accountID] ?? []

      switch state {
         case .idle:
            Button("See followers you know") {
               Task { await profiles.loadMutualFollowers(accountID) }
            }
            .buttonStyle(.plain)
            .font(.system(size: 12, weight: .semibold))
            .foregroundStyle(Palette.textSecondary)

         case .loading:
            Text("Loading followers you know")
               .font(.system(size: 12))
               .foregroundStyle(Palette.textSecondary)

         case .failed(let message):
            Button("Could not load followers you know. \(message) Try again") {
               Task { await profiles.loadMutualFollowers(accountID) }
            }
            .buttonStyle(.plain)
            .font(.system(size: 12))
            .foregroundStyle(Palette.textSecondary)

         case .loaded, .notFound:
            HStack(spacing: 8) {
               HStack(spacing: -6) {
                  ForEach(mutual.prefix(3)) { account in
                     Avatar(account: account, diameter: 20)
                        .overlay(Circle().strokeBorder(Palette.card, lineWidth: 1.5))
                  }
               }

               Text(mutualFollowersText(mutual, hasMore: profiles.mutualFollowersHaveMore.contains(accountID)))
                  .font(.system(size: 12))
                  .foregroundStyle(Palette.textSecondary)
            }
      }
   }

   private func mutualFollowersText(_ mutual: [Account], hasMore: Bool) -> String {
      let names = mutual.prefix(2).map(\.username)

      guard !names.isEmpty else {
         return "No followers you know"
      }

      let shown = names.joined(separator: ", ")
      let remaining = mutual.count - names.count

      if remaining > 0 {
         return "Followed by \(shown) and \(remaining) \(remaining == 1 ? "other" : "others")\(hasMore ? " and more" : "")"
      }

      return "Followed by \(shown)\(hasMore ? " and more" : "")"
   }

   private var similarAccountsRow: some View {
      let state = profiles.similarAccountState(for: accountID)
      let accounts = profiles.similarAccounts[accountID] ?? []

      return VStack(alignment: .leading, spacing: 14) {
         Text("Similar accounts")
            .font(.system(size: 14, weight: .semibold))
            .foregroundStyle(Palette.textPrimary)

         switch state {
            case .idle, .loading:
               LoadingStateView(label: "Loading similar accounts")
                  .frame(height: 120)

            case .failed(let message):
               ErrorStateView(message: message) {
                  Task { await profiles.loadSimilarAccounts(accountID) }
               }

            case .loaded, .notFound:
               if accounts.isEmpty {
                  Text("Instagram suggested no similar accounts.")
                     .font(.system(size: 13))
                     .foregroundStyle(Palette.textSecondary)
               } else {
                  ScrollView(.horizontal, showsIndicators: false) {
                     HStack(spacing: 12) {
                        ForEach(accounts) { account in
                           similarAccountCard(account)
                        }
                     }
                  }
               }
         }
      }
      .padding(.horizontal, 40)
   }

   private func similarAccountCard(_ account: Account) -> some View {
      Button {
         navigation.openProfile(account.id)
      } label: {
         VStack(spacing: 8) {
            Avatar(account: account, diameter: 56)

            VStack(spacing: 2) {
               HStack(spacing: 3) {
                  Text(account.username)
                     .font(.system(size: 12, weight: .semibold))
                     .lineLimit(1)

                  if account.isVerified {
                     VerifiedBadge(size: 10)
                  }
               }

               Text(account.displayName)
                  .font(.system(size: 11))
                  .foregroundStyle(Palette.textSecondary)
                  .lineLimit(1)
            }
         }
         .foregroundStyle(Palette.textPrimary)
         .frame(width: 128, height: 128)
         .background(Palette.card, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
         .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Palette.hairline))
      }
      .buttonStyle(.plain)
   }

   // The viewer's saved collections, read when the saved tab asks for them. The engine gives
   // the first page and says whether more exist.
   @ViewBuilder
   private var collectionsSection: some View {
      switch profiles.collectionsState {
         case .idle:
            Button("Show collections") {
               Task { await profiles.loadCollections() }
            }
            .buttonStyle(.plain)
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(Palette.link)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.top, 16)

         case .loading:
            LoadingStateView(label: "Loading collections")
               .frame(height: 120)

         case .failed(let message):
            ErrorStateView(message: message) {
               Task { await profiles.loadCollections() }
            }

         case .loaded, .notFound:
            VStack(alignment: .leading, spacing: 10) {
               ScrollView(.horizontal, showsIndicators: false) {
                  HStack(spacing: 12) {
                     ForEach(profiles.collections) { collection in
                        collectionCard(collection)
                     }
                  }
               }

               if profiles.hasMoreCollections {
                  Text("There are more collections, but Instagram+ can read only the first page yet.")
                     .font(.system(size: 12))
                     .foregroundStyle(Palette.textSecondary)
               }
            }
            .padding(.top, 16)
      }
   }

   private func collectionCard(_ collection: SavedCollection) -> some View {
      VStack(alignment: .leading, spacing: 6) {
         MediaView(seed: collection.id, url: collection.coverURL, cornerRadius: 10)
            .frame(width: 140, height: 140)

         Text(collection.name)
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(Palette.textPrimary)
            .lineLimit(1)

         Text(collection.mediaCount.map { "\(CompactCount.format($0)) posts" } ?? "Count not given")
            .font(.system(size: 11))
            .foregroundStyle(Palette.textSecondary)
      }
      .frame(width: 140)
      .help(collection.isAllPosts ? "Every post you saved" : "")
   }

   private func stat(_ value: Int, _ label: String) -> some View {
      Text("\(Text(CompactCount.format(value)).fontWeight(.semibold)) \(label)")
         .font(.system(size: 15))
         .foregroundStyle(Palette.textPrimary)
   }

   private func highlights(_ highlights: [Highlight]) -> some View {
      HStack(spacing: 36) {
         ForEach(highlights) { highlight in
            Button {
               guard let owner = profiles.details(for: accountID)?.account else {
                  return
               }

               // The engine gives no item count for a highlight. The viewer counts the items of its reel.
               navigation.presentedHighlight = PresentedHighlight(owner: owner, highlight: highlight, itemCount: 0)
            } label: {
            VStack(spacing: 10) {
               MediaView(seed: highlight.id, cornerRadius: 40)
                  .frame(width: 70, height: 70)
                  .padding(4)
                  .overlay(Circle().strokeBorder(Palette.hairline, lineWidth: 1))

               Text(highlight.title)
                  .font(.system(size: 12, weight: .semibold))
                  .foregroundStyle(Palette.textPrimary)
            }
            }
            .buttonStyle(.plain)
         }

         Spacer(minLength: 0)
      }
      .padding(.leading, 40)
   }

   private func isLocked(_ details: ProfileDetails) -> Bool {
      let isViewer = profiles.isViewer(details.account.id)
      let isPrivateToViewer = details.isPrivate && !isViewer && details.isFollowing != true
      return isPrivateToViewer || details.isBlocking == true
   }

   private func showsHighlights(_ details: ProfileDetails) -> Bool {
      let hasHighlights = !(profiles.highlights[accountID] ?? []).isEmpty
      return hasHighlights && !isLocked(details)
   }

   @ViewBuilder
   private func content(_ details: ProfileDetails) -> some View {
      let isViewer = profiles.isViewer(details.account.id)

      if details.isBlocking == true {
         VStack(spacing: 0) {
            Hairline()

            EmptyStateView(
               symbolName: "hand.raised",
               title: "You blocked this account",
               message: "They can't see your profile or contact you. Unblock them from the menu.",
               actionTitle: "Unblock"
            ) {
               Task { await profiles.setBlocked(details.account.id, blocked: false) }
            }
            .frame(height: 360)
         }
      } else if isLocked(details) {
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

            if tab == .saved {
               collectionsSection
                  .padding(.bottom, 16)
            }

            let tiles = profiles.tiles(for: accountID, tab: tab)

            LoadStateContainer(state: profiles.tileState(for: accountID, tab: tab), retry: loadTab) {
               if tiles.isEmpty {
                  EmptyStateView(symbolName: tab.symbolName, title: "No \(tab.title.lowercased()) yet", message: emptyMessage(for: tab, isViewer: isViewer))
                     .frame(height: 320)
               } else {
                  ProfileTileGrid(tiles: tiles, isTall: tab == .reels)

                  if profiles.hasMoreTiles(for: accountID, tab: tab) {
                     if profiles.canLoadMoreTiles(tab: tab) {
                        LoadingStateView(label: "Loading more")
                           .padding(.vertical, -30)
                           .onAppear {
                              Task { await profiles.loadMoreTiles(accountID, tab: tab) }
                           }
                     } else {
                        Text("There are more, but Instagram+ can read only the first page of this tab yet.")
                           .font(.system(size: 12))
                           .foregroundStyle(Palette.textSecondary)
                           .frame(maxWidth: .infinity)
                           .padding(.vertical, 16)
                     }
                  }
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
   @State private var hasNextPage = false
   @State private var nextCursor: String?
   @State private var isLoadingMore = false

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

                        let canRemoveFollower = kind == .followers && profiles.isViewer(accountID)

                        if canRemoveFollower {
                           PrimaryButton(title: "Remove", isProminent: false) {
                              Task {
                                 if await profiles.removeFollower(account.id) {
                                    accounts.removeAll { $0.id == account.id }
                                 }
                              }
                           }
                        } else if !profiles.isViewer(account.id) {
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

                  if hasNextPage {
                     LoadingStateView(label: "Loading more")
                        .padding(.vertical, -30)
                        .onAppear {
                           Task { await loadMore() }
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
         case .success(let page):
            accounts = page.accounts
            hasNextPage = page.hasNextPage
            nextCursor = page.endCursor
            state = .loaded

         case .failure(.notFound):
            state = .notFound

         case .failure(let error):
            state = .failed(HomeStore.describe(error))

         case .halted:
            state = .idle
      }
   }

   // The cursor goes back to the engine exactly as the last page returned it.
   private func loadMore() async {
      let canLoadMore = hasNextPage && !isLoadingMore

      guard canLoadMore else {
         return
      }

      isLoadingMore = true
      defer { isLoadingMore = false }

      guard case .success(let page) = await profiles.followList(kind, of: accountID, after: nextCursor) else {
         return
      }

      let knownIDs = Set(accounts.map(\.id))
      accounts.append(contentsOf: page.accounts.filter { !knownIDs.contains($0.id) })
      hasNextPage = page.hasNextPage
      nextCursor = page.endCursor
   }
}
