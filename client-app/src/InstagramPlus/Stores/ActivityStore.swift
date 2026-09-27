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

@MainActor
@Observable
final class ActivityStore {
   let gateway: EngineGateway

   private(set) var state = LoadState.idle
   private(set) var items: [ActivityItem] = []
   private(set) var followRequests: [Account] = []
   private(set) var pendingRequestIDs: Set<Account.ID> = []
   private(set) var hasUnread = true

   init(gateway: EngineGateway) {
      self.gateway = gateway
   }

   func load() async {
      state = .loading

      let engine = gateway.client
      switch await gateway.read("activity", { () async throws(EngineError) in try await engine.activity() }) {
         case .success(let entries):
            items = entries.map(ActivityItem.init)
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
