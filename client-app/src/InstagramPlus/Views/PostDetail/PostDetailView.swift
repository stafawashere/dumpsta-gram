import SwiftUI

struct PostDetailView: View {
   @Environment(HomeStore.self) private var home
   @Environment(ProfileStore.self) private var profiles
   @Environment(NavigationStore.self) private var navigation
   @Environment(EngineGateway.self) private var gateway

   let postCode: String

   @State private var replyTarget: PostComment?
   @State private var isShowingLikers = false
   @State private var isShowingAuthorGrid = false
   @State private var presentedAudio: PresentedAudio?

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
               .task(id: post.id) {
                  let hasComments = home.commentState(for: post.id).hasLoaded

                  if !hasComments {
                     await home.loadComments(postPK: post.id)
                  }
               }
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
      .onChange(of: postCode) {
         isShowingAuthorGrid = false
         replyTarget = nil
      }
      .sheet(isPresented: $isShowingLikers) {
         if let post = home.post(code: postCode) {
            LikersSheet(postPK: post.id)
         }
      }
      .sheet(item: $presentedAudio) { audio in
         AudioPageSheet(audio: audio)
      }
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

   // Replies arrive only when a person asks for them. The count is the engine's, and a comment
   // whose count the engine did not give offers no button rather than a guess.
   @ViewBuilder
   private func replyControl(for comment: PostComment, post: Post, shownReplies: Int) -> some View {
      let state = home.replyState(of: comment.id)
      let replyCount = comment.replyCount ?? 0
      let hasUnreadReplies = !state.hasLoaded && replyCount > shownReplies
      let hasMorePages = state.hasLoaded && home.hasMoreReplies(to: comment.id)

      if state.isLoading {
         Text("Loading replies")
            .replyControlStyle()
      } else if case .failed(let message) = state {
         Button("Could not load replies. \(message) Try again") {
            Task { await home.loadReplies(to: comment.id, on: post.id) }
         }
         .buttonStyle(.plain)
         .replyControlStyle()
      } else if hasUnreadReplies || hasMorePages {
         let label = hasMorePages ? "View more replies" : "View replies (\(CompactCount.format(replyCount)))"

         Button {
            Task { await home.loadReplies(to: comment.id, on: post.id) }
         } label: {
            HStack(spacing: 8) {
               Rectangle()
                  .fill(Palette.textTertiary)
                  .frame(width: 24, height: 1)

               Text(label)
            }
         }
         .buttonStyle(.plain)
         .replyControlStyle()
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

               if let audioID = post.audioID {
                  audioRow(audioID: audioID, title: post.audioTitle ?? "Audio", author: post.author)
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
                        let replies = all.filter { $0.parentID == comment.id }

                        commentRow(comment, post: post)

                        ForEach(replies) { reply in
                           commentRow(reply, post: post)
                              .padding(.leading, 44)
                        }

                        replyControl(for: comment, post: post, shownReplies: replies.count)
                           .padding(.leading, 44)
                     }

                     if home.hasMoreComments(for: post.id) {
                        Button(home.isLoadingMoreComments(for: post.id) ? "Loading comments" : "Load more comments") {
                           Task { await home.loadMoreComments(postPK: post.id) }
                        }
                        .buttonStyle(.plain)
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(Palette.textSecondary)
                        .disabled(home.isLoadingMoreComments(for: post.id))
                     }
               }

               authorGridSection(for: post)
            }
            .padding(16)
         }

         Hairline()

         VStack(alignment: .leading, spacing: 10) {
            PostActionBar(post: post, isCompact: true)

            Button {
               isShowingLikers = true
            } label: {
               Text(likedByLabel(for: post))
                  .font(.system(size: 13, weight: .semibold))
                  .foregroundStyle(Palette.textPrimary)
            }
            .buttonStyle(.plain)
            .help("Shows a sample of the accounts that liked this post")

            Text(post.postedAt.formatted(date: .long, time: .omitted).uppercased())
               .font(.system(size: 10, weight: .medium))
               .tracking(0.5)
               .foregroundStyle(Palette.textSecondary)
         }
         .padding(16)

         Hairline()

         if post.commentsDisabled == true {
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

   private func likedByLabel(for post: Post) -> String {
      guard !post.hidesLikeCount else {
         return "Liked by others"
      }

      return post.likeCount == 1 ? "Liked by 1 account" : "Liked by \(CompactCount.format(post.likeCount)) accounts"
   }

   private func audioRow(audioID: String, title: String, author: Account) -> some View {
      Button {
         presentedAudio = PresentedAudio(id: audioID, title: title)
      } label: {
         HStack(spacing: 8) {
            Image(systemName: "music.note")
               .font(.system(size: 11, weight: .semibold))

            Text(title)
               .lineLimit(1)

            Image(systemName: "chevron.right")
               .font(.system(size: 9, weight: .semibold))
               .foregroundStyle(Palette.textTertiary)
         }
         .font(.system(size: 12, weight: .medium))
         .foregroundStyle(Palette.textPrimary)
         .padding(.horizontal, 10)
         .padding(.vertical, 6)
         .background(Palette.raised, in: Capsule())
      }
      .buttonStyle(.plain)
      .help("Opens the reels that use this audio")
   }

   // The author's other posts. A post opened through its page already carries them, and
   // otherwise they are read when the section is opened.
   @ViewBuilder
   private func authorGridSection(for post: Post) -> some View {
      let authorID = post.author.id
      let state = home.authorGridState(of: authorID)
      let tiles = home.authorGrid(of: authorID).filter { $0.id != post.id }

      VStack(alignment: .leading, spacing: 12) {
         Hairline()

         Button {
            isShowingAuthorGrid.toggle()

            if isShowingAuthorGrid {
               Task { await home.loadAuthorGrid(authorID: authorID) }
            }
         } label: {
            HStack {
               Text("More posts from \(post.author.username)")
                  .font(.system(size: 13, weight: .semibold))
                  .foregroundStyle(Palette.textPrimary)

               Spacer()

               Image(systemName: isShowingAuthorGrid ? "chevron.up" : "chevron.down")
                  .font(.system(size: 11, weight: .semibold))
                  .foregroundStyle(Palette.textSecondary)
            }
            .contentShape(Rectangle())
         }
         .buttonStyle(.plain)

         if isShowingAuthorGrid {
            switch state {
               case .idle, .loading:
                  LoadingStateView(label: "Loading posts")

               case .failed(let message):
                  ErrorStateView(message: message) {
                     Task { await home.loadAuthorGrid(authorID: authorID) }
                  }

               case .loaded, .notFound:
                  if tiles.isEmpty {
                     Text("No other posts to show.")
                        .font(.system(size: 12))
                        .foregroundStyle(Palette.textSecondary)
                  } else {
                     TileGrid(tiles: tiles)
                  }
            }
         }
      }
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

               if let likeCount = comment.likeCount, likeCount > 0 {
                  Text(likeCount == 1 ? "1 like" : "\(CompactCount.format(likeCount)) likes")
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
            let isLiked = comment.isLiked == true

            Button(action: toggleLike) {
               Image(systemName: isLiked ? "heart.fill" : "heart")
                  .font(.system(size: 11))
                  .foregroundStyle(isLiked ? Palette.accent : Palette.textSecondary)
                  .padding(.top, 4)
            }
            .buttonStyle(.plain)
            .opacity(comment.isLiked == nil ? 0.55 : 1)
            .help(comment.isLiked == nil ? "Instagram+ cannot tell whether you like this comment" : "")
            .accessibilityLabel(isLiked ? "Unlike comment" : "Like comment")
         }
      }
      .opacity(comment.isPending ? 0.55 : 1)
   }
}

