import SwiftUI

struct InstagramGlyph: View {
   var body: some View {
      GeometryReader { proxy in
         let side = min(proxy.size.width, proxy.size.height)
         let strokeWidth = side * 0.08

         ZStack {
            RoundedRectangle(cornerRadius: side * 0.26, style: .continuous)
               .fill(Self.brandGradient(side: side))

            RoundedRectangle(cornerRadius: side * 0.19, style: .continuous)
               .strokeBorder(.white, lineWidth: strokeWidth)
               .frame(width: side * 0.64, height: side * 0.64)

            Circle()
               .strokeBorder(.white, lineWidth: strokeWidth)
               .frame(width: side * 0.32, height: side * 0.32)

            Circle()
               .fill(.white)
               .frame(width: side * 0.085, height: side * 0.085)
               .position(x: side * 0.69, y: side * 0.31)
         }
         .frame(width: side, height: side)
      }
      .aspectRatio(1, contentMode: .fit)
   }

   // The brand's published gradient, circle at 30% 107% out to the farthest corner.
   static func brandGradient(side: CGFloat) -> RadialGradient {
      let farthestCornerDistance = side * hypot(0.7, 1.07)

      return RadialGradient(
         stops: [
            .init(color: Color(hex: 0xFDF497), location: 0.00),
            .init(color: Color(hex: 0xFDF497), location: 0.05),
            .init(color: Color(hex: 0xFD5949), location: 0.45),
            .init(color: Color(hex: 0xD6249F), location: 0.60),
            .init(color: Color(hex: 0x285AEB), location: 0.90),
         ],
         center: UnitPoint(x: 0.30, y: 1.07),
         startRadius: 0,
         endRadius: farthestCornerDistance
      )
   }
}
