import Foundation
import Observation

// Everything that belongs to one signed-in account. The engine is instance scoped, so a second
// account is a second engine client with its own stores, never shared state.
@MainActor
final class AccountSession: Identifiable {
   let id: String
   let gateway: EngineGateway
   let navigation = NavigationStore()
   let home: HomeStore
   let direct: DirectStore
   let activity: ActivityStore
   let reels: ReelsStore
   let search: SearchStore
   let profiles: ProfileStore

   init(engine: DummyEngine) {
      let gateway = EngineGateway(engine: engine)

      self.id = engine.viewerID
      self.gateway = gateway
      self.home = HomeStore(gateway: gateway)
      self.direct = DirectStore(gateway: gateway)
      self.activity = ActivityStore(gateway: gateway)
      self.reels = ReelsStore(gateway: gateway)
      self.search = SearchStore(gateway: gateway)
      self.profiles = ProfileStore(gateway: gateway)
   }

   func suspend() async {
      await direct.stopListening()
   }
}

@MainActor
@Observable
final class AccountsStore {
   enum AvailableAccount: String, CaseIterable {
      case primary
      case studio

      func makeEngine(timing: DummyEngine.Timing) -> DummyEngine {
         switch self {
            case .primary: DummyEngine(timing: timing, world: .seed())
            case .studio: DummyEngine(timing: timing, world: .seedStudio())
         }
      }
   }

   private(set) var sessions: [AccountSession]
   private(set) var activeID: AccountSession.ID
   private let timing: DummyEngine.Timing

   init(timing: DummyEngine.Timing) {
      let primary = AccountSession(engine: AvailableAccount.primary.makeEngine(timing: timing))
      self.timing = timing
      self.sessions = [primary]
      self.activeID = primary.id
   }

   var active: AccountSession {
      sessions.first { $0.id == activeID } ?? sessions[0]
   }

   var canAddAccount: Bool {
      sessions.count < AvailableAccount.allCases.count
   }

   func switchTo(_ sessionID: AccountSession.ID) async {
      guard sessionID != activeID, sessions.contains(where: { $0.id == sessionID }) else {
         return
      }

      await active.suspend()
      activeID = sessionID
   }

   // In the dummy, adding an account signs in the next seeded one. With the bridge it adopts a
   // second browser session through the same setup screen.
   func addAccount() async {
      let usedCount = sessions.count
      guard usedCount < AvailableAccount.allCases.count else {
         return
      }

      let next = AvailableAccount.allCases[usedCount]
      let session = AccountSession(engine: next.makeEngine(timing: timing))
      sessions.append(session)
      await switchTo(session.id)
   }

   func remove(_ sessionID: AccountSession.ID) async {
      let isLastAccount = sessions.count == 1
      guard !isLastAccount, let session = sessions.first(where: { $0.id == sessionID }) else {
         return
      }

      await session.suspend()
      sessions.removeAll { $0.id == sessionID }

      if activeID == sessionID {
         activeID = sessions[0].id
      }
   }
}
