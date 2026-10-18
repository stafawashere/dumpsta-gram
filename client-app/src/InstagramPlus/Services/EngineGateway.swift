import Foundation
import Observation

enum SessionState: Equatable, Sendable {
   case active
   case checkpoint(Checkpoint)
   case revoked
   case signedOut
}

struct Notice: Identifiable, Equatable, Sendable {
   enum Tone: Sendable {
      case info
      case warning
      case error
   }

   let id = UUID()
   let tone: Tone
   let title: String
   let message: String
}

enum CallOutcome<Value> {
   case success(Value)
   case failure(EngineError)
   case halted
}

// An engine that can still be stopped after reconnect() returns. The dummy clears every stop on
// reconnect, so only the real engine reports one.
protocol ReportsSessionStop: Sendable {
   func sessionStop() async -> SessionState?
   func reopenFailure() async -> EngineError?
}

// The one place engine results become interface state. Checkpoints and revoked sessions stop
// every later call here rather than in each store, and nothing in this file retries a write.
@MainActor
@Observable
final class EngineGateway {
   let engine: any AppEngine

   private(set) var session: SessionState
   private(set) var sessionGeneration = 0
   private(set) var notices: [Notice] = []
   private(set) var pendingWrites = 0

   init(engine: any AppEngine, session: SessionState = .active) {
      self.engine = engine
      self.session = session
   }

   var client: any AppEngine { engine }

   // The dummy's developer controls and the DEBUG probe. Nil on the real engine.
   var dummy: DummyEngine? { engine as? DummyEngine }

   #if DEBUG
   // The snapshot probe only ever runs on the dummy, which EngineSelection guarantees.
   var dummyEngine: DummyEngine {
      guard let dummy else {
         preconditionFailure("the snapshot probe ran on the real engine")
      }

      return dummy
   }
   #endif

   var viewerID: String { engine.viewerID }

   var isActive: Bool { session == .active }

   func read<Value: Sendable>(
      _ label: String,
      _ operation: () async throws(EngineError) -> EngineResult<Value>
   ) async -> CallOutcome<Value> {
      await call(label, isWrite: false, operation)
   }

   func write<Value: Sendable>(
      _ label: String,
      _ operation: () async throws(EngineError) -> EngineResult<Value>
   ) async -> CallOutcome<Value> {
      await call(label, isWrite: true, operation)
   }

   private func call<Value: Sendable>(
      _ label: String,
      isWrite: Bool,
      _ operation: () async throws(EngineError) -> EngineResult<Value>
   ) async -> CallOutcome<Value> {
      guard isActive else {
         return .halted
      }

      if isWrite {
         pendingWrites += 1
      }

      defer {
         if isWrite {
            pendingWrites -= 1
         }
      }

      do throws(EngineError) {
         switch try await operation() {
            case .value(let value):
               return .success(value)

            case .checkpoint(let checkpoint):
               enterCheckpoint(checkpoint)
               return .halted
         }
      } catch {
         handle(error, label: label, isWrite: isWrite)
         return .failure(error)
      }
   }

   // MARK: Events
   // The listener polls inside the engine and its events wait in a buffer. Starting and draining
   // stop with the session, so a checkpointed or revoked session reaches nothing. Stopping always
   // reaches the engine, because a listener must be stopped even after it failed. A listener that
   // stopped is reported to the store and never restarted here.

   func startEvents(since messageID: String?) async -> Bool {
      guard isActive else {
         return false
      }

      await engine.startEvents(since: messageID)
      return true
   }

   func drainEvents() async -> [Engine.Event] {
      guard isActive else {
         return []
      }

      let events = await engine.drainEvents()

      for case .listenerStopped(let reason) in events {
         switch reason {
            case .checkpoint(let checkpoint):
               enterCheckpoint(checkpoint)

            case .error(.authenticationFailed):
               session = .revoked

            case .error:
               break
         }
      }

      return events
   }

