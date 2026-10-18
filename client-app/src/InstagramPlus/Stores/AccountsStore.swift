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

// A session the engine accepted and whose own profile was read back, waiting for the person to
// say it is their account. Nothing is installed until they do. The session file exists already,
// because the engine reads its session from a file, and is removed again on a refusal.
struct PendingAccount: Identifiable {
   let engine: PythonEngine
   let account: Account
   let followerCount: Int
   let followingCount: Int
   let sessionFile: URL
   // The file an earlier session of this account had, moved aside so a refusal can put it back.
   fileprivate let displaced: URL?

   var id: String { account.id }
}

// What the verify step produced. A checkpoint and a refused session land in the same states a
// later call would produce, and neither is retried.
enum SessionVerification {
   case needsConfirmation(PendingAccount)
   case routedToState
   case rejected(String)
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

   // The account the verify step read back, shown on the setup screen until it is confirmed.
   private(set) var pending: PendingAccount?

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
   // session file. The engine then reads the account's own profile, one request, and the result
   // waits as `pending` for the person to confirm. A checkpoint lands in the same state a later
   // call would produce. A refusal while another account is in use is reported back to the
   // setup screen and leaves that account untouched.
   func verifyBrowserSession(_ input: SessionCookieInput.Cleaned) async -> SessionVerification {
      guard case .real(let launch) = source else {
         return .routedToState
      }

      let material = PythonBridge.CookieMaterial(
         sessionID: input.sessionID,
         userID: input.userID,
         csrfToken: input.csrfToken,
         extraCookies: [:]
      )

      let isAddingToSignedIn = isAddingAccount && hasSignedInAccount
      let sessionFile = PythonEngineFactory.sessionFile(for: input.userID)
      let displaced = displaceSessionFile(sessionFile)

      func restore() {
         restoreSessionFile(sessionFile, from: displaced)
      }

      switch await PythonEngineFactory.adopt(material, enabled: launch.enabled) {
         case .adopted(let engine):
            return await readBack(engine, sessionFile: sessionFile, displaced: displaced, isAddingToSignedIn: isAddingToSignedIn)

         case .checkpoint(let engine, let checkpoint):
            discard(displaced)
            await install(engine, session: .checkpoint(checkpoint))
            return .routedToState

         case .revoked where isAddingToSignedIn:
            restore()
            return .rejected("Instagram refused this session. Sign in again in the browser and copy fresh cookies.")

         case .revoked:
            restore()
            active.gateway.handle(.authenticationFailed, label: "the session", isWrite: false)
            return .routedToState

         case .failed(let problem):
            restore()
            return .rejected(problem.description)
      }
   }

   private func readBack(_ engine: PythonEngine, sessionFile: URL, displaced: URL?, isAddingToSignedIn: Bool) async -> SessionVerification {
      do throws(EngineError) {
         switch try await engine.profile(id: engine.viewerID) {
            case .value(let profile):
               let account = Account(id: profile.id, username: profile.username, displayName: profile.fullName.isEmpty ? profile.username : profile.fullName, location: nil, isVerified: profile.isVerified, profilePicURL: profile.profilePicURL.isEmpty ? nil : profile.profilePicURL)

               guard profile.id == engine.viewerID else {
                  await engine.close()
                  restoreSessionFile(sessionFile, from: displaced)
                  return .rejected("Instagram answered with a different account than ds_user_id names. Copy all three values from the same browser profile.")
               }

               pending = PendingAccount(engine: engine, account: account, followerCount: profile.followerCount, followingCount: profile.followingCount, sessionFile: sessionFile, displaced: displaced)
               return .needsConfirmation(pending!)

            case .checkpoint(let checkpoint):
               discard(displaced)
               await install(engine, session: .checkpoint(checkpoint))
               return .routedToState
         }
      } catch {
         await engine.close()
         restoreSessionFile(sessionFile, from: displaced)

         switch error {
            case .authenticationFailed where isAddingToSignedIn:
               return .rejected("Instagram refused this session. Sign in again in the browser and copy fresh cookies.")

            case .authenticationFailed:
               active.gateway.handle(.authenticationFailed, label: "the session", isWrite: false)
               return .routedToState

            case .rateLimited:
               return .rejected("Instagram asked for a pause. Nothing was saved. Try again in a few minutes.")

            case .transportFailure:
               return .rejected("Could not reach Instagram. Check the connection. Nothing was saved.")

            default:
               return .rejected("Instagram did not answer the account check. Nothing was saved.")
         }
      }
   }

   // "Yes, that is me". The session stays saved, owner-only, and the account becomes active.
   func confirmPending() async {
      guard let confirmed = pending else {
         return
      }

      pending = nil
      discard(confirmed.displaced)
      await install(confirmed.engine, session: .active)
   }

   // "Not me". The session file is removed and any earlier file of that account comes back.
   func cancelPending() async {
      guard let refused = pending else {
         return
      }

      pending = nil
      await refused.engine.close()
      restoreSessionFile(refused.sessionFile, from: refused.displaced)
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

   // A verify that fails or is refused must not cost the person a session that worked, so an
   // existing file of the same account is moved aside first and put back on any failure.
   fileprivate func displaceSessionFile(_ file: URL) -> URL? {
      let manager = FileManager.default

      guard manager.fileExists(atPath: file.path) else {
         return nil
      }

      let aside = file.deletingLastPathComponent().appendingPathComponent(".previous-\(file.lastPathComponent)")
      try? manager.removeItem(at: aside)

      do {
         try manager.moveItem(at: file, to: aside)
         return aside
      } catch {
         return nil
      }
   }

   fileprivate func restoreSessionFile(_ file: URL, from displaced: URL?) {
      let manager = FileManager.default
      try? manager.removeItem(at: file)

      // The ledger holds the write budget and stop. It stays when an earlier session of this
      // account is coming back, and goes with a session that never existed before.
      if let displaced {
         try? manager.moveItem(at: displaced, to: file)
      } else {
         try? manager.removeItem(at: file.appendingPathExtension("ledger"))
      }
   }

   fileprivate func discard(_ displaced: URL?) {
      if let displaced {
         try? FileManager.default.removeItem(at: displaced)
      }
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
