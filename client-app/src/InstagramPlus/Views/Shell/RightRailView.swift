import SwiftUI

struct RightRailView: View {
   @Environment(NavigationStore.self) private var navigation
   @Environment(HomeStore.self) private var home
   @Environment(ProfileStore.self) private var profiles

   private let trendingSeeds = ["trend.c", "trend.d", "trend.e", "trend.f"]

   var body: some View {
      VStack(spacing: 0) {
         HStack {
            Spacer(minLength: 0)
            HeaderActions()
         }
         .padding(.horizontal, 24)
         .frame(height: RootView.headerHeight)

         Hairline()

         ScrollView {
            VStack(alignment: .leading, spacing: 0) {
               trendingFeeds

               suggestions
                  .padding(.top, 36)

               profileActivity
                  .padding(.top, 36)
            }
            .padding(.horizontal, 28)
            .padding(.vertical, 32)
         }
         .scrollIndicators(.never)
      }
      .background(Palette.panel)
   }

   private var trendingFeeds: some View {
      VStack(alignment: .leading, spacing: 18) {
         SectionTitle(text: "Trending feeds", size: 16)

         LazyVGrid(columns: [GridItem(.flexible(), spacing: 8), GridItem(.flexible(), spacing: 8)], spacing: 8) {
            ForEach(trendingSeeds, id: \.self) { seed in
               Button {
                  navigation.route = .search
               } label: {
                  MediaView(seed: seed, cornerRadius: 8)
                     .frame(height: 94)
               }
               .buttonStyle(.plain)
            }
         }
      }
   }

   private var suggestions: some View {
      VStack(alignment: .leading, spacing: 18) {
         SectionTitle(text: "Suggestions for you", size: 16)

         VStack(spacing: 14) {
            ForEach(home.suggestions) { account in
               SuggestionRow(account: account, isFollowing: profiles.isFollowing(account.id), isPending: profiles.isPending(account.id)) {
                  Task { await profiles.toggleFollow(account.id) }
               }
            }
         }
      }
   }

   private var profileActivity: some View {
      VStack(alignment: .leading, spacing: 18) {
         SectionTitle(text: "Profile activity", size: 16)

         Button {
            navigation.route = .notifications
         } label: {
            VStack(alignment: .leading, spacing: 0) {
               HStack(spacing: -8) {
                  ForEach(home.recentFollowers) { follower in
                     Avatar(account: follower, diameter: 30)
                        .overlay(Circle().strokeBorder(Palette.raised, lineWidth: 2))
                  }
               }

               HStack(alignment: .firstTextBaseline, spacing: 6) {
                  Text(CompactCount.format(home.activeFollowerCount))
                     .font(.system(size: 24, weight: .semibold))

                  Text("Followers")
                     .font(.system(size: 13))
               }
               .foregroundStyle(Palette.textPrimary)
               .padding(.top, 14)

               Text("Active now on your profile")
                  .font(.system(size: 12, weight: .semibold))
                  .foregroundStyle(Palette.textPrimary)
                  .padding(.top, 4)
            }
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Palette.raised, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .contentShape(Rectangle())
         }
         .buttonStyle(.plain)

         Button {
            navigation.route = .create
         } label: {
            Text("The perfect time for uploading your new post. \(Text("Create new post").underline().foregroundStyle(Palette.accent))")
               .font(.system(size: 11))
               .foregroundStyle(Palette.textSecondary)
               .lineSpacing(4)
               .multilineTextAlignment(.leading)
         }
         .buttonStyle(.plain)
      }
   }
}

private struct SuggestionRow: View {
   let account: Account
   let isFollowing: Bool
   let isPending: Bool
   let toggleFollow: () -> Void

   var body: some View {
      HStack(spacing: 12) {
         AvatarLink(account: account, diameter: 38)

         VStack(alignment: .leading, spacing: 2) {
            AccountLink(account: account, size: 13)

            Text(account.username)
               .font(.system(size: 11))
               .foregroundStyle(Palette.textSecondary)
         }
         .lineLimit(1)

         Spacer(minLength: 8)

         Button(action: toggleFollow) {
            Text(isFollowing ? "Following" : "Follow")
               .font(.system(size: 12, weight: .semibold))
               .foregroundStyle(isFollowing ? Palette.textSecondary : Palette.accent)
               .contentShape(Rectangle())
         }
         .buttonStyle(.plain)
         .disabled(isPending)
         .opacity(isPending ? 0.5 : 1)
      }
   }
}