   func stopEvents() async {
      await engine.stopEvents()
   }

   func enterCheckpoint(_ checkpoint: Checkpoint) {
      session = .checkpoint(checkpoint)
   }

   func handle(_ error: EngineError, label: String, isWrite: Bool) {
      switch error {
         case .authenticationFailed:
            session = .revoked

         case .rateLimited(let retryAfter):
            let minutes = max(1, Int(((retryAfter ?? 60) / 60).rounded(.up)))
            let message = isWrite
               ? "This account's hourly write budget is spent. Writes resume in about \(minutes) min."
               : "Instagram asked for a pause. Try again in about \(minutes) min."
            post(Notice(tone: .warning, title: "Slowing down", message: message))

         case .outcomeUnknown:
            post(Notice(tone: .warning, title: "Could not confirm \(label)", message: "It may have gone through. Instagram+ is checking instead of trying again."))

         case .upstreamRejected(let code) where code == EngineError.notWiredCode:
            post(Notice(tone: .info, title: "Not wired yet", message: "Instagram+ does not reach the engine for \(label) yet. Nothing was sent."))

         case .upstreamRejected(let code) where code == EngineError.sessionUnavailableCode:
            post(Notice(tone: .error, title: "The session is not open", message: "Instagram+ could not reopen this account's session, so nothing was sent for \(label). Reconnect it in Settings."))

         case .upstreamRejected(let code) where code == EngineError.bridgeFailureCode:
            post(Notice(tone: .error, title: "The engine bridge failed on \(label)", message: "Nothing was retried. The unified log has the engine's traceback."))

         case .upstreamRejected(let code) where code == EngineError.writesStoppedCode || code == "unrecognised":
            post(Notice(tone: .error, title: "Writes are stopped", message: "Instagram refused a write for a reason nothing explains. Check the account in a browser before resuming writes in Settings."))

         case .upstreamRejected:
            post(Notice(tone: .error, title: "Instagram refused \(label)", message: "Nothing was changed."))

         case .schemaChanged:
            post(Notice(tone: .error, title: "Instagram changed this page", message: "The engine could not read the answer. This needs an engine update."))

         case .transportFailure:
            post(Notice(tone: .error, title: "Can't reach Instagram", message: "Check the connection and try again."))

         case .notFound, .operationCancelled:
            break
      }
   }

   func post(_ notice: Notice) {
      notices.append(notice)

      Task { [weak self] in
         try? await Task.sleep(for: .seconds(7))
         self?.dismiss(notice.id)
      }
   }

   func dismiss(_ noticeID: Notice.ID) {
      notices.removeAll { $0.id == noticeID }
   }

   // A person confirming a checkpoint in their browser resumes future calls. The call the
   // checkpoint interrupted is not replayed.
   func resumeAfterCheckpoint() async {
      await reconnectEngine()
   }

   func connect() async {
      await reconnectEngine()
   }

   // A reconnect that meets the checkpoint or the revoked session again keeps that state.
   private func reconnectEngine() async {
      await engine.reconnect()

      let stoppable = engine as? any ReportsSessionStop
      let stopAfterReconnect = await stoppable?.sessionStop()

      if let stopAfterReconnect {
         session = stopAfterReconnect
         return
      }

      // A reopen that failed for any other reason leaves no open client, so the session is shown
      // as signed out, which stops every later call, rather than as active.
      if let reopenFailure = await stoppable?.reopenFailure() {
         session = .signedOut
         handle(reopenFailure, label: "reopening the session", isWrite: false)
         post(Notice(tone: .error, title: "The session is not open", message: "Instagram+ could not reopen this account's session. Nothing is sent until it is connected again."))
         return
      }

      session = .active
      sessionGeneration += 1
   }

   func signOut() async {
      await engine.close()
      session = .signedOut
   }

   func acknowledgeRevoked() {
      session = .signedOut
   }
}
