import Foundation
import Observation

@MainActor
@Observable
final class DirectStore {
   let gateway: EngineGateway

   private(set) var inboxState = LoadState.idle
   private(set) var threads: [DirectThread] = []
   private(set) var messages: [DirectThread.ID: [DirectMessage]] = [:]
   private(set) var messageStates: [DirectThread.ID: LoadState] = [:]
   private(set) var notes: [Note] = []
   private(set) var isListening = false
   private(set) var listenerProblem: String?

   var selectedThreadID: DirectThread.ID?

   private var drainTask: Task<Void, Never>?

   init(gateway: EngineGateway) {
      self.gateway = gateway
   }

   var engine: any AppEngine { gateway.client }

   var viewerID: String { gateway.viewerID }

   var unreadCount: Int {
      threads.filter(\.isUnread).count
   }

   var orderedThreads: [DirectThread] {
      threads.sorted { $0.lastActivity > $1.lastActivity }
   }

   var selectedThread: DirectThread? {
      threads.first { $0.id == selectedThreadID }
   }

   var viewerNote: Note? {
      notes.first { $0.author.id == viewerID }
   }

   func messages(in threadID: DirectThread.ID) -> [DirectMessage] {
      messages[threadID] ?? []
   }

   func messageState(for threadID: DirectThread.ID) -> LoadState {
      messageStates[threadID] ?? .idle
   }

   // MARK: Inbox

   func loadInbox() async {
      inboxState = .loading

      let engine = engine
      switch await gateway.read("the inbox", { () async throws(EngineError) in try await engine.inbox(after: nil) }) {
         case .success(let page):
            threads = page.items.map { DirectThread($0, viewerID: viewerID) }
            inboxState = .loaded
            await startListening()

         case .failure(let error):
            inboxState = .failed(HomeStore.describe(error))

         case .halted:
            inboxState = .idle
      }
   }

   func loadNotes() async {
      let engine = engine

      guard case .success(let engineNotes) = await gateway.read("notes", { () async throws(EngineError) in try await engine.notes() }) else {
         return
      }

      notes = engineNotes.map { note in
         let knownAuthor = threads.flatMap(\.participants).first { $0.id == note.authorID }
         let username = note.authorUsername ?? note.authorID
         let author = knownAuthor ?? Account(id: note.authorID, username: username, displayName: username, location: nil)
         return Note(note, author: author)
      }
   }

   func select(_ threadID: DirectThread.ID) async {
      selectedThreadID = threadID

      let hasMessages = messageState(for: threadID).hasLoaded
      guard !hasMessages else {
         markRead(threadID)
         return
      }

      await loadMessages(threadID)
   }

   func loadMessages(_ threadID: DirectThread.ID) async {
      messageStates[threadID] = .loading

      let engine = engine
      switch await gateway.read("the conversation", { () async throws(EngineError) in try await engine.messages(threadFBID: threadID, after: nil) }) {
         case .success(let page):
            messages[threadID] = page.items.map(DirectMessage.init)
            messageStates[threadID] = .loaded
            markRead(threadID)

         case .failure(let error):
            messageStates[threadID] = .failed(HomeStore.describe(error))

         case .halted:
            messageStates[threadID] = .idle
      }
   }

   private func markRead(_ threadID: DirectThread.ID) {
      guard let index = threads.firstIndex(where: { $0.id == threadID }) else {
         return
      }

      threads[index].isUnread = false
   }

   func openThread(with account: Account) async -> Bool {
      let existing = threads.first { thread in
         let isOneToOne = !thread.isGroup
         let isWithAccount = thread.participants.first?.id == account.id
         return isOneToOne && isWithAccount
      }

      guard let existing else {
         gateway.post(Notice(tone: .info, title: "No conversation yet", message: "The engine can only send into an existing thread. Starting a new one is not supported yet."))
         return false
      }

      await select(existing.id)
      return true
   }

   // MARK: Sending

   func send(_ text: String, to threadID: DirectThread.ID) async {
      let trimmedText = text.trimmingCharacters(in: .whitespacesAndNewlines)
      guard !trimmedText.isEmpty else {
         return
      }

      let localID = "local." + UUID().uuidString
      let pending = DirectMessage(id: localID, senderID: viewerID, text: trimmedText, sentAt: .now, reactionCount: 0, delivery: .sending)
      messages[threadID, default: []].append(pending)
      touch(threadID, snippet: trimmedText, byViewer: true)

      let engine = engine
      let outcome = await gateway.write("the message") { () async throws(EngineError) in try await engine.send(threadFBID: threadID, text: trimmedText) }

      switch outcome {
         case .success(let sent):
            updateMessage(localID, in: threadID) { message in
               message.id = sent.id
               message.delivery = .sent
            }

         case .failure(.outcomeUnknown):
            updateMessage(localID, in: threadID) { $0.delivery = .uncertain }

         case .failure, .halted:
            updateMessage(localID, in: threadID) { $0.delivery = .failed }
      }
   }

