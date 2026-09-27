// The engine's exception hierarchy as Swift values. CheckpointRequired is deliberately absent:
// a checkpoint arrives as EngineResult.checkpoint, because an error case invites a catch that
// retries, and a checkpoint must never be retried.
enum EngineError: Error, Sendable, Equatable {
   case notFound
   case rateLimited(retryAfter: Double?)
   case upstreamRejected(code: String?)
   case outcomeUnknown(operation: String?)
   case schemaChanged(path: String?)
   case transportFailure
   case authenticationFailed
   case operationCancelled

   static let writesStoppedCode = "writes_stopped"
}

struct Checkpoint: Sendable, Hashable {
   let requiredAction: String?
}

enum EngineResult<Value: Sendable>: Sendable {
   case value(Value)
   case checkpoint(Checkpoint)
}
