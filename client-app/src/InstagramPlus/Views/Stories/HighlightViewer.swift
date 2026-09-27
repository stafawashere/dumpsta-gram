import SwiftUI

struct HighlightViewer: View {
   @Environment(NavigationStore.self) private var navigation

   let presented: PresentedHighlight

   @State private var itemIndex = 0
   @State private var progress: Double = 0
   @State private var isPaused = false

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
         .task(id: itemIndex) {
            await play()
         }

         OverlayCloseButton { navigation.dismissOverlays() }
            .padding(20)
      }
   }

   private var card: some View {
      MediaView(seed: "\(presented.highlight.id).\(itemIndex)", cornerRadius: 12)
         .overlay(alignment: .top) {
            VStack(spacing: 12) {
               HStack(spacing: 4) {
                  ForEach(0..<presented.itemCount, id: \.self) { segment in
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
      let hasNext = itemIndex + 1 < presented.itemCount

      if hasNext {
         itemIndex += 1
      } else {
         navigation.dismissOverlays()
      }
   }
}
