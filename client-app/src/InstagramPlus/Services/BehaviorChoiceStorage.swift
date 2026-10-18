import Foundation

// The person's Behavior choice, kept for the next launch. Each real engine client is opened with
// it, and Settings changes it for every open account at once.
extension Engine.BehaviorChoice {
   static let markThreadsReadKey = "behavior.markThreadsRead"
   static let markStoriesSeenKey = "behavior.markStoriesSeen"

   static func stored(in defaults: UserDefaults = .standard) -> Engine.BehaviorChoice {
      Engine.BehaviorChoice(
         markThreadsRead: defaults.object(forKey: markThreadsReadKey) as? Bool ?? true,
         markStoriesSeen: defaults.object(forKey: markStoriesSeenKey) as? Bool ?? true
      )
   }

   func store(in defaults: UserDefaults = .standard) {
      defaults.set(markThreadsRead, forKey: Self.markThreadsReadKey)
      defaults.set(markStoriesSeen, forKey: Self.markStoriesSeenKey)
   }
}
