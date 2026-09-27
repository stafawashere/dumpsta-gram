import SwiftUI

struct PostDetailView: View {
   @Environment(HomeStore.self) private var home
   @Environment(ProfileStore.self) private var profiles
   @Environment(NavigationStore.self) private var navigation
   @Environment(EngineGateway.self) private var gateway

   let postCode: String

   var body: some View {
      ZStack(alignment: .topTrailing) {
         Color.black.opacity(0.7)
            .onTapGesture { navigation.dismissOverlays() }

         Group {
            if let post = home.post(code: postCode) {
               HStack(spacing: 0) {
                  MediaView(seed: post.mediaSeed, url: post.mediaURL, label: post.mediaDescription.isEmpty ? nil : post.mediaDescription, cornerRadius: 0)
                     .frame(minWidth: 420, maxWidth: 620)

                  sidePanel(for: post)
                     .frame(width: 400)
               }
               .task { await home.loadComments(postPK: post.id) }
            } else {
               LoadStateContainer(state: home.detailState(code: postCode), loadingLabel: "Loading post", notFoundTitle: "Post unavailable", retry: reload) {
                  EmptyView()
               }
               .frame(width: 420, height: 320)
               .background(Palette.card)
            }
         }
         .frame(maxWidth: 1020, maxHeight: 680)
         .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
         .padding(.horizontal, 64)
         .padding(.vertical, 48)
         .frame(maxWidth: .infinity, maxHeight: .infinity)

         OverlayCloseButton { navigation.dismissOverlays() }
            .padding(20)
      }
      .task { await home.loadPost(code: postCode) }
   }

   private func reload() {
      Task { await home.loadPost(code: postCode) }
   }

   private func sidePanel(for post: Post) -> some View {
      VStack(alignment: .leading, spacing: 0) {
         PostHeader(post: post)
            .padding(16)

         Hairline()

         ScrollView {
            VStack(alignment: .leading, spacing: 20) {
               if !post.caption.isEmpty {
                  CommentRow(author: post.author, text: post.caption, postedAt: post.postedAt, likeCount: nil, isLiked: false, isPending: false)
               }

               switch home.commentState(for: post.id) {
                  case .loading where home.comments(for: post.id).isEmpty:
                     LoadingStateView(label: "Loading comments")

                  case .failed(let message):
                     ErrorStateView(message: message) {
                        Task { await home.loadComments(postPK: post.id) }
                     }

                  default:
                     ForEach(home.comments(for: post.id)) { comment in
                        CommentRow(author: comment.author, text: comment.text, postedAt: comment.postedAt, likeCount: comment.likeCount, isLiked: comment.isLiked, isPending: comment.isPending)
                           .contextMenu {
                              let isOwnComment = comment.author.id == gateway.viewerID

                              if isOwnComment, !comment.isPending {
                                 Button("Delete comment", role: .destructive) {
                                    Task { await home.deleteComment(comment.id, from: post.id) }
                                 }
                              }
                           }
                     }
               }
            }
            .padding(16)
         }

         Hairline()

         VStack(alignment: .leading, spacing: 10) {
            PostActionBar(post: post, isCompact: true)

            Text(post.postedAt.formatted(date: .long, time: .omitted).uppercased())
               .font(.system(size: 10, weight: .medium))
               .tracking(0.5)
               .foregroundStyle(Palette.textSecondary)
         }
         .padding(16)

         Hairline()

         if post.commentsDisabled {
            Text("Commenting has been turned off.")
               .font(.system(size: 13))
               .foregroundStyle(Palette.textSecondary)
               .padding(16)
         } else {
            CommentComposer(viewer: profiles.viewerAccount, placeholder: "Add a comment") { text in
               Task { await home.addComment(text, to: post.id, viewer: profiles.viewerAccount) }
            }
            .padding(12)
         }
      }
      .background(Palette.card)
   }
}

private struct CommentRow: View {
   let author: Account
   let text: String
   let postedAt: Date
   let likeCount: Int?
   let isLiked: Bool
   let isPending: Bool

   var body: some View {
      HStack(alignment: .top, spacing: 12) {
         AvatarLink(account: author, diameter: 32)

         VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
               AccountLink(account: author, size: 13, usesUsername: true)

               Text(text)
                  .font(.system(size: 13))
                  .foregroundStyle(Palette.textPrimary)
                  .fixedSize(horizontal: false, vertical: true)
            }

            HStack(spacing: 14) {
               if isPending {
                  Text("Posting")
               } else {
                  Text(RelativeTime.short(since: postedAt))
               }

               if let likeCount, likeCount > 0 {
                  Text(likeCount == 1 ? "1 like" : "\(CompactCount.format(likeCount)) likes")
                     .fontWeight(.semibold)
               }
            }
            .font(.system(size: 11))
            .foregroundStyle(Palette.textSecondary)
         }

         Spacer(minLength: 0)

         if likeCount != nil {
            Image(systemName: isLiked ? "heart.fill" : "heart")
               .font(.system(size: 11))
               .foregroundStyle(isLiked ? Palette.accent : Palette.textSecondary)
               .padding(.top, 4)
               .help("Liking comments is not in the engine yet")
         }
      }
      .opacity(isPending ? 0.55 : 1)
   }
}
