import SwiftUI

struct HomeFeedView: View {
   @Environment(HomeStore.self) private var home

   var body: some View {
      ScrollView {
         VStack(alignment: .leading, spacing: 0) {
            StoriesSection()

            FeedHeader()
               .padding(.top, 40)

            if home.feedState.hasLoaded {
               newPostsPill
                  .frame(maxWidth: .infinity)
                  .padding(.top, 16)
            }

            if home.isPublishing {
               HStack(spacing: 10) {
                  ProgressView()
                     .controlSize(.small)

                  Text("Sharing your post. It departs when the pacer allows.")
                     .font(.system(size: 13))
                     .foregroundStyle(Palette.textSecondary)
               }
               .padding(14)
               .frame(maxWidth: .infinity, alignment: .leading)
               .background(Palette.card, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
               .padding(.top, 20)
            }

            LoadStateContainer(state: home.feedState, loadingLabel: "Loading your feed", retry: reload) {
               LazyVStack(spacing: 20) {
                  ForEach(home.orderedPosts) { post in
                     PostCard(post: post)
                  }

                  if home.unshownFeedItemCount > 0 {
                     Text(unshownItemsNote)
                        .font(.system(size: 12))
                        .foregroundStyle(Palette.textSecondary)
                        .frame(maxWidth: .infinity)
                  }

                  feedFooter
               }
            }
            .padding(.top, 20)
         }
         .frame(maxWidth: 624)
         .padding(.horizontal, 40)
         .padding(.vertical, 36)
         .frame(maxWidth: .infinity)
      }
   }

   @ViewBuilder
   private var feedFooter: some View {
      if home.hasMorePosts {
         LoadingStateView(label: "Loading more")
            .padding(.vertical, -30)
            .onAppear {
               Task { await home.loadMore() }
            }
      } else if !home.orderedPosts.isEmpty {
         VStack(spacing: 8) {
            Image(systemName: "checkmark.circle")
               .font(.system(size: 28, weight: .light))
               .foregroundStyle(Palette.accent)

            Text("You're all caught up")
               .font(.system(size: 14, weight: .semibold))
               .foregroundStyle(Palette.textPrimary)
         }
         .padding(.vertical, 30)
      }
   }

   // One read of has_new_posts, sent only when the pill is pressed. Nothing polls it.
   private var newPostsPill: some View {
      let state = home.newPostsState
      let isChecking = state == .checking
      let hasNewPosts = state == .available

      let title = switch state {
         case .unchecked: "Check for new posts"
         case .checking: "Checking for new posts"
         case .available: "New posts"
         case .upToDate: "No new posts yet"
         case .unknown: "Could not check for new posts"
      }

      return Button {
         Task {
            if hasNewPosts {
               await home.showNewPosts()
            } else {
               await home.checkForNewPosts()
            }
         }
      } label: {
         HStack(spacing: 6) {
            Image(systemName: hasNewPosts ? "arrow.up" : "arrow.clockwise")
               .font(.system(size: 11, weight: .bold))

            Text(title)
               .font(.system(size: 13, weight: .semibold))
         }
         .foregroundStyle(hasNewPosts ? Color.white : Palette.textPrimary)
         .padding(.horizontal, 16)
         .padding(.vertical, 8)
         .background(hasNewPosts ? AnyShapeStyle(Palette.primaryButton) : AnyShapeStyle(Palette.card), in: Capsule())
         .overlay(Capsule().strokeBorder(hasNewPosts ? Color.clear : Palette.hairline))
      }
      .buttonStyle(.plain)
      .disabled(isChecking)
      .help(hasNewPosts ? "Reloads the feed from the top" : "Asks Instagram once whether the feed has posts newer than these")
   }

   private var unshownItemsNote: String {
      let count = home.unshownFeedItemCount
      let noun = count == 1 ? "item" : "items"
      return "Instagram also sent \(count) \(noun) Instagram+ does not show yet, such as ads and suggestions."
   }

   private func reload() {
      Task { await home.load() }
   }
}
