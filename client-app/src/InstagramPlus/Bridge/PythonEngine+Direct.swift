import Foundation

// The direct inbox, threads, requests, unread counts, notes, and the four direct writes. A
// thread cursor goes back to the engine exactly as it came. Each write is sent once through the
// gateway's write path, and the engine's pacer, write budget and write stop decide whether it
// leaves at all. Nothing here retries a send, an unsend or a note.
extension PythonEngine {
   func inbox(after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.DirectThread>> {
      try await guarded(.inbox) { bridge, handle throws(EngineError) in
         try await bridge.inbox(handle, after: cursor)
      }
   }

   func inboxLoad() async throws(EngineError) -> EngineResult<Engine.InboxLoad> {
      try await guarded(.inbox) { bridge, handle throws(EngineError) in
         try await bridge.inboxLoad(handle)
      }
   }

   func messages(threadFBID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.Message>> {
      try await guarded(.messages) { bridge, handle throws(EngineError) in
         try await bridge.messages(handle, threadFBID: threadFBID, after: cursor)
      }
   }

   func messageRequests() async throws(EngineError) -> EngineResult<Engine.MessageRequests> {
      try await guarded(.messageRequests) { bridge, handle throws(EngineError) in
         try await bridge.messageRequests(handle)
      }
   }

   func unreadCounts() async throws(EngineError) -> EngineResult<Engine.UnreadCounts> {
      try await guarded(.unreadCounts) { bridge, handle throws(EngineError) in
         try await bridge.unreadCounts(handle)
      }
   }

   func notes() async throws(EngineError) -> EngineResult<[Engine.Note]> {
      try await guarded(.notes) { bridge, handle throws(EngineError) in
         try await bridge.notes(handle)
      }
   }

   func send(threadFBID: String, text: String) async throws(EngineError) -> EngineResult<Engine.SentMessage> {
      try await guarded(.directWrites) { bridge, handle throws(EngineError) in
         try await bridge.send(handle, threadFBID: threadFBID, text: text)
      }
   }

   func unsend(threadFBID: String, messageID: String) async throws(EngineError) -> EngineResult<Void> {
      try await guarded(.directWrites) { bridge, handle throws(EngineError) in
         try await bridge.unsend(handle, threadFBID: threadFBID, messageID: messageID)
      }
   }

   func setNote(text: String, audience: Engine.NoteAudience) async throws(EngineError) -> EngineResult<Engine.Note> {
      try await guarded(.directWrites) { bridge, handle throws(EngineError) in
         try await bridge.setNote(handle, text: text, audience: audience)
      }
   }

   func deleteNote(noteID: String) async throws(EngineError) -> EngineResult<Void> {
      try await guarded(.directWrites) { bridge, handle throws(EngineError) in
         try await bridge.deleteNote(handle, noteID: noteID)
      }
   }
}
