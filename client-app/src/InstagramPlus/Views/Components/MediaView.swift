import AppKit
import SwiftUI

struct MediaView: View {
   let seed: String
   var url: URL?
   var label: String?
   var cornerRadius: CGFloat = 14

   var body: some View {
      Group {
         if let localImage = LocalImageCache.image(at: url) {
            Color.clear
               .overlay {
                  Image(nsImage: localImage)
                     .resizable()
                     .scaledToFill()
               }
         } else {
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
      }
      .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
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
