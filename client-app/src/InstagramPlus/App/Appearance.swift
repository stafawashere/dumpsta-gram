import SwiftUI

enum Appearance: String {
   case system
   case light
   case dark

   static let storageKey = "appearance"

   var colorScheme: ColorScheme? {
      switch self {
         case .system: nil
         case .light: .light
         case .dark: .dark
      }
   }

   static func opposite(of scheme: ColorScheme) -> Appearance {
      scheme == .dark ? .light : .dark
   }
}
