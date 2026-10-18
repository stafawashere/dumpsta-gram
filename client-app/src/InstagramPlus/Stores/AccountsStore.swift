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

   // The file the engine saved this account's session to. Removing the account deletes it.
   let sessionFile: URL?

   init(engine: any AppEngine, session: SessionState = .active, sessionFile: URL? = nil) {
      let gateway = EngineGateway(engine: engine, session: session)

      self.id = engine.viewerID
      self.sessionFile = sessionFile
      self.gateway = gateway
      self.home = HomeStore(gateway: gateway)
      self.direct = DirectStore(gateway: gateway)
      self.activity = ActivityStore(gateway: gateway)
      self.reels = ReelsStore(gateway: gateway)
      self.search = SearchStore(gateway: gateway)
      self.profiles = ProfileStore(gateway: gateway)
   }

   // The listener belongs to the active account only. It stops when another account takes
   // over and starts again, through the gateway, when this one is active again.
   func suspend() async {
      await direct.stopListening()
   }

   func resume() async {
      await direct.resumeListening()
   }

   func close() async {
      await suspend()
      await gateway.engine.close()
   }
}

// Makes one engine client per account session (ADR-0004). The dummy serves two seeded
// accounts. The real engine serves one account per saved browser session, opened at launch,
// and one more for each session a person connects through the setup screen.
enum AccountEngineSource {
   case dummy(DummyEngine.Timing)
   case real(RealEngineLaunch)
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
   private let source: AccountEngineSource

   // Set while the setup screen is open to connect one more account on the real engine.
   var isAddingAccount = false

   convenience init(timing: DummyEngine.Timing) {
      self.init(source: .dummy(timing))
   }

   init(source: AccountEngineSource) {
      let initial: [AccountSession] = switch source {
         case .dummy(let timing):
            [Self.makeDummySession(.primary, timing: timing)]

         case .real(let launch) where launch.engines.isEmpty:
            // No adopted session. The setup screen shows, and the unopened client answers every
            // call as signed out until a session is connected.
            [AccountSession(engine: PythonEngine(bridge: .shared, opened: nil, sessionFile: nil, enabled: []), session: .signedOut)]

         case .real(let launch):
            launch.engines.map { AccountSession(engine: $0, sessionFile: $0.sessionFile) }
      }

      self.source = source
      self.sessions = initial
      self.activeID = initial[0].id

      guard case .real(let launch) = source else {
         return
      }

      if launch.bootstrap == nil {
         print("[engine] the runtime did not start, showing how to build it")
      } else if launch.engines.isEmpty {
         print("[engine] no account session open, showing the session setup")
      }

      let isSetupExplanation = launch.bootstrap != nil && launch.engines.isEmpty

      if let problem = launch.problem, !isSetupExplanation {
         initial[0].gateway.post(Notice(tone: .warning, title: "Real engine", message: problem))
      }
   }

   var active: AccountSession {
      sessions.first { $0.id == activeID } ?? sessions[0]
   }

   var isRealEngine: Bool {
      if case .real = source {
         return true
      }

      return false
   }

   // Why the real engine could not start, when its embedded runtime is missing or broken.
   var runtimeProblem: String? {
      guard case .real(let launch) = source, launch.bootstrap == nil else {
         return nil
      }

      return launch.problem ?? "The embedded Python runtime did not start."
   }

   private var hasSignedInAccount: Bool {
      sessions.contains { !$0.id.isEmpty }
   }

   // The setup screen's cookies, handed to the engine to build, save and open a Session in its
   // own file. The values live only in the material passed down and in the engine's owner-only
   // session file. A checkpoint lands in the same state a later call would produce. When a
   // second account is being added, a refusal is reported back to the setup screen and leaves
   // the account already in use untouched.
   func adoptBrowserSession(sessionID: String, userID: String, csrfToken: String) async -> String? {
      guard case .real(let launch) = source else {
         return nil
      }

      let material = PythonBridge.CookieMaterial(
         sessionID: sessionID.trimmingCharacters(in: .whitespacesAndNewlines),
         userID: userID.trimmingCharacters(in: .whitespacesAndNewlines),
         csrfToken: csrfToken.trimmingCharacters(in: .whitespacesAndNewlines),
         extraCookies: [:]
      )

      let isAddingToSignedIn = isAddingAccount && hasSignedInAccount

      switch await PythonEngineFactory.adopt(material, enabled: launch.enabled) {
         case .adopted(let engine):
            await install(engine, session: .active)
            return nil

         case .checkpoint(let engine, let checkpoint):
            await install(engine, session: .checkpoint(checkpoint))
            return nil

         case .revoked where isAddingToSignedIn:
            return "Instagram refused this session. Sign in again in the browser and copy fresh cookies."

         case .revoked:
            active.gateway.handle(.authenticationFailed, label: "the session", isWrite: false)
            return nil

         case .failed(let problem) where isAddingToSignedIn:
            return problem.description

         case .failed(let problem):
            active.gateway.post(Notice(tone: .error, title: "Could not connect the session", message: problem.description))
            return nil
      }
   }

