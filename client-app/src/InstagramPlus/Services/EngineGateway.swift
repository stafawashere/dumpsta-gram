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

// The one place engine results become interface state. Checkpoints and revoked sessions stop
// every later call here rather than in each store, and nothing in this file retries a write.
@MainActor
@Observable
final class EngineGateway {
   let engine: DummyEngine

   private(set) var session: SessionState = .active
   private(set) var sessionGeneration = 0
   private(set) var notices: [Notice] = []
   private(set) var pendingWrites = 0

   init(engine: DummyEngine) {
      self.engine = engine
   }

   var client: any AppEngine { engine }

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
      await engine.reconnect()
      session = .active
      sessionGeneration += 1
   }

   func connect() async {
      await engine.reconnect()
      session = .active
      sessionGeneration += 1
   }

   func signOut() async {
      await engine.stopEvents()
      session = .signedOut
   }

   func acknowledgeRevoked() {
      session = .signedOut
   }
}
