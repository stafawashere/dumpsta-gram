import AppKit
import UniformTypeIdentifiers
import SwiftUI

struct PostCard: View {
   @Environment(HomeStore.self) private var home
   @Environment(ProfileStore.self) private var profiles
   @Environment(NavigationStore.self) private var navigation

   let post: Post

   var body: some View {
      VStack(alignment: .leading, spacing: 0) {
         PostHeader(post: post)

         PostMedia(post: post) {
            navigation.showPost(code: post.code)
         }
         .frame(height: 288)
         .padding(.top, 16)

         PostActionBar(post: post)
            .padding(.vertical, 16)

         Hairline()

         if !post.caption.isEmpty {
            CaptionText(text: post.caption)
               .lineSpacing(5)
               .fixedSize(horizontal: false, vertical: true)
               .padding(.top, 16)
               .padding(.horizontal, 2)
         }

         if post.commentsDisabled {
            Text("Commenting has been turned off.")
               .font(.system(size: 13))
               .foregroundStyle(Palette.textSecondary)
               .padding(.top, 14)
         } else {
            CommentComposer(viewer: profiles.viewerAccount) { text in
               Task { await home.addComment(text, to: post.id, viewer: profiles.viewerAccount) }
            }
            .padding(.top, 18)
         }
      }
      .padding(22)
      .background(Palette.card, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
      .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(Palette.hairline))
   }
}

struct PostHeader: View {
   @Environment(HomeStore.self) private var home
   @Environment(NavigationStore.self) private var navigation
   @Environment(EngineGateway.self) private var gateway

   let post: Post

   @State private var isConfirmingDelete = false

   var body: some View {
      let isOwnPost = post.author.id == gateway.viewerID

      HStack(spacing: 12) {
         AvatarLink(account: post.author, diameter: 40)

         VStack(alignment: .leading, spacing: 2) {
            AccountLink(account: post.author)

            HStack(spacing: 6) {
               if let location = post.location {
                  Button(location) {
                     navigation.dismissOverlays()
                     navigation.route = .place(id: location, name: location)
                  }
                  .buttonStyle(.plain)
               }

               Text(RelativeTime.short(since: post.postedAt))
                  .foregroundStyle(Palette.textTertiary)
            }
            .font(.system(size: 11))
            .foregroundStyle(Palette.textSecondary)
         }

         Spacer()

         Menu {
            Button("Go to post") {
               navigation.showPost(code: post.code)
            }

            Button("Share to") {
               navigation.share(postPK: post.id)
            }

            Button("Copy link") {
               NSPasteboard.general.clearContents()
               NSPasteboard.general.setString("https://www.instagram.com/p/\(post.code)/", forType: .string)
            }

            Button("Download") {
               download()
            }

            Button("About this account") {
               navigation.openProfile(post.author.id)
            }

            Divider()

            if isOwnPost {
               Button("Delete", role: .destructive) {
                  isConfirmingDelete = true
               }
            } else {
               Button("Not interested") {
                  navigation.dismissOverlays()
                  Task { await home.hide(postPK: post.id) }
               }
            }
         } label: {
            Image(systemName: "ellipsis")
               .font(.system(size: 16, weight: .bold))
               .foregroundStyle(Palette.textPrimary)
         }
         .menuStyle(.borderlessButton)
         .menuIndicator(.hidden)
         .fixedSize()
         .frame(width: 32, height: 32)
         .accessibilityLabel("More options")
      }
      .confirmationDialog("Delete this post?", isPresented: $isConfirmingDelete) {
         Button("Delete", role: .destructive) {
            navigation.dismissOverlays()
            Task { _ = await home.delete(postPK: post.id) }
         }
      } message: {
         Text("It will be removed from your profile and everyone's feed.")
      }
   }

   private func download() {
      let panel = NSSavePanel()
      panel.nameFieldStringValue = "\(post.author.username)-\(post.code).png"
      panel.allowedContentTypes = [.png]

      guard panel.runModal() == .OK, let destination = panel.url else {
         return
      }

      Task {
         let didSave = await home.download(post, to: destination)

         if didSave {
            gateway.post(Notice(tone: .info, title: "Saved", message: destination.lastPathComponent))
         }
      }
   }
}

struct PostActionBar: View {
   @Environment(HomeStore.self) private var home
   @Environment(NavigationStore.self) private var navigation

   let post: Post
   var isCompact = false

   var body: some View {
      let isPending = home.isPending(post.id)

      HStack {
         PostAction(
            symbolName: post.isLiked ? "heart.fill" : "heart",
            count: post.hidesLikeCount ? nil : post.likeCount,
            title: "Like",
            isActive: post.isLiked,
            isCompact: isCompact
         ) {
            Task { await home.toggleLike(postPK: post.id) }
         }

         Spacer()

         PostAction(symbolName: "bubble.right", count: post.commentCount, title: "Comment", isActive: false, isCompact: isCompact) {
            navigation.showPost(code: post.code)
         }

         Spacer()

         PostAction(symbolName: "square.and.arrow.up", count: post.shareCount, title: "Share", isActive: false, isCompact: isCompact) {
            navigation.share(postPK: post.id)
         }

         Spacer()

         PostAction(
            symbolName: post.isSaved ? "bookmark.fill" : "bookmark",
            count: post.saveCount,
            title: post.isSaved ? "Saved" : "Save",
            isActive: post.isSaved,
            isCompact: isCompact
         ) {
            Task { await home.toggleSave(postPK: post.id) }
         }
      }
      .padding(.horizontal, 2)
      .opacity(isPending ? 0.6 : 1)
      .disabled(isPending)
      .help(isPending ? "Waiting for the engine's pacer" : "")
   }
}

private struct PostAction: View {
   let symbolName: String
   let count: Int?
   let title: String
   let isActive: Bool
   let isCompact: Bool
   let action: () -> Void

   var body: some View {
      Button(action: action) {
         HStack(spacing: 7) {
            Image(systemName: symbolName)
               .font(.system(size: 15))
               .foregroundStyle(isActive ? Palette.accent : Palette.textPrimary)
               .contentTransition(.symbolEffect(.replace))

            if let count {
               Text(CompactCount.format(count))
                  .monospacedDigit()
            }

            if !isCompact {
               Text(title)
            }
         }
         .font(.system(size: 14))
         .foregroundStyle(Palette.textPrimary)
         .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
      .accessibilityLabel(title)
   }
}

struct CommentComposer: View {
   let viewer: Account
   var placeholder = "Write your comment"
   let submit: (String) -> Void

   @State private var draft = ""

   var body: some View {
      let hasDraft = !draft.trimmingCharacters(in: .whitespaces).isEmpty

      HStack(spacing: 12) {
         Avatar(account: viewer, diameter: 36, style: .soft)

         HStack(spacing: 8) {
            TextField(placeholder, text: $draft)
               .textFieldStyle(.plain)
               .font(.system(size: 14))
               .onSubmit(send)

            if hasDraft {
               Button("Post", action: send)
                  .buttonStyle(.plain)
                  .font(.system(size: 13, weight: .semibold))
                  .foregroundStyle(Palette.link)
            }
         }
         .padding(.horizontal, 18)
         .frame(height: 44)
         .background(Palette.field, in: Capsule())
         .overlay(Capsule().strokeBorder(Palette.hairline))
      }
   }

   private func send() {
      submit(draft)
      draft = ""
   }
}
