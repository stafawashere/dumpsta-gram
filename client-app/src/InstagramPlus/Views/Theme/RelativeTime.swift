import Foundation

enum RelativeTime {
   static func short(since date: Date, now: Date = .now) -> String {
      let seconds = max(0, Int(now.timeIntervalSince(date)))
      let minutes = seconds / 60
      let hours = minutes / 60
      let days = hours / 24
      let weeks = days / 7

      if minutes < 1 {
         return "now"
      }

      if hours < 1 {
         return "\(minutes)m"
      }

      if days < 1 {
         return "\(hours)h"
      }

      if weeks < 1 {
         return "\(days)d"
      }

      return "\(weeks)w"
   }
}
