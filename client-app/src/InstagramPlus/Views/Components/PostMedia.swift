import SwiftUI

// A post's media: one image, a carousel with its own page state, or a video that plays and
// pauses in place. The dummy engine has no video bytes, so playback is a timeline over the
// placeholder rather than an AVPlayer.
struct PostMedia: View {
   let post: Post
   var cornerRadius: CGFloat = 14
   var onOpen: (() -> Void)?

   @State private var page = 0
   @State private var isPlaying = false
   @State private var playhead: Double = 0

   var body: some View {
      let pageCount = post.kind == .carousel ? max(2, post.carouselCount ?? 3) : 1
      let seed = page == 0 ? post.mediaSeed : "\(post.mediaSeed).\(page)"
      let usesLocalImage = page == 0
      let label = post.mediaDescription.isEmpty ? nil : post.mediaDescription

      MediaView(seed: seed, url: usesLocalImage ? post.mediaURL : nil, label: page == 0 ? label : nil, cornerRadius: cornerRadius)
         .contentShape(Rectangle())
         .onTapGesture(count: 2) {
            onOpen?()
         }
         .overlay {
            if post.kind == .video {
               videoControls
            }
         }
         .overlay(alignment: .topTrailing) {
            if pageCount > 1 {
               Text("\(page + 1)/\(pageCount)")
                  .font(.system(size: 11, weight: .semibold))
                  .foregroundStyle(.white)
                  .padding(.horizontal, 8)
                  .padding(.vertical, 4)
                  .background(.black.opacity(0.5), in: Capsule())
                  .padding(12)
            }
         }
         .overlay {
            if pageCount > 1 {
               carouselControls(pageCount: pageCount)
            }
         }
   }

   private func carouselControls(pageCount: Int) -> some View {
      let canGoBack = page > 0
      let canGoForward = page + 1 < pageCount

      return ZStack {
         HStack {
            PagerButton(symbolName: "chevron.left", isHidden: !canGoBack) {
               withAnimation(.easeOut(duration: 0.2)) { page -= 1 }
            }

            Spacer()

            PagerButton(symbolName: "chevron.right", isHidden: !canGoForward) {
               withAnimation(.easeOut(duration: 0.2)) { page += 1 }
            }
         }
         .padding(.horizontal, 12)

         VStack {
            Spacer()

            HStack(spacing: 5) {
               ForEach(0..<pageCount, id: \.self) { index in
                  Circle()
                     .fill(index == page ? Color.white : Color.white.opacity(0.45))
                     .frame(width: 6, height: 6)
               }
            }
            .padding(.bottom, 14)
         }
      }
   }

   private var videoControls: some View {
      ZStack {
         if !isPlaying {
            Image(systemName: "play.fill")
               .font(.system(size: 40))
               .foregroundStyle(.white.opacity(0.92))
               .shadow(radius: 8)
         }

         VStack {
            Spacer()

            GeometryReader { proxy in
               Capsule()
                  .fill(.white.opacity(0.3))
                  .overlay(alignment: .leading) {
                     Capsule()
                        .fill(.white)
                        .frame(width: proxy.size.width * playhead)
                  }
            }
            .frame(height: 3)
            .padding(14)
         }
      }
      .contentShape(Rectangle())
      .onTapGesture {
         isPlaying.toggle()
      }
      .task(id: isPlaying) {
         while isPlaying, !Task.isCancelled {
            try? await Task.sleep(for: .milliseconds(100))
            playhead = playhead >= 1 ? 0 : playhead + 0.01
         }
      }
      .accessibilityLabel(isPlaying ? "Pause" : "Play")
   }
}

private struct PagerButton: View {
   let symbolName: String
   let isHidden: Bool
   let action: () -> Void

   var body: some View {
      Button(action: action) {
         Image(systemName: symbolName)
            .font(.system(size: 12, weight: .bold))
            .foregroundStyle(.black)
            .frame(width: 28, height: 28)
            .background(.white.opacity(0.85), in: Circle())
      }
      .buttonStyle(.plain)
      .opacity(isHidden ? 0 : 1)
      .disabled(isHidden)
   }
}

// Captions with #tags and @mentions that open their pages.
struct CaptionText: View {
   @Environment(NavigationStore.self) private var navigation
   @Environment(ProfileStore.self) private var profiles

   let text: String
   var leadingUsername: String?
   var size: CGFloat = 15

   var body: some View {
      Text(attributed)
         .font(.system(size: size))
         .foregroundStyle(Palette.textPrimary)
         .tint(Palette.link)
         .environment(\.openURL, OpenURLAction { url in
            open(url)
            return .handled
         })
   }

   private var attributed: AttributedString {
      var result = AttributedString()

      if let leadingUsername {
         var name = AttributedString(leadingUsername + " ")
         name.font = .system(size: size, weight: .semibold)
         result += name
      }

      let words = text.split(separator: " ", omittingEmptySubsequences: false)

      for (position, word) in words.enumerated() {
         var piece = AttributedString(String(word))
         let isTag = word.hasPrefix("#") && word.count > 1
         let isMention = word.hasPrefix("@") && word.count > 1

         if isTag || isMention {
            let value = word.dropFirst().trimmingCharacters(in: .punctuationCharacters)
            let host = isTag ? "tag" : "user"
            piece.link = URL(string: "instagramplus://\(host)/\(value)")
         }

         result += piece

         if position + 1 < words.count {
            result += AttributedString(" ")
         }
      }

      return result
   }

   private func open(_ url: URL) {
      let value = url.lastPathComponent

      switch url.host() {
         case "tag":
            navigation.dismissOverlays()
            navigation.route = .hashtag(value.lowercased())

         case "user":
            Task {
               if let accountID = await profiles.resolve(username: value) {
                  navigation.openProfile(accountID)
               }
            }

         default:
            break
      }
   }
}
