import SwiftUI

struct StoryViewer: View {
   @Environment(HomeStore.self) private var home
   @Environment(DirectStore.self) private var direct
   @Environment(NavigationStore.self) private var navigation

   let initialAuthorID: Account.ID

   @State private var authorID: Account.ID?
   @State private var itemIndex = 0
   @State private var progress: Double = 0
   @State private var isPaused = false
   @State private var reply = ""
   @State private var likedAuthorIDs: Set<Account.ID> = []

   private struct Frame: Hashable {
      let authorID: Account.ID
      let itemIndex: Int
   }

   private static let itemDuration: Double = 5
   private static let tick: Double = 0.05

   var body: some View {
      let currentAuthorID = authorID ?? initialAuthorID
      let story = home.stories.first { $0.id == currentAuthorID }

      ZStack(alignment: .topTrailing) {
         Color(hex: 0x111111).opacity(0.97)

         if let story {
            HStack(spacing: 28) {
               StepButton(symbolName: "chevron.left", isHidden: isAtVeryStart(story)) { rewind(story) }

               card(for: story)

               StepButton(symbolName: "chevron.right", isHidden: false) { advance(story) }
            }
            .padding(.vertical, 36)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .task(id: Frame(authorID: story.id, itemIndex: itemIndex)) {
               await play(story)
            }
         }

         OverlayCloseButton { navigation.dismissOverlays() }
            .padding(20)
      }
   }

   private func card(for story: Story) -> some View {
      MediaView(seed: "\(story.id).story.\(itemIndex)", cornerRadius: 12)
         .overlay(alignment: .top) {
            LinearGradient(colors: [.black.opacity(0.45), .clear], startPoint: .top, endPoint: .bottom)
               .frame(height: 120)
         }
         .overlay(alignment: .top) {
            VStack(spacing: 12) {
               HStack(spacing: 4) {
                  ForEach(0..<story.itemCount, id: \.self) { segment in
                     ProgressSegment(fill: segmentFill(segment))
                  }
               }

               HStack(spacing: 10) {
                  Avatar(account: story.author, diameter: 32)

                  Text(story.author.username)
                     .font(.system(size: 14, weight: .semibold))

                  Text(RelativeTime.short(since: story.postedAt))
                     .font(.system(size: 13))
                     .opacity(0.7)

                  Spacer()

                  Button {
                     isPaused.toggle()
                  } label: {
                     Image(systemName: isPaused ? "play.fill" : "pause.fill")
                        .font(.system(size: 14))
                        .frame(width: 28, height: 28)
                        .contentShape(Rectangle())
                  }
                  .buttonStyle(.plain)
                  .keyboardShortcut(.space, modifiers: [])
                  .accessibilityLabel(isPaused ? "Play" : "Pause")
               }
               .foregroundStyle(.white)
            }
            .padding(14)
         }
         .overlay(alignment: .bottom) {
            HStack(spacing: 14) {
               TextField("Reply to \(story.author.username)", text: $reply)
                  .textFieldStyle(.plain)
                  .font(.system(size: 14))
                  .foregroundStyle(.white)
                  .padding(.horizontal, 18)
                  .frame(height: 44)
                  .overlay(Capsule().strokeBorder(.white.opacity(0.6)))
                  .onSubmit { sendReply(to: story) }

               Button {
                  likedAuthorIDs.insert(story.id)
                  Task { await home.likeStory(authorID: story.id) }
               } label: {
                  let isLiked = likedAuthorIDs.contains(story.id)
                  Image(systemName: isLiked ? "heart.fill" : "heart")
                     .foregroundStyle(isLiked ? Color(hex: 0xED4956) : .white)
               }
               .buttonStyle(.plain)
               .accessibilityLabel("Like story")

               Button {
                  sendReply(to: story)
               } label: {
                  Image(systemName: "paperplane")
               }
               .buttonStyle(.plain)
               .accessibilityLabel("Send reply")
            }
            .font(.system(size: 20))
            .foregroundStyle(.white)
            .padding(14)
         }
         .aspectRatio(9 / 16, contentMode: .fit)
         .frame(maxHeight: 760)
   }

   // A story reply is a direct message to the author, so it goes through the same thread.
   private func sendReply(to story: Story) {
      let text = reply.trimmingCharacters(in: .whitespacesAndNewlines)
      reply = ""

      guard !text.isEmpty else {
         return
      }

      Task {
         guard await direct.openThread(with: story.author), let threadID = direct.selectedThreadID else {
            return
         }

         await direct.send("Replied to your story: \(text)", to: threadID)
      }
   }

   private func segmentFill(_ segment: Int) -> Double {
      if segment < itemIndex {
         return 1
      }

      if segment == itemIndex {
         return progress
      }

      return 0
   }

   private func play(_ story: Story) async {
      await home.markStorySeen(authorID: story.id)
      progress = 0

      while progress < 1 {
         try? await Task.sleep(for: .seconds(Self.tick))

         if Task.isCancelled {
            return
         }

         if !isPaused {
            progress = min(1, progress + Self.tick / Self.itemDuration)
         }
      }

      advance(story)
   }

   private func isAtVeryStart(_ story: Story) -> Bool {
      let isFirstStory = home.stories.first?.id == story.id
      let isFirstItem = itemIndex == 0
      return isFirstStory && isFirstItem
   }

   private func advance(_ story: Story) {
      let hasNextItem = itemIndex + 1 < story.itemCount

      if hasNextItem {
         itemIndex += 1
         return
      }

      guard let position = home.stories.firstIndex(where: { $0.id == story.id }) else {
         navigation.dismissOverlays()
         return
      }

      let nextPosition = position + 1
      let hasNextStory = nextPosition < home.stories.count

      if hasNextStory {
         authorID = home.stories[nextPosition].id
         itemIndex = 0
      } else {
         navigation.dismissOverlays()
      }
   }

   private func rewind(_ story: Story) {
      if itemIndex > 0 {
         itemIndex -= 1
         return
      }

      guard let position = home.stories.firstIndex(where: { $0.id == story.id }), position > 0 else {
         progress = 0
         return
      }

      authorID = home.stories[position - 1].id
      itemIndex = 0
   }
}

struct ProgressSegment: View {
   let fill: Double

   var body: some View {
      GeometryReader { proxy in
         Capsule()
            .fill(.white.opacity(0.35))
            .overlay(alignment: .leading) {
               Capsule()
                  .fill(.white)
                  .frame(width: proxy.size.width * fill)
            }
      }
      .frame(height: 2.5)
   }
}

struct StepButton: View {
   let symbolName: String
   let isHidden: Bool
   let action: () -> Void

   var body: some View {
      Button(action: action) {
         Image(systemName: symbolName)
            .font(.system(size: 14, weight: .bold))
            .foregroundStyle(.black)
            .frame(width: 32, height: 32)
            .background(.white.opacity(0.85), in: Circle())
      }
      .buttonStyle(.plain)
      .opacity(isHidden ? 0 : 1)
      .disabled(isHidden)
   }
}