   // The adopted account replaces the unopened placeholder and any earlier session of the same
   // account, and becomes the active one. Every other account keeps its own client.
   private func install(_ engine: PythonEngine, session state: SessionState) async {
      let adopted = AccountSession(engine: engine, session: state, sessionFile: engine.sessionFile)
      let replaced = sessions.filter { $0.id == adopted.id || $0.id.isEmpty }
      let isActiveReplaced = replaced.contains { $0.id == activeID }

      if !isActiveReplaced {
         await active.suspend()
      }

      for session in replaced {
         await session.close()
      }

      sessions.removeAll { session in replaced.contains { $0 === session } }
      sessions.append(adopted)
      activeID = adopted.id
      isAddingAccount = false
   }

   var canAddAccount: Bool {
      switch source {
         case .dummy:
            sessions.count < AvailableAccount.allCases.count

         case .real:
            runtimeProblem == nil && hasSignedInAccount
      }
   }

   func switchTo(_ sessionID: AccountSession.ID) async {
      guard sessionID != activeID, sessions.contains(where: { $0.id == sessionID }) else {
         return
      }

      await active.suspend()
      activeID = sessionID
      await active.resume()
   }

   // In the dummy, adding an account signs in the next seeded one. On the real engine it opens
   // the setup screen, and the session connected there becomes a new account with its own client.
   func addAccount() async {
      guard case .dummy(let timing) = source else {
         isAddingAccount = canAddAccount
         return
      }

      let usedCount = sessions.count
      guard usedCount < AvailableAccount.allCases.count else {
         return
      }

      let next = AvailableAccount.allCases[usedCount]
      let session = Self.makeDummySession(next, timing: timing)
      sessions.append(session)
      await switchTo(session.id)
   }

   // Closes that account's client through the engine, then deletes that account's own session
   // file, which holds the tokens the person asked to drop. Every other file stays.
   func remove(_ sessionID: AccountSession.ID) async {
      let isLastAccount = sessions.count == 1
      guard !isLastAccount, let session = sessions.first(where: { $0.id == sessionID }) else {
         return
      }

      let wasActive = activeID == sessionID

      await session.close()
      deleteSessionFile(of: session)
      sessions.removeAll { $0.id == sessionID }

      if wasActive {
         activeID = sessions[0].id
         await active.resume()
      }
   }
}

extension AccountsStore {
   // The dummy writes no session files. Under --exercise each dummy account is given one in the
   // exercise's own directory, so the harness can check that removing an account deletes it.
   fileprivate static func makeDummySession(_ account: AvailableAccount, timing: DummyEngine.Timing) -> AccountSession {
      let engine = account.makeEngine(timing: timing)
      let isExerciseRun = ProcessInfo.processInfo.arguments.contains("--exercise")
      let sessionFile = isExerciseRun ? PythonEngineFactory.sessionFile(for: engine.viewerID) : nil

      return AccountSession(engine: engine, sessionFile: sessionFile)
   }

   fileprivate func deleteSessionFile(of session: AccountSession) {
      guard let sessionFile = session.sessionFile else {
         return
      }

      let isOnDisk = FileManager.default.fileExists(atPath: sessionFile.path)

      guard isOnDisk else {
         return
      }

      do {
         try FileManager.default.removeItem(at: sessionFile)
      } catch {
         active.gateway.post(Notice(tone: .error, title: "Session file kept", message: "Could not delete \(sessionFile.lastPathComponent). Delete it by hand to drop that session."))
      }
   }
}
