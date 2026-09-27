import AppKit
import SwiftUI

extension NSColor {
   convenience init(hex: UInt32, alpha: CGFloat = 1) {
      let red = CGFloat((hex >> 16) & 0xFF) / 255
      let green = CGFloat((hex >> 8) & 0xFF) / 255
      let blue = CGFloat(hex & 0xFF) / 255
      self.init(srgbRed: red, green: green, blue: blue, alpha: alpha)
   }
}

extension Color {
   init(hex: UInt32) {
      self.init(nsColor: NSColor(hex: hex))
   }

   init(light: UInt32, dark: UInt32) {
      let lightColor = NSColor(hex: light)
      let darkColor = NSColor(hex: dark)

      let adaptiveColor = NSColor(name: nil) { appearance in
         let matchedAppearance = appearance.bestMatch(from: [.aqua, .darkAqua])
         let isDark = matchedAppearance == .darkAqua
         return isDark ? darkColor : lightColor
      }

      self.init(nsColor: adaptiveColor)
   }
}

enum Palette {
   static let window = Color(light: 0xF1F0EE, dark: 0x0D0D0F)
   static let panel = Color(light: 0xFFFFFF, dark: 0x18171A)
   static let canvas = Color(light: 0xF8F7F5, dark: 0x141316)
   static let card = Color(light: 0xFFFFFF, dark: 0x19181B)
   static let raised = Color(light: 0xF7F6F4, dark: 0x1F1E22)
   static let field = Color(light: 0xF6F5F3, dark: 0x141316)
   static let hairline = Color(light: 0xECEAE6, dark: 0x2A282D)

   static let textPrimary = Color(light: 0x1E1C1A, dark: 0xF3F1EF)
   static let textSecondary = Color(light: 0x8B8680, dark: 0x8F8B93)
   static let textTertiary = Color(light: 0xAAA59F, dark: 0x6C6870)

   static let accent = Color(light: 0xC2477A, dark: 0xE0689A)
   static let online = Color(hex: 0x3DBE6A)
   static let badge = Color(hex: 0xE5484D)
   static let link = Color(light: 0x0095F6, dark: 0x4CB5F9)
   static let primaryButton = Color(hex: 0x0095F6)

   static let outgoingBubble = Color(hex: 0x4A5DF9)
   static let incomingBubble = Color(light: 0xEFEEEC, dark: 0x262529)

   static let softAvatarFill = Color(hex: 0xF7DCCB)
   static let softAvatarText = Color(hex: 0xC0623F)

   static let createGradient = LinearGradient(
      colors: [Color(hex: 0xEE5A6F), Color(hex: 0xA24FB6)],
      startPoint: .leading,
      endPoint: .trailing
   )

   static let storyRing = LinearGradient(
      colors: [Color(hex: 0xFEDA75), Color(hex: 0xFA7E1E), Color(hex: 0xD62976), Color(hex: 0x962FBF)],
      startPoint: .bottomLeading,
      endPoint: .topTrailing
   )
}