   // Only a message that certainly did not go out is offered for sending again, and only when
   // a person asks. An uncertain one is checked by reading the thread instead.
   func resend(_ messageID: DirectMessage.ID, in threadID: DirectThread.ID) async {
      guard let failed = messages[threadID]?.first(where: { $0.id == messageID }), failed.delivery == .failed else {
         return
      }

      messages[threadID]?.removeAll { $0.id == messageID }
      await send(failed.text, to: threadID)
   }

   func unsend(_ messageID: DirectMessage.ID, in threadID: DirectThread.ID) async {
      guard let index = messages[threadID]?.firstIndex(where: { $0.id == messageID }) else {
         return
      }

      let removed = messages[threadID]![index]
      messages[threadID]?.remove(at: index)

      let engine = engine
      let outcome = await gateway.write("the unsend") { () async throws(EngineError) in try await engine.unsend(threadFBID: threadID, messageID: messageID) }

      switch outcome {
         case .success:
            break

         case .failure(.outcomeUnknown):
            await loadMessages(threadID)

         case .failure, .halted:
            messages[threadID]?.insert(removed, at: min(index, messages[threadID]?.count ?? 0))
      }
   }

   private func updateMessage(_ messageID: DirectMessage.ID, in threadID: DirectThread.ID, _ change: (inout DirectMessage) -> Void) {
      guard let index = messages[threadID]?.firstIndex(where: { $0.id == messageID }) else {
         return
      }

      change(&messages[threadID]![index])
   }

   private func touch(_ threadID: DirectThread.ID, snippet: String, byViewer: Bool) {
      guard let index = threads.firstIndex(where: { $0.id == threadID }) else {
         return
      }

      threads[index].lastActivity = .now
      threads[index].snippet = snippet
      threads[index].lastSenderIsViewer = byViewer
   }

   // MARK: Notes

   func setNote(_ text: String, closeFriendsOnly: Bool) async {
      let trimmedText = text.trimmingCharacters(in: .whitespacesAndNewlines)
      guard !trimmedText.isEmpty else {
         return
      }

      let engine = engine
      let audience: Engine.NoteAudience = closeFriendsOnly ? .closeFriends : .mutualFollows
      let outcome = await gateway.write("the note") { () async throws(EngineError) in try await engine.setNote(text: trimmedText, audience: audience) }

      switch outcome {
         case .success, .failure(.outcomeUnknown):
            await loadNotes()

         case .failure, .halted:
            break
      }
   }

   func deleteViewerNote() async {
      guard let note = viewerNote else {
         return
      }

      notes.removeAll { $0.id == note.id }

      let engine = engine
      let outcome = await gateway.write("the note delete") { () async throws(EngineError) in try await engine.deleteNote(noteID: note.id) }

      if case .success = outcome {
         return
      }

      await loadNotes()
   }

   // MARK: Events

   // Events come out of a buffer the app drains on a timer. The engine never calls back into
   // Swift, which is the rule the bridge has to keep.
   func startListening() async {
      guard !isListening else {
         return
      }

      isListening = true
      listenerProblem = nil
      await engine.startEvents(since: nil)

      drainTask = Task { [weak self] in
         while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(1.5))

            guard let self else {
               return
            }

            let events = await self.engine.drainEvents()
            await self.apply(events)
         }
      }
   }

   func stopListening() async {
      drainTask?.cancel()
      drainTask = nil
      isListening = false
      await engine.stopEvents()
   }

   private func apply(_ events: [Engine.Event]) async {
      for event in events {
         switch event {
            case .newMessage(let engineMessage):
               await receive(engineMessage)

            case .eventsDropped:
               await loadInbox()

               if let selectedThreadID {
                  await loadMessages(selectedThreadID)
               }

            case .listenerStopped(.checkpoint(let checkpoint)):
               drainTask?.cancel()
               isListening = false
               gateway.enterCheckpoint(checkpoint)

            case .listenerStopped(.error(let error)):
               drainTask?.cancel()
               isListening = false
               listenerProblem = HomeStore.describe(error)
         }
      }
   }

   private func receive(_ engineMessage: Engine.Message) async {
      let threadID = engineMessage.threadFBID
      let isKnownThread = threads.contains { $0.id == threadID }

      guard isKnownThread else {
         await loadInbox()
         return
      }

      let message = DirectMessage(engineMessage)
      let isDuplicate = messages[threadID]?.contains { $0.id == message.id } ?? false

      if !isDuplicate, messageState(for: threadID).hasLoaded {
         messages[threadID, default: []].append(message)
      }

      touch(threadID, snippet: message.text, byViewer: false)

      let isOpen = threadID == selectedThreadID
      if !isOpen, let index = threads.firstIndex(where: { $0.id == threadID }) {
         threads[index].isUnread = true
      }
   }
}
