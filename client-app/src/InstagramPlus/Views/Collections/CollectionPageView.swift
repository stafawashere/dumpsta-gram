import SwiftUI

struct CollectionPageView: View {
   enum Kind: Hashable {
      case hashtag(String)
      case place(String)
   }

   @Environment(SearchStore.self) private var search

   let kind: Kind

   @State private var resolvedPlace: Place?
   @State private var placeState = LoadState.idle

   var body: some View {
      ScrollView {
         VStack(alignment: .leading, spacing: 28) {
            header

            LoadStateContainer(state: state, loadingLabel: "Loading posts", retry: reload) {
               let tiles = search.tiles(for: key)

               if tiles.isEmpty {
                  EmptyStateView(symbolName: "photo.on.rectangle", title: "No posts yet", message: "Posts shared here will appear in this grid.")
                     .frame(height: 300)
               } else {
                  VStack(alignment: .leading, spacing: 12) {
                     Text("Top posts")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(Palette.textSecondary)

                     TileGrid(tiles: tiles)
                  }
               }
            }
         }
         .frame(maxWidth: 935)
         .padding(.horizontal, 40)
         .padding(.vertical, 40)
         .frame(maxWidth: .infinity)
      }
      .task { await load() }
   }

   private var key: String {
      switch kind {
         case .hashtag(let name): "tag:" + name
         case .place: "place:" + (resolvedPlace?.id ?? "")
      }
   }

   private var state: LoadState {
      switch kind {
         case .hashtag: search.collectionState(key)
         case .place: resolvedPlace == nil ? placeState : search.collectionState(key)
      }
   }

   private var header: some View {
      HStack(spacing: 24) {
         Image(systemName: kindSymbol)
            .font(.system(size: 44, weight: .light))
            .foregroundStyle(Palette.textPrimary)
            .frame(width: 120, height: 120)
            .overlay(Circle().strokeBorder(Palette.hairline))

         VStack(alignment: .leading, spacing: 8) {
            Text(title)
               .font(.system(size: 24, weight: .semibold))
               .foregroundStyle(Palette.textPrimary)

            if let postCount {
               Text("\(Text(CompactCount.format(postCount)).fontWeight(.semibold)) posts")
                  .font(.system(size: 15))
                  .foregroundStyle(Palette.textPrimary)
            }
         }
      }
   }

   private var kindSymbol: String {
      switch kind {
         case .hashtag: "number"
         case .place: "mappin.and.ellipse"
      }
   }

   private var title: String {
      switch kind {
         case .hashtag(let name): "#" + name
         case .place(let name): name
      }
   }

   private var postCount: Int? {
      switch kind {
         case .hashtag(let name): search.tagResults.first { $0.name == name }?.postCount
         case .place: resolvedPlace?.postCount
      }
   }

   private func reload() {
      Task { await load() }
   }

   private func load() async {
      switch kind {
         case .hashtag(let name):
            await search.loadHashtag(name)

         case .place(let name):
            placeState = .loading

            guard let place = await search.findPlace(named: name) else {
               placeState = .notFound
               return
            }

            resolvedPlace = place
            placeState = .loaded
            await search.loadPlace(place.id)
      }
   }
}

struct ArchiveView: View {
   @Environment(ProfileStore.self) private var profiles

