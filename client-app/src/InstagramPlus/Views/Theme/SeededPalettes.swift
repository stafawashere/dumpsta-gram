import SwiftUI

enum SeededPalettes {
   static let avatarTints: [Color] = [
      Color(hex: 0xC9785A),
      Color(hex: 0x6E8C74),
      Color(hex: 0xB89A4E),
      Color(hex: 0x7F72A8),
      Color(hex: 0x4F6A86),
      Color(hex: 0x8A6A5C),
      Color(hex: 0x3F5A4B),
      Color(hex: 0x5B4BC4),
   ]

   static let mediaGradients: [[Color]] = [
      [Color(hex: 0xBFC2BC), Color(hex: 0x8E998A), Color(hex: 0x5C6B50)],
      [Color(hex: 0xF1CBA2), Color(hex: 0xDD9A64), Color(hex: 0x9C5634)],
      [Color(hex: 0x2E4A8C), Color(hex: 0x5A9AD8)],
      [Color(hex: 0xF3B18A), Color(hex: 0xE45F2C)],
      [Color(hex: 0x3F5F2E), Color(hex: 0x8DB05C)],
      [Color(hex: 0xD9D6CF), Color(hex: 0x8E8A84), Color(hex: 0x5A5652)],
   ]

   static func avatarTint(for seed: String) -> Color {
      avatarTints[index(for: seed, count: avatarTints.count)]
   }

   static func mediaGradient(for seed: String) -> [Color] {
      mediaGradients[index(for: seed, count: mediaGradients.count)]
   }

   // String.hashValue is randomised per launch, so colours would reshuffle on every run.
   private static func index(for seed: String, count: Int) -> Int {
      let scalarSum = seed.unicodeScalars.reduce(0) { $0 &+ Int($1.value) }
      return scalarSum % count
   }
}