private struct LikersSheet: View {
   @Environment(HomeStore.self) private var home
   @Environment(NavigationStore.self) private var navigation
   @Environment(\.dismiss) private var dismiss

   let postPK: String

   var body: some View {
      VStack(spacing: 0) {
         HStack {
            Text("Likes")
               .font(.system(size: 16, weight: .semibold))

            Spacer()

            Button("Done") { dismiss() }
               .keyboardShortcut(.cancelAction)
         }
         .padding(16)

         Hairline()

         LoadStateContainer(state: home.likerState(of: postPK), loadingLabel: "Loading likes", retry: load) {
            let likers = home.likers(of: postPK)

            if likers.isEmpty {
               EmptyStateView(symbolName: "heart", title: "No likes to show", message: "Instagram shared no accounts for this post.")
            } else {
               ScrollView {
                  VStack(alignment: .leading, spacing: 2) {
                     ForEach(likers) { account in
                        HStack(spacing: 12) {
                           Avatar(account: account, diameter: 40)

                           VStack(alignment: .leading, spacing: 2) {
                              Text(account.username)
                                 .font(.system(size: 13, weight: .semibold))

                              Text(account.displayName)
                                 .font(.system(size: 12))
                                 .foregroundStyle(Palette.textSecondary)
                           }

                           Spacer()
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 8)
                        .contentShape(Rectangle())
                        .onTapGesture {
                           dismiss()
                           navigation.openProfile(account.id)
                        }
                     }

                     Text("Instagram shares a sample of the accounts, not the whole list.")
                        .font(.system(size: 11))
                        .foregroundStyle(Palette.textSecondary)
                        .padding(16)
                  }
                  .padding(.vertical, 8)
               }
            }
         }
      }
      .frame(width: 400, height: 480)
      .task {
         let hasLoaded = home.likerState(of: postPK).hasLoaded

         if !hasLoaded {
            await home.loadLikers(postPK: postPK)
         }
      }
   }

