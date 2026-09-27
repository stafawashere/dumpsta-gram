import SwiftUI

struct HomeFeedView: View {
   @Environment(HomeStore.self) private var home

   var body: some View {
      ScrollView {
         VStack(alignment: .leading, spacing: 0) {
            StoriesSection()

            FeedHeader()
               .padding(.top, 40)

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

   private func reload() {
      Task { await home.load() }
   }
}
