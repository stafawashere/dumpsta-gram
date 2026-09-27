import SwiftUI

struct BrandMark: View {
   var body: some View {
      HStack(spacing: 10) {
         InstagramGlyph()
            .frame(width: 30, height: 30)

         Text("Instagram+")
            .font(.system(size: 22, weight: .bold))
            .foregroundStyle(Palette.textPrimary)
      }
      .accessibilityElement(children: .combine)
   }
}
