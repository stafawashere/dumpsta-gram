import SwiftUI

// The profile grids. A tile whose engine model has no comment count, as on the saved posts read,
// shows its likes alone on hover and says why.
struct ProfileTileGrid: View {
   let tiles: [ProfileTile]
   var isTall = false

   var body: some View {
      LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 4), count: 3), spacing: 4) {
         ForEach(tiles) { tile in
            ProfileTileView(tile: tile, isTall: isTall)
         }
      }
   }
}

private struct ProfileTileView: View {
   @Environment(NavigationStore.self) private var navigation

   let tile: ProfileTile
   let isTall: Bool

   @State private var isHovered = false

   var body: some View {
      Button {
         navigation.showPost(code: tile.code)
      } label: {
         MediaView(seed: tile.code, cornerRadius: 2)
            .aspectRatio(isTall ? 9 / 16 : 1, contentMode: .fill)
            .overlay(alignment: .topTrailing) {
               if let kindSymbol {
                  Image(systemName: kindSymbol)
                     .font(.system(size: 14, weight: .semibold))
                     .foregroundStyle(.white)
                     .shadow(radius: 3)
                     .padding(10)
               }
            }
            .overlay {
               if isHovered {
                  ZStack {
                     Color.black.opacity(0.35)

                     HStack(spacing: 24) {
                        Label(CompactCount.format(tile.likeCount), systemImage: "heart.fill")

                        if let commentCount = tile.commentCount {
                           Label(CompactCount.format(commentCount), systemImage: "bubble.right.fill")
                        }
                     }
                     .font(.system(size: 15, weight: .bold))
                     .foregroundStyle(.white)
                  }
               }
            }
            .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
      .help(tile.commentCount != nil ? "" : "Instagram+ cannot read yet how many comments a saved post has")
      .onHover { isHovered = $0 }
   }

   private var kindSymbol: String? {
      switch tile.kind {
         case .photo: nil
         case .carousel: "square.fill.on.square.fill"
         case .video: "play.rectangle.fill"
      }
   }
}
