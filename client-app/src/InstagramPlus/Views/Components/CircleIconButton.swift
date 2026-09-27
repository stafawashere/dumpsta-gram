import SwiftUI

struct CircleIconButton: View {
   let symbolName: String
   let accessibilityTitle: String
   var indicatorColor: Color?
   var action: () -> Void = {}

   var body: some View {
      Button(action: action) {
         Image(systemName: symbolName)
            .font(.system(size: 15, weight: .regular))
            .foregroundStyle(Palette.textPrimary)
            .frame(width: 42, height: 42)
            .background(Palette.panel, in: Circle())
            .overlay(Circle().strokeBorder(Palette.hairline))
            .overlay(alignment: .topTrailing) {
               if let indicatorColor {
                  Circle()
                     .fill(indicatorColor)
                     .frame(width: 8, height: 8)
                     .offset(x: -9, y: 9)
               }
            }
            .contentShape(Circle())
      }
      .buttonStyle(.plain)
      .accessibilityLabel(accessibilityTitle)
   }
}
