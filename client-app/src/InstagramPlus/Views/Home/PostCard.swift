import AppKit
import SwiftUI

struct PostCard: View {
   @Environment(HomeStore.self) private var home
   @Environment(ProfileStore.self) private var profiles
   @Environment(NavigationStore.self) private var navigation

   let post: Post

   var body: some View {
      VStack(alignment: .leading, spacing: 0) {
         PostHeader(post: post)

         Button {
            navigation.showPost(code: post.code)
         } label: {
            MediaView(seed: post.mediaSeed, url: post.mediaURL, label: post.mediaDescription.isEmpty ? nil : post.mediaDescription)
               .frame(height: 288)
         }
         .buttonStyle(.plain)
         .padding(.top, 16)

         PostActionBar(post: post)
            .padding(.vertical, 16)

         Hairline()

         if !post.caption.isEmpty {
            Text(post.caption)
               .font(.system(size: 15))
               .lineSpacing(5)
               .foregroundStyle(Palette.textPrimary)
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
   let post: Post

   var body: some View {
      HStack(spacing: 12) {
         AvatarLink(account: post.author, diameter: 40)

         VStack(alignment: .leading, spacing: 2) {
            AccountLink(account: post.author)

            HStack(spacing: 6) {
               if let location = post.location {
                  Text(location)
               }

               Text(RelativeTime.short(since: post.postedAt))
                  .foregroundStyle(Palette.textTertiary)
            }
            .font(.system(size: 11))
            .foregroundStyle(Palette.textSecondary)
         }

         Spacer()

         Menu {
            Button("Copy link") {
               NSPasteboard.general.clearContents()
               NSPasteboard.general.setString("https://www.instagram.com/p/\(post.code)/", forType: .string)
            }

            Button("Go to post") {}
            Button("About this account") {}
            Divider()
            Button("Not interested") {}
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

         PostAction(symbolName: "square.and.arrow.up", count: post.shareCount, title: "Share", isActive: false, isCompact: isCompact) {}

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