   private func load() {
      Task { await home.loadLikers(postPK: postPK) }
   }
}

struct PresentedAudio: Identifiable, Hashable {
   let id: String
   let title: String
}

struct AudioPageSheet: View {
   @Environment(ReelsStore.self) private var reels
   @Environment(NavigationStore.self) private var navigation
   @Environment(\.dismiss) private var dismiss

   let audio: PresentedAudio

   var body: some View {
      VStack(spacing: 0) {
         HStack(spacing: 14) {
            Image(systemName: "music.note")
               .font(.system(size: 22, weight: .light))
               .frame(width: 52, height: 52)
               .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).strokeBorder(Palette.hairline))

            VStack(alignment: .leading, spacing: 3) {
               let page = reels.audioPage(audio.id)

               Text(page?.title ?? audio.title)
                  .font(.system(size: 16, weight: .semibold))
                  .lineLimit(1)

               if let page {
                  let artist = page.artist.map { $0 + ", " } ?? ""
                  let noun = page.clipsCount == 1 ? "reel" : "reels"

                  Text("\(artist)\(CompactCount.format(page.clipsCount)) \(noun)")
                     .font(.system(size: 12))
                     .foregroundStyle(Palette.textSecondary)
               }
            }

            Spacer()

            Button("Done") { dismiss() }
               .keyboardShortcut(.cancelAction)
         }
         .padding(16)

         Hairline()

         LoadStateContainer(state: reels.audioState(audio.id), loadingLabel: "Loading audio", notFoundTitle: "Audio unavailable", retry: load) {
            ScrollView {
               VStack(spacing: 14) {
                  if reels.audioPage(audio.id)?.isRestricted == true {
                     Text("Instagram restricts this audio, so some reels may be missing.")
                        .font(.system(size: 12))
                        .foregroundStyle(Palette.textSecondary)
                  }

                  TileGrid(tiles: reels.audioPage(audio.id)?.clips ?? [], isTall: true)

                  if reels.hasMoreClips(audio.id) {
                     Button(reels.isLoadingMoreClips(audio.id) ? "Loading" : "Show more") {
                        Task { await reels.loadMoreClips(audio.id) }
                     }
                     .buttonStyle(.plain)
                     .font(.system(size: 13, weight: .semibold))
                     .foregroundStyle(Palette.link)
                     .disabled(reels.isLoadingMoreClips(audio.id))
                  }
               }
               .padding(16)
            }
         }
      }
      .frame(width: 520, height: 600)
      .task { await reels.loadAudio(audio.id, title: audio.title) }
      .onChange(of: navigation.presentedPostCode) {
         dismiss()
      }
   }

   private func load() {
      Task { await reels.loadAudio(audio.id, title: audio.title) }
   }
}

private extension View {
   func replyControlStyle() -> some View {
      font(.system(size: 11, weight: .semibold))
         .foregroundStyle(Palette.textSecondary)
   }
}
