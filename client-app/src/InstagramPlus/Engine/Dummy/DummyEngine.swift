import Foundation

// Stands in for the bridge until roadmap step 5.2. It keeps the engine's observable behaviour,
// not its mechanics: the pacer's spacing and write budget, the write stop, the error each
// failure raises, checkpoints as results, and a polling listener feeding a drainable buffer.
actor DummyEngine: AppEngine {
   enum Timing: String, CaseIterable, Sendable, Identifiable {
      case parity
      case fast
      case instant

      var id: String { rawValue }

      var title: String {
         switch self {
            case .parity: "Parity"
            case .fast: "Fast"
            case .instant: "Instant"
         }
      }

      var detail: String {
         switch self {
            case .parity: "The engine's defaults. Reads 1.3 s plus jitter, writes 30 s apart, polls every 60 s."
            case .fast: "The engine's FAST preset. No spacing, network latency only, polls every 10 s."
            case .instant: "No spacing and no latency. For screenshots and tests."
         }
      }

      // Engine behavior.py: Spacing(floor_seconds=1.3, mean_jitter_seconds=2.0) for reads,
      // Spacing(floor_seconds=30.0, mean_jitter_seconds=5.0) for writes. Jitter spans twice the mean.
      var readSpacing: (floor: Double, meanJitter: Double) {
         self == .parity ? (1.3, 2.0) : (0, 0)
      }

      var writeSpacing: (floor: Double, meanJitter: Double) {
         self == .parity ? (30, 5) : (0, 0)
      }

      var latency: ClosedRange<Double> {
         switch self {
            case .parity, .fast: 0.15...0.6
            case .instant: 0...0
         }
      }

      var pollInterval: Double {
         switch self {
            case .parity: 60
            case .fast: 10
            case .instant: 2
         }
      }
   }

   struct Faults: Sendable, Equatable {
      var transportFailureRate = 0.0
      var checkpointOnNextRequest = false
      var sessionRevoked = false
      var outcomeUnknownOnNextWrite = false
      var unrecognisedRejectionOnNextWrite = false
      var schemaChangeOnNextFeed = false
      var repliesFromOthers = true
   }

   enum RequestKind: String, Sendable {
      case read
      case write
      case poll
   }

   struct RequestRecord: Sendable, Identifiable {
      let id: Int
      let name: String
      let kind: RequestKind
      let queuedAt: Date
      var departedAt: Date?
      var finishedAt: Date?
      var outcome: String
   }

   struct Status: Sendable {
      let timing: Timing
      let faults: Faults
      let writesUsedThisHour: Int
      let writeBudget: Int
      let writesStopped: Bool
      let isListening: Bool
      let bufferedEvents: Int
      let requests: [RequestRecord]
   }

   nonisolated let viewerID: String

   static let writeBudgetPerHour = 30
   static let exerciseSeed: UInt64 = 20_260_930
   static let feedPageSize = 4
   static let messagePageSize = 20

   var world: DummyWorld
   private(set) var timing: Timing
   private(set) var faults = Faults()

   private var lastDepartureAt = Date.distantPast
   private var lastWriteDepartureAt = Date.distantPast
   private var writeDepartures: [Date] = []
   private var writesStopped = false
   private var requestLog: [RequestRecord] = []
   private var nextRequestID = 0

   // How many times an account session closed this client. The exercise reads it.
   private(set) var closeCount = 0

   private var eventBuffer: [Engine.Event] = []
   private var listenerTask: Task<Void, Never>?
   private var listenerWatermark: Date = .now

   // Every roll the dummy makes, the transport failure roll included. Under --exercise it is seeded,
   // so each run draws the same numbers in the same order.
   private var random: DummyRandom

   init(timing: Timing, world: DummyWorld = .seed()) {
      self.world = world
      self.timing = timing
      self.viewerID = world.viewerID

      let isExerciseRun = ProcessInfo.processInfo.arguments.contains("--exercise")
      self.random = DummyRandom(seed: isExerciseRun ? Self.exerciseSeed : nil)
   }

   func configure(timing newTiming: Timing) {
      timing = newTiming
   }

   func configure(faults newFaults: Faults) {
      faults = newFaults
   }

   func reconnect() {
      faults.sessionRevoked = false
      faults.checkpointOnNextRequest = false
      writesStopped = false
   }

   func close() async {
      closeCount += 1
      await stopEvents()
   }

   func status() -> Status {
      pruneWriteDepartures()

      return Status(
         timing: timing,
         faults: faults,
         writesUsedThisHour: writeDepartures.count,
         writeBudget: Self.writeBudgetPerHour,
         writesStopped: writesStopped,
         isListening: listenerTask != nil,
         bufferedEvents: eventBuffer.count,
         requests: Array(requestLog.suffix(60).reversed())
      )
   }

   // One request through the pacer. Every capability goes through here, so spacing, faults and
   // the log apply to all of them the same way they would to the engine's own transport.
   func perform<Value: Sendable>(
      _ name: String,
      kind: RequestKind,
      body: () throws(EngineError) -> Value
   ) async throws(EngineError) -> EngineResult<Value> {
      let recordID = beginRecord(name, kind: kind)

      if kind == .write {
         do throws(EngineError) {
            try refuseWriteIfBlocked()
         } catch {
            finishRecord(recordID, outcome: describe(error) + ", nothing sent")
            throw error
         }
      }

      let departure = reserveDeparture(for: kind)
      await sleep(until: departure)
      markDeparted(recordID)

      if kind == .write {
         writeDepartures.append(.now)
      }

      await sleep(seconds: Double.random(in: timing.latency, using: &random))

      if faults.sessionRevoked {
         finishRecord(recordID, outcome: "AuthenticationFailed")
         throw .authenticationFailed
      }

      if faults.checkpointOnNextRequest {
         faults.checkpointOnNextRequest = false
         finishRecord(recordID, outcome: "CheckpointRequired")
         return .checkpoint(Checkpoint(requiredAction: "confirm_it_was_you"))
      }

      let transportRoll = Double.random(in: 0..<1, using: &random)
      let transportFails = transportRoll < faults.transportFailureRate

      if transportFails {
         finishRecord(recordID, outcome: "TransportFailure")
         throw .transportFailure
      }

      if kind == .write, faults.unrecognisedRejectionOnNextWrite {
         faults.unrecognisedRejectionOnNextWrite = false
         writesStopped = true
         finishRecord(recordID, outcome: "UpstreamRejected, writes stopped")
         throw .upstreamRejected(code: "unrecognised")
      }

      do throws(EngineError) {
         let value = try body()

         if kind == .write, faults.outcomeUnknownOnNextWrite {
            faults.outcomeUnknownOnNextWrite = false
            finishRecord(recordID, outcome: "OutcomeUnknown, applied upstream")
            throw EngineError.outcomeUnknown(operation: name)
         }

         finishRecord(recordID, outcome: "ok")
         return .value(value)
      } catch {
         finishRecord(recordID, outcome: describe(error))
         throw error
      }
   }

   // MARK: Pacer

   private func reserveDeparture(for kind: RequestKind) -> Date {
      let readGap = gap(timing.readSpacing)
      var departure = max(Date.now, lastDepartureAt.addingTimeInterval(readGap))

      if kind == .write {
         let writeGap = gap(timing.writeSpacing)
         departure = max(departure, lastWriteDepartureAt.addingTimeInterval(writeGap))
         lastWriteDepartureAt = departure
      }

      lastDepartureAt = departure
      return departure
   }

   private func gap(_ spacing: (floor: Double, meanJitter: Double)) -> Double {
      spacing.floor + Double.random(in: 0...1, using: &random) * 2 * spacing.meanJitter
   }

   private func refuseWriteIfBlocked() throws(EngineError) {
      if writesStopped {
         throw .upstreamRejected(code: EngineError.writesStoppedCode)
      }

      pruneWriteDepartures()

      let budgetIsSpent = writeDepartures.count >= Self.writeBudgetPerHour
      guard budgetIsSpent, let oldest = writeDepartures.min() else {
         return
      }

      throw .rateLimited(retryAfter: oldest.addingTimeInterval(3_600).timeIntervalSinceNow)
   }

   private func pruneWriteDepartures() {
      let windowStart = Date.now.addingTimeInterval(-3_600)
      writeDepartures.removeAll { $0 < windowStart }
   }

   private func sleep(until date: Date) async {
      await sleep(seconds: date.timeIntervalSinceNow)
   }

   private func sleep(seconds: Double) async {
      guard seconds > 0 else {
         return
      }

      try? await Task.sleep(for: .seconds(seconds))
   }

   // MARK: Request log

   private static let tracesRequests = ProcessInfo.processInfo.environment["DUMMY_ENGINE_TRACE"] != nil

   private func trace(_ line: String) {
      guard Self.tracesRequests else {
         return
      }

      FileHandle.standardError.write(Data("dummy-engine: \(line)\n".utf8))
   }

   private func beginRecord(_ name: String, kind: RequestKind) -> Int {
      trace("queued \(kind.rawValue) \(name)")
      nextRequestID += 1
      requestLog.append(RequestRecord(id: nextRequestID, name: name, kind: kind, queuedAt: .now, departedAt: nil, finishedAt: nil, outcome: "queued"))

      if requestLog.count > 400 {
         requestLog.removeFirst(requestLog.count - 400)
      }

      return nextRequestID
   }

   private func markDeparted(_ recordID: Int) {
      guard let index = requestLog.firstIndex(where: { $0.id == recordID }) else {
         return
      }

      requestLog[index].departedAt = .now
      requestLog[index].outcome = "in flight"
   }

   private func finishRecord(_ recordID: Int, outcome: String) {
      guard let index = requestLog.firstIndex(where: { $0.id == recordID }) else {
         return
      }

      requestLog[index].finishedAt = .now
      requestLog[index].outcome = outcome
      trace("finished \(requestLog[index].name): \(outcome)")
   }

   private func describe(_ error: EngineError) -> String {
      switch error {
         case .notFound: "NotFound"
         case .rateLimited: "RateLimited"
         case .upstreamRejected(let code): "UpstreamRejected(\(code ?? "none"))"
         case .outcomeUnknown: "OutcomeUnknown"
         case .schemaChanged: "SchemaChanged"
         case .transportFailure: "TransportFailure"
         case .authenticationFailed: "AuthenticationFailed"
         case .operationCancelled: "OperationCancelled"
      }
   }

   // MARK: Events

   func startEvents(since messageID: String?) async {
      guard listenerTask == nil else {
         return
      }

      // Like the engine, a listener given the last handled message picks up after it, and one
      // given nothing starts from what it first sees.
      let handled = messageID.flatMap { id in world.messages.values.flatMap { $0 }.first { $0.id == id } }
      listenerWatermark = handled?.sentAt ?? .now
      listenerTask = Task { [weak self] in
         while !Task.isCancelled {
            guard let self else {
               return
            }

            let interval = await self.timing.pollInterval
            try? await Task.sleep(for: .seconds(interval))

            if Task.isCancelled {
               return
            }

            let shouldContinue = await self.poll()
            if !shouldContinue {
               return
            }
         }
      }
   }

   func stopEvents() async {
      listenerTask?.cancel()
      listenerTask = nil
   }

   func drainEvents() async -> [Engine.Event] {
      let drained = eventBuffer
      eventBuffer.removeAll()
      return drained
   }

   // One listener poll: an inbox read, then the thread read for each thread that moved. A
   // TransportFailure is survived, a checkpoint stops the listener, as the engine's poller does.
   private func poll() async -> Bool {
      do throws(EngineError) {
         let result = try await perform("PolarisDirectInboxQuery (poll)", kind: .poll) { () throws(EngineError) -> [Engine.Message] in
            deliverDueReplies()
            return newMessagesSinceWatermark()
         }

         switch result {
            case .checkpoint(let checkpoint):
               eventBuffer.append(.listenerStopped(.checkpoint(checkpoint)))
               listenerTask = nil
               return false

            case .value(let messages):
               for message in messages {
                  eventBuffer.append(.newMessage(world.asRead(message)))
               }

               return true
         }
      } catch .transportFailure {
         return true
      } catch {
         eventBuffer.append(.listenerStopped(.error(error)))
         listenerTask = nil
         return false
      }
   }

   private func deliverDueReplies() {
      let now = Date.now
      let due = world.pendingReplies.filter { $0.dueAt <= now }
      world.pendingReplies.removeAll { $0.dueAt <= now }

      for reply in due {
         _ = world.appendMessage(threadFBID: reply.threadFBID, senderID: reply.senderID, text: reply.text, offlineThreadingID: nil)
      }
   }

   private func newMessagesSinceWatermark() -> [Engine.Message] {
      let watermark = listenerWatermark
      let fresh = world.messages.values
         .flatMap { $0 }
         .filter { $0.sentAt > watermark && $0.sender.igid != viewerID }
         .sorted { $0.sentAt < $1.sentAt }

      if let newest = fresh.last {
         listenerWatermark = newest.sentAt
      }

      return fresh
   }

   func scheduleReply(in threadFBID: String) {
      guard faults.repliesFromOthers, let thread = world.threads[threadFBID], let senderID = thread.participantIDs.randomElement(using: &random) else {
         return
      }

      let delay = Double.random(in: 4...18, using: &random)
      let text = DummyWorld.cannedReplies.randomElement(using: &random) ?? "Ok"
      world.pendingReplies.append(DummyWorld.PendingReply(dueAt: .now.addingTimeInterval(delay), threadFBID: threadFBID, senderID: senderID, text: text))
   }

   func consumeSchemaFault() -> Bool {
      let shouldFail = faults.schemaChangeOnNextFeed
      faults.schemaChangeOnNextFeed = false
      return shouldFail
   }
}

// SplitMix64 when seeded, the system generator otherwise.
struct DummyRandom: RandomNumberGenerator, Sendable {
   private var seededState: UInt64?
   private var system = SystemRandomNumberGenerator()

   init(seed: UInt64?) {
      seededState = seed
   }

   mutating func next() -> UInt64 {
      guard var state = seededState else {
         return system.next()
      }

      state &+= 0x9E37_79B9_7F4A_7C15
      seededState = state

      var mixed = state
      mixed = (mixed ^ (mixed >> 30)) &* 0xBF58_476D_1CE4_E5B9
      mixed = (mixed ^ (mixed >> 27)) &* 0x94D0_49BB_1331_11EB
      return mixed ^ (mixed >> 31)
   }
}
