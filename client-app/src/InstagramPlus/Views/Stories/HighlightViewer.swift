import SwiftUI

// The number of items comes from the highlight's reel, which the engine returns whole. The
// highlight row on a profile carries no count.
struct HighlightViewer: View {
   @Environment(NavigationStore.self) private var navigation
   @Environment(ProfileStore.self) private var profiles
   @Environment(HomeStore.self) private var home

   let presented: PresentedHighlight

   @State private var itemIndex = 0
   @State private var progress: Double = 0
   @State private var isPaused = false

   private struct PlaybackKey: Hashable {
      let itemIndex: Int
      let isReady: Bool
   }

   private var highlightID: Highlight.ID { presented.highlight.id }

   private var reel: StoryFrames? { profiles.highlightReel(highlightID) }

   var body: some View {
      ZStack(alignment: .topTrailing) {
         Color(hex: 0x111111).opacity(0.97)

         HStack(spacing: 28) {
            StepButton(symbolName: "chevron.left", isHidden: itemIndex == 0) {
               itemIndex -= 1
            }

            card

            StepButton(symbolName: "chevron.right", isHidden: false) {
               advance()
            }
         }
         .padding(.vertical, 36)
         .frame(maxWidth: .infinity, maxHeight: .infinity)
         .task(id: highlightID) {
            await profiles.loadHighlightReel(highlightID)
         }
         .task(id: PlaybackKey(itemIndex: itemIndex, isReady: reel != nil)) {
            await play()
         }

         OverlayCloseButton { navigation.dismissOverlays() }
            .padding(20)
      }
   }

   private var card: some View {
      let frame = reel.flatMap { $0.frames.indices.contains(itemIndex) ? $0.frames[itemIndex] : nil }

      return MediaView(seed: "\(highlightID).\(itemIndex)", url: frame?.mediaURL, cornerRadius: 12)
         .overlay {
            if reel == nil {
               ReelStatusView(state: profiles.highlightReelState(highlightID), loadingLabel: "Opening highlight", notFoundMessage: "This highlight is no longer available.") {
                  Task { await profiles.loadHighlightReel(highlightID) }
               }
            }
         }
         .overlay(alignment: .top) {
            VStack(spacing: 12) {
               HStack(spacing: 4) {
                  ForEach(0..<(reel?.frames.count ?? 0), id: \.self) { segment in
                     ProgressSegment(fill: segment < itemIndex ? 1 : (segment == itemIndex ? progress : 0))
                  }
               }

               HStack(spacing: 10) {
                  Avatar(account: presented.owner, diameter: 32)

                  Text(presented.highlight.title)
                     .font(.system(size: 14, weight: .semibold))

                  Spacer()

                  Button {
                     isPaused.toggle()
                  } label: {
                     Image(systemName: isPaused ? "play.fill" : "pause.fill")
                        .frame(width: 28, height: 28)
                        .contentShape(Rectangle())
                  }
                  .buttonStyle(.plain)
                  .keyboardShortcut(.space, modifiers: [])
               }
               .foregroundStyle(.white)
            }
            .padding(14)
            .background(LinearGradient(colors: [.black.opacity(0.45), .clear], startPoint: .top, endPoint: .bottom))
         }
         .aspectRatio(9 / 16, contentMode: .fit)
         .frame(maxHeight: 760)
   }

   private func play() async {
      progress = 0

      guard let reel else {
         return
      }

      home.markStoryFrameSeen(in: reel, at: itemIndex)

      while progress < 1 {
         try? await Task.sleep(for: .milliseconds(50))

         if Task.isCancelled {
            return
         }

         if !isPaused {
            progress = min(1, progress + 0.01)
         }
      }

      advance()
   }

   private func advance() {
      let itemCount = reel?.frames.count ?? 0
      let hasNext = itemIndex + 1 < itemCount

      if hasNext {
         itemIndex += 1
      } else {
         navigation.dismissOverlays()
      }
   }
}
