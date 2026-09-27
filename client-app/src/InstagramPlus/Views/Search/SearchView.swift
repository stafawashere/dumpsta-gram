import SwiftUI

struct SearchView: View {
   @Environment(NavigationStore.self) private var navigation
   @Environment(SearchStore.self) private var search

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
      .task {
         await search.loadExplore()
      }
   }

   private func results(for query: String) -> some View {
      VStack(alignment: .leading, spacing: 18) {
         SectionTitle(text: "Results for \"\(query)\"")

         LoadStateContainer(state: search.resultsState, loadingLabel: "Searching", retry: { Task { await search.search(query) } }) {
            if search.results.isEmpty {
               EmptyStateView(symbolName: "magnifyingglass", title: "No results found", message: "Try a different name or username.")
                  .frame(height: 320)
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
         }
      }
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
