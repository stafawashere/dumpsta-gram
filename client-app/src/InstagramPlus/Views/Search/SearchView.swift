import SwiftUI

enum SearchTab: String, CaseIterable, Identifiable {
   case top
   case accounts
   case posts
   case tags
   case places

   var id: String { rawValue }

   var title: String {
      switch self {
         case .top: "Top"
         case .accounts: "Accounts"
         case .posts: "Posts"
         case .tags: "Tags"
         case .places: "Places"
      }
   }
}

struct SearchView: View {
   @Environment(NavigationStore.self) private var navigation
   @Environment(SearchStore.self) private var search

   @State private var tab = SearchTab.accounts
   @State private var exploreMode = ExploreMode.grid

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
         let keepsChosenTab = tab == .top || tab == .posts

         guard !keepsChosenTab else {
            return
         }

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
         await search.loadRecent()
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
               case .top:
                  topResults(for: query)

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

               case .posts:
                  keywordResults(for: query)

               case .tags:
                  if search.isTagSearchUnavailable() {
                     exactTagResult(for: query)
                  } else if case .failed(let problem) = search.tagSearchState {
                     unavailable(problem)
                  } else if search.tagResults.isEmpty {
                     noResults
                  } else {
                     VStack(spacing: 4) {
                        ForEach(search.tagResults) { hashtag in
                           CollectionRow(symbolName: "number", title: "#" + hashtag.name, subtitle: postCountLabel(hashtag.postCount)) {
                              navigation.route = .hashtag(hashtag.name)
                           }
                        }
                     }
                  }

