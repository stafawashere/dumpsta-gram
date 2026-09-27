import SwiftUI

struct ReelsView: View {
   @Environment(ReelsStore.self) private var reels

   var body: some View {
      Group {
         if reels.state.hasLoaded {
            ScrollView(.vertical) {
               LazyVStack(spacing: 0) {
                  ForEach(reels.reels) { reel in
                     ReelPlayer(reel: reel)
                        .containerRelativeFrame(.vertical)
                  }
               }
               .scrollTargetLayout()
            }
            .scrollTargetBehavior(.paging)
            .scrollIndicators(.never)
         } else {
            LoadStateContainer(state: reels.state, loadingLabel: "Loading reels", retry: reload) {
               EmptyView()
            }
         }
      }
      .task {
         if !reels.state.hasLoaded {
            await reels.load()
         }
      }
   }

   private func reload() {
      Task { await reels.load() }
   }
}

private struct ReelPlayer: View {
   @Environment(ReelsStore.self) private var reels
   @Environment(ProfileStore.self) private var profiles
   @Environment(NavigationStore.self) private var navigation

   let reel: Reel

   @State private var isPlaying = true
   @State private var isMuted = true

   var body: some View {
      HStack(alignment: .bottom, spacing: 20) {
         MediaView(seed: reel.code, cornerRadius: 10)
            .overlay {
               if !isPlaying {
                  Image(systemName: "play.fill")
                     .font(.system(size: 44))
                     .foregroundStyle(.white.opacity(0.9))
                     .shadow(radius: 8)
               }
            }
            .overlay(alignment: .bottom) {
               LinearGradient(colors: [.clear, .black.opacity(0.55)], startPoint: .top, endPoint: .bottom)
                  .frame(height: 200)
                  .allowsHitTesting(false)
            }
            .overlay(alignment: .topTrailing) {
               Button {
                  isMuted.toggle()
               } label: {
                  Image(systemName: isMuted ? "speaker.slash.fill" : "speaker.wave.2.fill")
                     .font(.system(size: 12))
                     .foregroundStyle(.white)
                     .frame(width: 30, height: 30)
                     .background(.black.opacity(0.4), in: Circle())
               }
               .buttonStyle(.plain)
               .padding(14)
               .accessibilityLabel(isMuted ? "Unmute" : "Mute")
            }
            .overlay(alignment: .bottomLeading) {
               details
                  .padding(16)
            }
            .contentShape(Rectangle())
            .onTapGesture { isPlaying.toggle() }
            .aspectRatio(9 / 16, contentMode: .fit)

         actions
            .padding(.bottom, 8)
      }
      .padding(.vertical, 28)
      .frame(maxWidth: .infinity)
   }

   private var details: some View {
      let isFollowing = profiles.isFollowing(reel.author.id)
      let isPending = profiles.isPending(reel.author.id)

      return VStack(alignment: .leading, spacing: 10) {
         HStack(spacing: 10) {
            AvatarLink(account: reel.author, diameter: 32)

            Text(reel.author.username)
               .font(.system(size: 14, weight: .semibold))

            if reel.author.isVerified {
               VerifiedBadge(size: 11)
            }

            Button(isFollowing ? "Following" : "Follow") {
               Task { await profiles.toggleFollow(reel.author.id) }
            }
            .buttonStyle(.plain)
            .font(.system(size: 12, weight: .semibold))
            .padding(.horizontal, 10)
            .frame(height: 26)
            .overlay(RoundedRectangle(cornerRadius: 7).strokeBorder(.white.opacity(0.7)))
            .disabled(isPending)
            .opacity(isPending ? 0.5 : 1)
         }

         Text(reel.caption)
            .font(.system(size: 13))
            .lineLimit(2)

         HStack(spacing: 6) {
            Image(systemName: "music.note")
            Text(reel.audioTitle)
         }
         .font(.system(size: 12))
      }
      .foregroundStyle(.white)
   }

   private var actions: some View {
      VStack(spacing: 22) {
         ReelAction(symbolName: reel.isLiked ? "heart.fill" : "heart", label: CompactCount.format(reel.likeCount), isActive: reel.isLiked) {
            Task { await reels.toggleLike(reelID: reel.id) }
         }

         ReelAction(symbolName: "bubble.right", label: CompactCount.format(reel.commentCount), isActive: false) {
            navigation.showPost(code: reel.code)
         }

         ReelAction(symbolName: "paperplane", label: nil, isActive: false) {}

         ReelAction(symbolName: reel.isSaved ? "bookmark.fill" : "bookmark", label: nil, isActive: reel.isSaved) {
            Task { await reels.toggleSave(reelID: reel.id) }
         }

         ReelAction(symbolName: "ellipsis", label: nil, isActive: false) {}

         MediaView(seed: reel.code + ".audio", cornerRadius: 6)
            .frame(width: 26, height: 26)
            .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Palette.textPrimary, lineWidth: 1.5))
      }
      .opacity(reels.pendingIDs.contains(reel.id) ? 0.6 : 1)
   }
}

private struct ReelAction: View {
   let symbolName: String
   let label: String?
   let isActive: Bool
   let action: () -> Void

   var body: some View {
      Button(action: action) {
         VStack(spacing: 5) {
            Image(systemName: symbolName)
               .font(.system(size: 22))
               .foregroundStyle(isActive ? Palette.accent : Palette.textPrimary)
               .contentTransition(.symbolEffect(.replace))

            if let label {
               Text(label)
                  .font(.system(size: 12, weight: .medium))
                  .foregroundStyle(Palette.textPrimary)
            }
         }
         .frame(width: 44)
         .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
   }
}