   var body: some View {
      ScrollView {
         VStack(alignment: .leading, spacing: 20) {
            SectionTitle(text: "Stories archive", size: 24)

            Text("Only you can see your archived stories.")
               .font(.system(size: 13))
               .foregroundStyle(Palette.textSecondary)

            LoadStateContainer(state: profiles.archiveState, loadingLabel: "Loading archive", retry: { Task { await profiles.loadArchive() } }) {
               LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 4), count: 4), spacing: 4) {
                  ForEach(Array(profiles.archive.enumerated()), id: \.element.id) { position, tile in
                     MediaView(seed: tile.code, cornerRadius: 4)
                        .aspectRatio(9 / 16, contentMode: .fill)
                        .overlay(alignment: .topLeading) {
                           Text(Date.now.addingTimeInterval(Double(-86_400 * (position * 3 + 1))).formatted(.dateTime.day().month(.abbreviated)))
                              .font(.system(size: 11, weight: .bold))
                              .foregroundStyle(.black)
                              .padding(.horizontal, 6)
                              .padding(.vertical, 3)
                              .background(.white, in: RoundedRectangle(cornerRadius: 4))
                              .padding(8)
                        }
                  }
               }
            }
         }
         .frame(maxWidth: 820)
         .padding(.horizontal, 40)
         .padding(.vertical, 36)
         .frame(maxWidth: .infinity)
      }
      .task { await profiles.loadArchive() }
   }
}

struct RelationshipListView: View {
   @Environment(ProfileStore.self) private var profiles
   @Environment(NavigationStore.self) private var navigation

   let list: RelationshipList

   var body: some View {
      ScrollView {
         VStack(alignment: .leading, spacing: 20) {
            SectionTitle(text: list.title, size: 24)

            Text(explanation)
               .font(.system(size: 13))
               .foregroundStyle(Palette.textSecondary)
               .fixedSize(horizontal: false, vertical: true)

            LoadStateContainer(state: profiles.relationshipsState, loadingLabel: "Loading", retry: { Task { await profiles.loadRelationships() } }) {
               let ids = memberIDs.sorted()

               if ids.isEmpty {
                  EmptyStateView(symbolName: "person.2", title: "Nobody here", message: emptyMessage)
                     .frame(height: 280)
               } else {
                  VStack(spacing: 2) {
                     ForEach(ids, id: \.self) { accountID in
                        row(for: accountID)
                     }
                  }
               }
            }
         }
         .frame(maxWidth: 640)
         .padding(.horizontal, 40)
         .padding(.vertical, 36)
         .frame(maxWidth: .infinity)
      }
      .task { await profiles.loadRelationships() }
   }

   private var memberIDs: Set<Account.ID> {
      switch list {
         case .closeFriends: profiles.closeFriendIDs
         case .blocked: profiles.blockedIDs
         case .muted: profiles.mutedIDs
      }
   }

   private var explanation: String {
      switch list {
         case .closeFriends: "Only these people see stories and notes you share with close friends."
         case .blocked: "Blocked accounts can't find your profile, posts or stories, and aren't told they were blocked."
         case .muted: "You won't see posts from muted accounts in your feed. They aren't told."
      }
   }

   private var emptyMessage: String {
      switch list {
         case .closeFriends: "Add close friends from a profile's menu."
         case .blocked: "You haven't blocked anyone."
         case .muted: "You haven't muted anyone."
      }
   }

   private var actionTitle: String {
      switch list {
         case .closeFriends: "Remove"
         case .blocked: "Unblock"
         case .muted: "Unmute"
      }
   }

   private func row(for accountID: Account.ID) -> some View {
      let account = profiles.account(accountID) ?? Account(id: accountID, username: accountID, displayName: accountID, location: nil)

      return HStack(spacing: 12) {
         Avatar(account: account, diameter: 44)

         VStack(alignment: .leading, spacing: 2) {
            Text(account.username)
               .font(.system(size: 14, weight: .semibold))

            Text(account.displayName)
               .font(.system(size: 12))
               .foregroundStyle(Palette.textSecondary)
         }
         .foregroundStyle(Palette.textPrimary)

         Spacer()

         PrimaryButton(title: actionTitle, isProminent: false) {
            Task {
               switch list {
                  case .closeFriends: await profiles.setCloseFriend(accountID, included: false)
                  case .blocked: await profiles.setBlocked(accountID, blocked: false)
                  case .muted: await profiles.setMuted(accountID, muted: false)
               }
            }
         }
      }
      .padding(.vertical, 8)
      .contentShape(Rectangle())
      .onTapGesture {
         navigation.openProfile(accountID)
      }
   }
}
