import SwiftUI

struct Hairline: View {
   var axis: Axis = .horizontal

   var body: some View {
      let isHorizontal = axis == .horizontal

      Rectangle()
         .fill(Palette.hairline)
         .frame(width: isHorizontal ? nil : 1, height: isHorizontal ? 1 : nil)
   }
}
