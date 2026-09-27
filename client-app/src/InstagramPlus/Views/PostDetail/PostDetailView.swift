import SwiftUI

struct PostDetailView: View {
   @Environment(HomeStore.self) private var home
   @Environment(ProfileStore.self) private var profiles
   @Environment(NavigationStore.self) private var navigation
   @Environment(EngineGateway.self) private var gateway

   let postCode: String

   @State private var replyTarget: PostComment?

   var body: some View {
      ZStack(alignment: .topTrailing) {
         Color.black.opacity(0.7)
            .onTapGesture { navigation.dismissOverlays() }

         Group {
            if let post = home.post(code: postCode) {
               HStack(spacing: 0) {
                  PostMedia(post: post, cornerRadius: 0)
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

   private func commentRow(_ comment: PostComment, post: Post) -> some View {
      CommentRow(comment: comment) {
         Task { await home.toggleCommentLike(comment.id, on: post.id) }
      } reply: {
         replyTarget = comment
      }
      .contextMenu {
         let isOwnComment = comment.author.id == gateway.viewerID

         if isOwnComment, !comment.isPending {
            Button("Delete comment", role: .destructive) {
               Task { await home.deleteComment(comment.id, from: post.id) }
            }
         }
      }
   }

   private func sidePanel(for post: Post) -> some View {
      VStack(alignment: .leading, spacing: 0) {
         PostHeader(post: post)
            .padding(16)

         Hairline()

         ScrollView {
            VStack(alignment: .leading, spacing: 20) {
               if !post.caption.isEmpty {
                  HStack(alignment: .top, spacing: 12) {
                     AvatarLink(account: post.author, diameter: 32)

                     CaptionText(text: post.caption, leadingUsername: post.author.username, size: 13)
                        .fixedSize(horizontal: false, vertical: true)
                  }
               }

               switch home.commentState(for: post.id) {
                  case .loading where home.comments(for: post.id).isEmpty:
                     LoadingStateView(label: "Loading comments")

                  case .failed(let message):
                     ErrorStateView(message: message) {
                        Task { await home.loadComments(postPK: post.id) }
                     }

                  default:
                     let all = home.comments(for: post.id)
                     let topLevel = all.filter { $0.parentID == nil }

                     ForEach(topLevel) { comment in
                        commentRow(comment, post: post)

                        ForEach(all.filter { $0.parentID == comment.id }) { reply in
                           commentRow(reply, post: post)
                              .padding(.leading, 44)
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
            VStack(spacing: 0) {
               if let replyTarget {
                  HStack {
                     Text("Replying to \(replyTarget.author.username)")
                        .font(.system(size: 12))
                        .foregroundStyle(Palette.textSecondary)

                     Spacer()

                     Button {
                        self.replyTarget = nil
                     } label: {
                        Image(systemName: "xmark")
                           .font(.system(size: 10, weight: .bold))
                     }
                     .buttonStyle(.plain)
                  }
                  .padding(.horizontal, 16)
                  .padding(.top, 10)
               }

               CommentComposer(viewer: profiles.viewerAccount, placeholder: replyTarget == nil ? "Add a comment" : "Add a reply") { text in
                  let target = replyTarget
                  replyTarget = nil

                  Task {
                     if let target {
                        await home.reply(text, to: target.parentID ?? target.id, on: post.id, viewer: profiles.viewerAccount)
                     } else {
                        await home.addComment(text, to: post.id, viewer: profiles.viewerAccount)
                     }
                  }
               }
               .padding(12)
            }
         }
      }
      .background(Palette.card)
   }
}

private struct CommentRow: View {
   let comment: PostComment
   let toggleLike: () -> Void
   let reply: () -> Void

   var body: some View {
      HStack(alignment: .top, spacing: 12) {
         AvatarLink(account: comment.author, diameter: 32)

         VStack(alignment: .leading, spacing: 6) {
            CaptionText(text: comment.text, leadingUsername: comment.author.username, size: 13)
               .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 14) {
               Text(comment.isPending ? "Posting" : RelativeTime.short(since: comment.postedAt))

               if comment.likeCount > 0 {
                  Text(comment.likeCount == 1 ? "1 like" : "\(CompactCount.format(comment.likeCount)) likes")
                     .fontWeight(.semibold)
               }

               if !comment.isPending {
                  Button("Reply", action: reply)
                     .buttonStyle(.plain)
                     .fontWeight(.semibold)
               }
            }
            .font(.system(size: 11))
            .foregroundStyle(Palette.textSecondary)
         }

         Spacer(minLength: 0)

         if !comment.isPending {
            Button(action: toggleLike) {
               Image(systemName: comment.isLiked ? "heart.fill" : "heart")
                  .font(.system(size: 11))
                  .foregroundStyle(comment.isLiked ? Palette.accent : Palette.textSecondary)
                  .padding(.top, 4)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(comment.isLiked ? "Unlike comment" : "Like comment")
         }
      }
      .opacity(comment.isPending ? 0.55 : 1)
   }
}
