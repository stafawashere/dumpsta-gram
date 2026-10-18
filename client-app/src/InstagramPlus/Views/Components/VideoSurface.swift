import AVFoundation
import AVKit
import SwiftUI

// One inline video, muted until the viewer asks for sound. The player is made on the first
// play, so a video that is only scrolled past costs no request.
@MainActor
@Observable
final class InlineVideo {
   let url: URL

   private(set) var player: AVPlayer?
   private(set) var isPlaying = false
   private(set) var progress: Double = 0
   private(set) var hasFailed = false

   var isMuted = true {
      didSet { player?.isMuted = isMuted }
   }

   init(url: URL) {
      self.url = url
   }

   func togglePlayback() {
      if isPlaying {
         pause()
      } else {
         play()
      }
   }

   func play() {
      let activePlayer = player ?? makePlayer()
      player = activePlayer
      activePlayer.isMuted = isMuted
      activePlayer.play()
      isPlaying = true
   }

   func pause() {
      player?.pause()
      isPlaying = false
   }

   // Called on a short timer while playing. Loops at the end, the way the feed does.
   func refreshProgress() {
      guard let player, let item = player.currentItem else {
         return
      }

      if item.status == .failed {
         hasFailed = true
         pause()
         return
      }

      let duration = item.duration.seconds
      let hasDuration = duration.isFinite && duration > 0

      guard hasDuration else {
         return
      }

      progress = min(1, max(0, player.currentTime().seconds / duration))

      let reachedEnd = progress >= 0.999

      if reachedEnd {
         player.seek(to: .zero)
         player.play()
      }
   }

   private func makePlayer() -> AVPlayer {
      let asset = AVURLAsset(url: url, options: [AVURLAssetHTTPCookiesKey: [HTTPCookie]()])
      let player = AVPlayer(playerItem: AVPlayerItem(asset: asset))
      player.actionAtItemEnd = .pause
      return player
   }
}

struct VideoSurface: NSViewRepresentable {
   let player: AVPlayer

   func makeNSView(context: Context) -> AVPlayerView {
      let view = AVPlayerView()
      view.controlsStyle = .none
      view.videoGravity = .resizeAspectFill
      view.player = player
      return view
   }

   func updateNSView(_ view: AVPlayerView, context: Context) {
      if view.player !== player {
         view.player = player
      }
   }
}

// The play badge, progress bar and mute button drawn over a video, real or placeholder.
struct VideoOverlay: View {
   let isPlaying: Bool
   let progress: Double
   let hasFailed: Bool
   var isMuted: Bool?
   var onToggleMute: (() -> Void)?

   var body: some View {
      ZStack {
         if hasFailed {
            VStack(spacing: 6) {
               Image(systemName: "exclamationmark.triangle")
                  .font(.system(size: 22, weight: .semibold))

               Text("Video could not play")
                  .font(.system(size: 12, weight: .medium))
            }
            .foregroundStyle(.white.opacity(0.9))
            .shadow(radius: 6)
         } else if !isPlaying {
            Image(systemName: "play.fill")
               .font(.system(size: 40))
               .foregroundStyle(.white.opacity(0.92))
               .shadow(radius: 8)
         }

         VStack {
            Spacer()

            HStack {
               Spacer()

               if let isMuted, let onToggleMute {
                  Button(action: onToggleMute) {
                     Image(systemName: isMuted ? "speaker.slash.fill" : "speaker.wave.2.fill")
                        .font(.system(size: 12))
                        .foregroundStyle(.white)
                        .frame(width: 30, height: 30)
                        .background(.black.opacity(0.4), in: Circle())
                  }
                  .buttonStyle(.plain)
                  .padding(12)
                  .accessibilityLabel(isMuted ? "Unmute" : "Mute")
               }
            }

            GeometryReader { proxy in
               Capsule()
                  .fill(.white.opacity(0.3))
                  .overlay(alignment: .leading) {
                     Capsule()
                        .fill(.white)
                        .frame(width: proxy.size.width * progress)
                  }
            }
            .frame(height: 3)
            .padding(14)
         }
      }
   }
}
