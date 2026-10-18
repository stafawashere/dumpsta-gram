import SwiftUI

struct Avatar: View {
   enum Style {
      case solid
      case soft
   }

   let account: Account
   var diameter: CGFloat = 40
   var style: Style = .solid

   var body: some View {
      Group {
         if let pictureURL, MediaLoader.isRemote(pictureURL) {
            RemoteImage(url: pictureURL) { image in
               Image(nsImage: image)
                  .resizable()
                  .scaledToFill()
            } placeholder: { phase in
               initialsCircle
                  .opacity(phase == .loading ? 0.6 : 1)
                  .help(phase == .failed ? "The profile picture could not load" : "")
            }
         } else {
            initialsCircle
         }
      }
      .frame(width: diameter, height: diameter)
      .clipShape(Circle())
      .accessibilityLabel(account.displayName)
   }

   private var pictureURL: URL? {
      account.profilePicURL.flatMap(URL.init(string:))
   }

   private var initialsCircle: some View {
      let isSoft = style == .soft
      let fill = isSoft ? Palette.softAvatarFill : SeededPalettes.avatarTint(for: account.id)
      let initialsColor = isSoft ? Palette.softAvatarText : Color.white

      return Circle()
         .fill(fill)
         .overlay {
            Text(account.initials)
               .font(.system(size: diameter * 0.34, weight: .semibold))
               .foregroundStyle(initialsColor)
         }
   }
}

struct RingedAvatar: View {
   let account: Account
   var diameter: CGFloat = 76
   var style: Avatar.Style = .solid
   var showsRing = true

   var body: some View {
      let ringWidth: CGFloat = 2
      let ringGap: CGFloat = 3
      let innerDiameter = diameter - (ringWidth + ringGap) * 2

      ZStack {
         if showsRing {
            Circle()
               .strokeBorder(Palette.storyRing, lineWidth: ringWidth)
         } else {
            Circle()
               .strokeBorder(Palette.hairline, lineWidth: ringWidth)
         }

         Avatar(account: account, diameter: innerDiameter, style: style)
      }
      .frame(width: diameter, height: diameter)
   }
}
