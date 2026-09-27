import SwiftUI

enum SearchTab: String, CaseIterable, Identifiable {
   case accounts
   case tags
   case places

   var id: String { rawValue }

   var title: String {
      switch self {
         case .accounts: "Accounts"
         case .tags: "Tags"
         case .places: "Places"
      }
   }
}

struct SearchView: View {
   @Environment(NavigationStore.self) private var navigation
   @Environment(SearchStore.self) private var search

   @State private var tab = SearchTab.accounts

   var body: some View {
      let query = navigation.searchQuery
      let isSearching = !query.trimmingCharacters(in: .whitespaces).isEmpty

      ScrollView {
         VStack(alignment: .leading, spacing: 0) {
            if isSearching {
               results(for: query)
            } else {
               recent
               explore
                  .padding(.top, 40)
            }
         }
         .frame(maxWidth: 820)
         .padding(.horizontal, 40)
         .padding(.vertical, 36)
         .frame(maxWidth: .infinity)
      }
      .task(id: query) {
         await search.search(query)
      }
      .onChange(of: search.resultsQuery) {
         let hasNoAccounts = search.results.isEmpty
         let hasTags = !search.tagResults.isEmpty
         let hasPlaces = !search.placeResults.isEmpty

         if hasNoAccounts, hasTags {
            tab = .tags
         } else if hasNoAccounts, hasPlaces {
            tab = .places
         } else {
            tab = .accounts
         }
      }
      .task {
         await search.loadExplore()
      }
   }

   private func results(for query: String) -> some View {
      VStack(alignment: .leading, spacing: 18) {
         HStack {
            SectionTitle(text: "Results for \"\(query)\"")

            Spacer()

            SegmentedPills(options: SearchTab.allCases, selection: $tab) { $0.title }
         }

         LoadStateContainer(state: search.resultsState, loadingLabel: "Searching", retry: { Task { await search.search(query) } }) {
            switch tab {
               case .accounts:
                  if search.results.isEmpty {
                     noResults
                  } else {
                     VStack(spacing: 4) {
                        ForEach(search.results) { account in
                           AccountRow(account: account) {
                              search.remember(account)
                              navigation.openProfile(account.id)
                           }
                        }
                     }
                  }

               case .tags:
                  if search.tagResults.isEmpty {
                     noResults
                  } else {
                     VStack(spacing: 4) {
                        ForEach(search.tagResults) { hashtag in
                           CollectionRow(symbolName: "number", title: "#" + hashtag.name, subtitle: "\(CompactCount.format(hashtag.postCount)) posts") {
                              navigation.route = .hashtag(hashtag.name)
                           }
                        }
                     }
                  }

               case .places:
                  if search.placeResults.isEmpty {
                     noResults
                  } else {
                     VStack(spacing: 4) {
                        ForEach(search.placeResults) { place in
                           CollectionRow(symbolName: "mappin.and.ellipse", title: place.name, subtitle: "\(CompactCount.format(place.postCount)) posts") {
                              navigation.route = .place(id: place.id, name: place.name)
                           }
                        }
                     }
                  }
            }
         }
      }
   }

   private var noResults: some View {
      EmptyStateView(symbolName: "magnifyingglass", title: "No results found", message: "Try a different spelling.")
         .frame(height: 320)
   }

   private var recent: some View {
      VStack(alignment: .leading, spacing: 18) {
         HStack {
            SectionTitle(text: "Recent")

            Spacer()

            if !search.recent.isEmpty {
               Button("Clear all") {
                  search.clearRecent()
               }
               .buttonStyle(.plain)
               .font(.system(size: 13, weight: .semibold))
               .foregroundStyle(Palette.link)
            }
         }

         if search.recent.isEmpty {
            Text("No recent searches.")
               .font(.system(size: 14))
               .foregroundStyle(Palette.textSecondary)
         } else {
            VStack(spacing: 4) {
               ForEach(search.recent) { account in
                  AccountRow(account: account, onRemove: { search.forget(account.id) }) {
                     navigation.openProfile(account.id)
                  }
               }
            }
         }
      }
   }

   private var explore: some View {
      VStack(alignment: .leading, spacing: 18) {
         SectionTitle(text: "Explore")

         LoadStateContainer(state: search.exploreState, loadingLabel: "Loading explore", retry: { Task { await search.loadExplore() } }) {
            TileGrid(tiles: search.exploreTiles)
         }
      }
   }
}

private struct AccountRow: View {
   let account: Account
   var onRemove: (() -> Void)?
   let action: () -> Void

   @State private var isHovered = false

   var body: some View {
      HStack(spacing: 12) {
         Button(action: action) {
            HStack(spacing: 12) {
               Avatar(account: account, diameter: 44)

               VStack(alignment: .leading, spacing: 2) {
                  HStack(spacing: 4) {
                     Text(account.username)
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(Palette.textPrimary)

                     if account.isVerified {
                        VerifiedBadge(size: 11)
                     }
                  }

                  Text(account.displayName)
                     .font(.system(size: 13))
                     .foregroundStyle(Palette.textSecondary)
               }

               Spacer()
            }
            .contentShape(Rectangle())
         }
         .buttonStyle(.plain)

         if let onRemove {
            Button(action: onRemove) {
               Image(systemName: "xmark")
                  .font(.system(size: 12, weight: .semibold))
                  .foregroundStyle(Palette.textSecondary)
                  .frame(width: 28, height: 28)
                  .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Remove \(account.username)")
         }
      }
      .padding(.horizontal, 12)
      .padding(.vertical, 8)
      .background(isHovered ? Palette.raised : Color.clear, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
      .onHover { isHovered = $0 }
   }
}


private struct CollectionRow: View {
   let symbolName: String
   let title: String
   let subtitle: String
   let action: () -> Void

   @State private var isHovered = false

   var body: some View {
      Button(action: action) {
         HStack(spacing: 12) {
            Image(systemName: symbolName)
               .font(.system(size: 18))
               .frame(width: 44, height: 44)
               .overlay(Circle().strokeBorder(Palette.hairline))

            VStack(alignment: .leading, spacing: 2) {
               Text(title)
                  .font(.system(size: 14, weight: .semibold))

               Text(subtitle)
                  .font(.system(size: 13))
                  .foregroundStyle(Palette.textSecondary)
            }

            Spacer()
         }
         .foregroundStyle(Palette.textPrimary)
         .padding(.horizontal, 12)
         .padding(.vertical, 8)
         .background(isHovered ? Palette.raised : Color.clear, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
         .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
      .onHover { isHovered = $0 }
   }
}