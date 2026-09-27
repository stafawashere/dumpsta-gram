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
      let isSoft = style == .soft
      let fill = isSoft ? Palette.softAvatarFill : SeededPalettes.avatarTint(for: account.id)
      let initialsColor = isSoft ? Palette.softAvatarText : Color.white

      Circle()
         .fill(fill)
         .overlay {
            Text(account.initials)
               .font(.system(size: diameter * 0.34, weight: .semibold))
               .foregroundStyle(initialsColor)
         }
         .frame(width: diameter, height: diameter)
         .accessibilityLabel(account.displayName)
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
