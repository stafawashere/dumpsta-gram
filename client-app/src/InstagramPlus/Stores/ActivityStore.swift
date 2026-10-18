import Foundation
import Observation

enum ActivityFilter: String, CaseIterable, Identifiable {
   case all
   case follows
   case comments
   case likes

   var id: String { rawValue }

   var title: String {
      switch self {
         case .all: "All"
         case .follows: "Follows"
         case .comments: "Comments"
         case .likes: "Likes"
      }
   }

   func includes(_ kind: ActivityItem.Kind) -> Bool {
      switch (self, kind) {
         case (.all, _): true
         case (.follows, .followed): true
         case (.comments, .commented), (.comments, .mentioned): true
         case (.likes, .likedPost), (.likes, .likedComment): true
         default: false
      }
   }
}

// An activity row the engine reports only by the upstream's own kind string. It is shown with
// the engine's own line, and only under All, because sorting it by kind would take Instagram
// knowledge the engine does not expose.
struct UntypedActivity: Identifiable, Hashable, Sendable {
   let id: String
   let rawKind: String
   let text: String
   let actor: Account?
   let occurredAt: Date
   let mediaCode: String?
}

@MainActor
@Observable
final class ActivityStore {
   let gateway: EngineGateway

   private(set) var state = LoadState.idle
   private(set) var items: [ActivityItem] = []
   private(set) var untypedItems: [UntypedActivity] = []
   private(set) var followRequests: [Account] = []
   private(set) var pendingRequestIDs: Set<Account.ID> = []

   // False until a read of the feed says there is something unseen. The engine has no write to
   // mark the feed seen, so markSeen only clears the dot on this Mac.
   private(set) var hasUnread = false

   // What the last read of the feed said, which markSeen leaves alone. Nil before a read.
   private(set) var engineReportsUnseen: Bool?

   init(gateway: EngineGateway) {
      self.gateway = gateway
   }

   func load() async {
      state = .loading

      let engine = gateway.client
      switch await gateway.read("activity", { () async throws(EngineError) in try await engine.activityFeed() }) {
         case .success(let feed):
            items = feed.entries.map(ActivityItem.init)
            untypedItems = feed.untyped.map(UntypedActivity.init)
            hasUnread = feed.hasUnseen ?? false
            engineReportsUnseen = feed.hasUnseen
            state = .loaded

         case .failure(let error):
            state = .failed(HomeStore.describe(error))
            return

         case .halted:
            state = .idle
            return
      }

      if case .success(let requests) = await gateway.read("follow requests", { () async throws(EngineError) in try await engine.followRequests() }) {
         followRequests = requests.map(Account.init)
      }
   }

   func markSeen() {
      hasUnread = false
   }

   func resolveRequest(from accountID: Account.ID, approve: Bool) async {
      pendingRequestIDs.insert(accountID)
      defer { pendingRequestIDs.remove(accountID) }

      let engine = gateway.client
      let outcome = await gateway.write(approve ? "the approval" : "the request removal") { () async throws(EngineError) in
         try await engine.resolveFollowRequest(userID: accountID, approve: approve)
      }

      if case .success = outcome {
         followRequests.removeAll { $0.id == accountID }
      }
   }
}