               case .places:
                  if case .failed(let problem) = search.placeSearchState {
                     unavailable(problem)
                  } else if search.placeResults.isEmpty {
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
         .task(id: "\(tab.rawValue)|\(query)") {
            await loadOnDemand(tab, query: query)
         }
      }
   }

   // Top results, the posts grid for a keyword and the exact tag are read only when their tab
   // is open, after typing pauses, once per query.
   private func loadOnDemand(_ tab: SearchTab, query: String) async {
      try? await Task.sleep(for: .milliseconds(350))

      if Task.isCancelled {
         return
      }

      switch tab {
         case .top:
            await search.loadTop(query)

         case .posts:
            await search.loadKeyword(query)

         case .tags where search.isTagSearchUnavailable():
            await search.loadExactTag(query)

         case .accounts, .tags, .places:
            break
      }
   }

   private func postCountLabel(_ postCount: Int?) -> String {
      postCount.map { "\(CompactCount.format($0)) posts" } ?? "Post count not given"
   }

   @ViewBuilder
   private func topResults(for query: String) -> some View {
      LoadStateContainer(state: search.topState, loadingLabel: "Loading top results", retry: { Task { await search.loadTop(query) } }) {
         if search.topRows.isEmpty, search.topWithoutDetailsCount == 0 {
            noResults
         } else {
            VStack(alignment: .leading, spacing: 4) {
               ForEach(search.topRows) { row in
                  switch row.content {
                     case .account(let account):
                        AccountRow(account: account) {
                           search.remember(account)
                           navigation.openProfile(account.id)
                        }

                     case .keyword(let keyword):
                        CollectionRow(symbolName: "magnifyingglass", title: keyword, subtitle: "Posts") {
                           navigation.searchQuery = keyword
                           tab = .posts
                        }
                  }
               }

               if search.topWithoutDetailsCount > 0 {
                  let noun = search.topWithoutDetailsCount == 1 ? "result" : "results"

                  Text("\(search.topWithoutDetailsCount) hashtag or place \(noun) Instagram+ cannot show yet.")
                     .font(.system(size: 12))
                     .foregroundStyle(Palette.textSecondary)
                     .padding(.horizontal, 12)
                     .padding(.top, 8)
               }
            }
         }
      }
   }

   @ViewBuilder
   private func keywordResults(for query: String) -> some View {
      LoadStateContainer(state: search.keywordState, loadingLabel: "Loading posts", retry: { Task { await search.loadKeyword(query) } }) {
         if search.keywordTiles.isEmpty {
            noResults
         } else {
            VStack(spacing: 14) {
               TileGrid(tiles: search.keywordTiles)

               if search.keywordHasMore {
                  Text("There are more posts, but Instagram+ can read only the first page yet.")
                     .font(.system(size: 12))
                     .foregroundStyle(Palette.textSecondary)
               }
            }
         }
      }
   }

   // The engine has no tag search, but it reads the header of the exact tag typed.
   @ViewBuilder
   private func exactTagResult(for query: String) -> some View {
      switch search.exactTagState {
         case .idle, .loading:
            LoadingStateView(label: "Looking up the tag")

         case .notFound:
            EmptyStateView(symbolName: "number", title: "No tag by that name", message: "Instagram+ can look up an exact tag only, not tags that start with it.")
               .frame(height: 320)

         case .failed(let problem):
            unavailable(problem)

         case .loaded:
            if let tag = search.exactTag {
               VStack(alignment: .leading, spacing: 8) {
                  CollectionRow(symbolName: "number", title: "#" + tag.name, subtitle: postCountLabel(tag.postCount)) {
                     navigation.route = .hashtag(tag.name)
                  }

                  Text("Instagram+ can look up an exact tag only, not tags that start with it.")
                     .font(.system(size: 12))
                     .foregroundStyle(Palette.textSecondary)
                     .padding(.horizontal, 12)
               }
            }
      }
   }

   private var noResults: some View {
      EmptyStateView(symbolName: "magnifyingglass", title: "No results found", message: "Try a different spelling.")
         .frame(height: 320)
   }

   private func unavailable(_ problem: String) -> some View {
      EmptyStateView(symbolName: "magnifyingglass", title: "Not available yet", message: problem)
         .frame(height: 320)
   }

   private var recent: some View {
      let hasRecent = !search.recent.isEmpty || !search.recentKeywords.isEmpty || search.recentWithoutDetailsCount > 0

      return VStack(alignment: .leading, spacing: 18) {
         HStack {
            SectionTitle(text: "Recent")

            Spacer()

            if hasRecent {
               Button("Clear all") {
                  search.clearRecent()
               }
               .buttonStyle(.plain)
               .font(.system(size: 13, weight: .semibold))
               .foregroundStyle(Palette.link)
               .help("Clears this list on this Mac. Instagram+ cannot clear your recent searches on Instagram yet.")
            }
         }

         if case .failed(let problem) = search.recentState, !hasRecent {
            Text(problem)
               .font(.system(size: 14))
               .foregroundStyle(Palette.textSecondary)
         } else if !hasRecent {
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

               ForEach(search.recentKeywords, id: \.self) { keyword in
                  CollectionRow(symbolName: "magnifyingglass", title: keyword, subtitle: "Search") {
                     navigation.searchQuery = keyword
                  }
               }
            }

            if search.recentWithoutDetailsCount > 0 {
               let noun = search.recentWithoutDetailsCount == 1 ? "search" : "searches"

               Text("\(search.recentWithoutDetailsCount) recent hashtag or place \(noun) Instagram+ cannot show yet.")
                  .font(.system(size: 12))
                  .foregroundStyle(Palette.textSecondary)
            }
         }
      }
   }

   private var explore: some View {
      VStack(alignment: .leading, spacing: 18) {
         HStack {
            SectionTitle(text: "Explore")

            Spacer()

            SegmentedPills(options: ExploreMode.allCases, selection: $exploreMode) { $0.title }
         }

         switch exploreMode {
            case .grid:
               LoadStateContainer(state: search.exploreState, loadingLabel: "Loading explore", retry: { Task { await search.loadExplore() } }) {
                  VStack(spacing: 18) {
                     TileGrid(tiles: search.exploreTiles)

                     if search.hasMoreExplore {
                        showMoreButton(isLoading: search.isLoadingMoreExplore) {
                           await search.loadMoreExplore()
                        }
                     }
                  }
               }

            case .posts:
               LoadStateContainer(state: search.explorePostsState, loadingLabel: "Loading posts", retry: { Task { await search.loadExplorePosts() } }) {
                  VStack(spacing: 18) {
                     TileGrid(tiles: search.explorePosts)

                     if search.hasMoreExplorePosts {
                        showMoreButton(isLoading: search.isLoadingMoreExplorePosts) {
                           await search.loadMoreExplorePosts()
                        }
                     }
                  }
               }
               .task { await search.loadExplorePosts() }
         }
      }
   }

   private func showMoreButton(isLoading: Bool, load: @escaping @MainActor () async -> Void) -> some View {
      Button(isLoading ? "Loading" : "Show more") {
         Task { await load() }
      }
      .buttonStyle(.plain)
      .font(.system(size: 13, weight: .semibold))
      .foregroundStyle(Palette.link)
      .disabled(isLoading)
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
// Explore as the engine's sections joined in order, or as its flat page of posts. The flat
// form is read only when it is chosen.
enum ExploreMode: String, CaseIterable, Identifiable {
   case grid
   case posts

   var id: String { rawValue }

   var title: String {
      switch self {
         case .grid: "Sections"
         case .posts: "All posts"
      }
   }
}
