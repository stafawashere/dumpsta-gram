enum CompactCount {
   static func format(_ count: Int) -> String {
      let isMillions = count >= 1_000_000
      let isThousands = count >= 1_000

      if isMillions {
         return trimmed(Double(count) / 1_000_000) + "m"
      }

      if isThousands {
         return trimmed(Double(count) / 1_000) + "k"
      }

      return String(count)
   }

   private static func trimmed(_ value: Double) -> String {
      let rounded = (value * 10).rounded() / 10
      let isWhole = rounded == rounded.rounded()

      return isWhole ? String(Int(rounded)) : String(format: "%.1f", rounded)
   }
}
