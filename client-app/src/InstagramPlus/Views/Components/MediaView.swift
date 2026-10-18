import AppKit
import SwiftUI

// Shows a file the app holds, or an https address the engine handed over. Anything else, such
// as the dummy engine's addresses, falls back to the seeded placeholder without a request.
struct MediaView: View {
   let seed: String
   var url: URL?
   var label: String?
   var cornerRadius: CGFloat = 14

   var body: some View {
      Group {
         if let localImage = LocalImageCache.image(at: url) {
            filled(with: localImage)
         } else if let url, MediaLoader.isRemote(url) {
            RemoteImage(url: url) { image in
               filled(with: image)
            } placeholder: { phase in
               placeholder
                  .overlay {
                     remoteStatus(for: phase)
                  }
            }
         } else {
            placeholder
         }
      }
      .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
   }

   private func filled(with image: NSImage) -> some View {
      Color.clear
         .overlay {
            Image(nsImage: image)
               .resizable()
               .scaledToFill()
         }
   }

   private var placeholder: some View {
      LinearGradient(
         colors: SeededPalettes.mediaGradient(for: seed),
         startPoint: .topLeading,
         endPoint: .bottomTrailing
      )
      .overlay(alignment: .bottomLeading) {
         if let label {
            Text(label)
               .font(.system(size: 11, design: .monospaced))
               .foregroundStyle(.white.opacity(0.8))
               .padding(14)
         }
      }
   }

   @ViewBuilder
   private func remoteStatus(for phase: RemoteImagePhase) -> some View {
      switch phase {
         case .loading:
            ProgressView()
               .controlSize(.small)
               .tint(.white)

         case .failed:
            VStack(spacing: 6) {
               Image(systemName: "exclamationmark.triangle")
                  .font(.system(size: 18, weight: .semibold))

               Text("Media could not load")
                  .font(.system(size: 11, weight: .medium))
            }
            .foregroundStyle(.white.opacity(0.9))
            .accessibilityElement(children: .combine)
      }
   }
}

// Loads one remote image through MediaLoader and hands the caller either the image or the
// phase it is stuck in, so every caller draws its own placeholder and failure state.
enum RemoteImagePhase {
   case loading
   case failed
}

struct RemoteImage<Content: View, Placeholder: View>: View {
   let url: URL
   @ViewBuilder let content: (NSImage) -> Content
   @ViewBuilder let placeholder: (RemoteImagePhase) -> Placeholder

   @State private var loadedImage: NSImage?
   @State private var phase: RemoteImagePhase = .loading

   var body: some View {
      Group {
         if let shownImage = loadedImage ?? MediaLoader.shared.cachedImage(for: url) {
            content(shownImage)
         } else {
            placeholder(MediaLoader.shared.hasFailed(url) ? .failed : phase)
         }
      }
      .task(id: url) {
         loadedImage = nil
         phase = .loading

         switch await MediaLoader.shared.image(for: url) {
            case .loaded(let image):
               loadedImage = image

            case .failed:
               phase = .failed
         }
      }
   }
}

@MainActor
enum LocalImageCache {
   private static var images: [URL: NSImage] = [:]

   static func image(at url: URL?) -> NSImage? {
      guard let url, url.isFileURL else {
         return nil
      }

      if let cached = images[url] {
         return cached
      }

      let loaded = NSImage(contentsOf: url)
      images[url] = loaded
      return loaded
   }
}
