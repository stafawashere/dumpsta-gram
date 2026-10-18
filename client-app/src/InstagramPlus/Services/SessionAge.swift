import Foundation

// How the Settings session row words the session's age. The engine's `bootstrapped_at` is the
// only time shown. No cookie, no token and no file path ever reach this text.
enum SessionAge {
   static func describe(refreshedAt: Date?, now: Date = Date()) -> String {
      guard let refreshedAt else {
         return "Not refreshed yet"
      }

      let seconds = max(0, now.timeIntervalSince(refreshedAt))

      switch seconds {
         case ..<60: return "Refreshed just now"
         case ..<3600: return "Refreshed \(Int(seconds / 60)) min ago"
         case ..<86_400: return "Refreshed \(Int(seconds / 3600)) h ago"
         default: return "Refreshed \(Int(seconds / 86_400)) d ago"
      }
   }
}
