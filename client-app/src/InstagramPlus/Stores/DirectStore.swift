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
   private(set) var olderCursors: [DirectThread.ID: String] = [:]
   private(set) var loadingOlder: Set<DirectThread.ID> = []
   private(set) var requests: [DirectThread] = []
   private(set) var requestsState = LoadState.idle
   private(set) var pendingRequestIDs: Set<DirectThread.ID> = []
   private(set) var notes: [Note] = []
   private(set) var isListening = false
   private(set) var listenerProblem: String?

   var selectedThreadID: DirectThread.ID?

   private var drainTask: Task<Void, Never>?

   // The viewer's message sender id is not the account id. It is learned from the first message
   // the viewer is seen to have sent, and is what reactions name.
   private var viewerFBID: String?

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
      threads.first { $0.id == selectedThreadID } ?? requests.first { $0.id == selectedThreadID }
   }

   var viewerNote: Note? {
      notes.first { $0.author.id == viewerID }
   }

   func isRequest(_ threadID: DirectThread.ID) -> Bool {
      requests.contains { $0.id == threadID }
   }

   func messages(in threadID: DirectThread.ID) -> [DirectMessage] {
      messages[threadID] ?? []
   }

   func message(_ messageID: DirectMessage.ID, in threadID: DirectThread.ID) -> DirectMessage? {
      messages[threadID]?.first { $0.id == messageID }
   }

   func messageState(for threadID: DirectThread.ID) -> LoadState {
      messageStates[threadID] ?? .idle
   }

   func hasOlderMessages(_ threadID: DirectThread.ID) -> Bool {
      olderCursors[threadID] != nil
   }

   // MARK: Inbox and requests

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

   func loadRequests() async {
      requestsState = .loading

      let engine = engine
      switch await gateway.read("message requests", { () async throws(EngineError) in try await engine.messageRequests() }) {
         case .success(let engineRequests):
            requests = engineRequests.pending.map { DirectThread($0, viewerID: viewerID) }
            requestsState = .loaded

         case .failure(let error):
            requestsState = .failed(HomeStore.describe(error))

         case .halted:
            requestsState = .idle
      }
   }

   func resolveRequest(_ threadID: DirectThread.ID, accept: Bool) async {
      pendingRequestIDs.insert(threadID)
      defer { pendingRequestIDs.remove(threadID) }

      let engine = engine
      let outcome = await gateway.write(accept ? "the request acceptance" : "the request removal") { () async throws(EngineError) in
         try await engine.resolveMessageRequest(threadFBID: threadID, accept: accept)
      }

      switch outcome {
         case .success:
            let resolved = requests.first { $0.id == threadID }
            requests.removeAll { $0.id == threadID }

            if accept, let resolved {
               threads.append(resolved)
            } else if selectedThreadID == threadID {
               selectedThreadID = nil
            }

         case .failure(.outcomeUnknown):
            await loadRequests()
            await loadInbox()

         case .failure, .halted:
            break
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

   // MARK: Threads

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
            learnViewerFBID(from: page.items)
            messages[threadID] = page.items.map { DirectMessage($0, viewerFBID: viewerFBID) }
            olderCursors[threadID] = page.hasNextPage ? page.endCursor : nil
            messageStates[threadID] = .loaded
            markRead(threadID)

         case .failure(let error):
            messageStates[threadID] = .failed(HomeStore.describe(error))

         case .halted:
            messageStates[threadID] = .idle
      }
   }

   func loadOlder(_ threadID: DirectThread.ID) async {
      guard let cursor = olderCursors[threadID], !loadingOlder.contains(threadID) else {
         return
      }

      loadingOlder.insert(threadID)
      defer { loadingOlder.remove(threadID) }

      let engine = engine
      guard case .success(let page) = await gateway.read("older messages", { () async throws(EngineError) in try await engine.messages(threadFBID: threadID, after: cursor) }) else {
         return
      }

      learnViewerFBID(from: page.items)

      let known = Set(messages[threadID]?.map(\.id) ?? [])
      let older = page.items
         .map { DirectMessage($0, viewerFBID: viewerFBID) }
         .filter { !known.contains($0.id) }

      messages[threadID] = older + (messages[threadID] ?? [])
      olderCursors[threadID] = page.hasNextPage ? page.endCursor : nil
   }

   private func learnViewerFBID(from engineMessages: [Engine.Message]) {
      guard viewerFBID == nil else {
         return
      }

      viewerFBID = engineMessages.first { $0.sender.igid == viewerID }?.sender.fbid
   }

   private func markRead(_ threadID: DirectThread.ID) {
      guard let index = threads.firstIndex(where: { $0.id == threadID }) else {
         return
      }

      threads[index].isUnread = false
   }

   func thread(with account: Account) -> DirectThread? {
      threads.first { thread in
         let isOneToOne = !thread.isGroup
         let isWithAccount = thread.participants.first?.id == account.id
         return isOneToOne && isWithAccount
      }
   }

   func openThread(with account: Account) async -> Bool {
      if let existing = thread(with: account) {
         await select(existing.id)
         return true
      }

      return await createThread(with: [account])
   }

   func createThread(with accounts: [Account]) async -> Bool {
      let engine = engine
      let userIDs = accounts.map(\.id)

      guard case .success(let engineThread) = await gateway.write("the new conversation", { () async throws(EngineError) in try await engine.createThread(userIDs: userIDs) }) else {
         return false
      }

      let thread = DirectThread(engineThread, viewerID: viewerID)

      if !threads.contains(where: { $0.id == thread.id }) {
         threads.append(thread)
      }

      await select(thread.id)
      return true
   }

   func setMuted(_ muted: Bool, threadID: DirectThread.ID) async {
      guard let index = threads.firstIndex(where: { $0.id == threadID }) else {
         return
      }

      threads[index].isMuted = muted

      let engine = engine
      let outcome = await gateway.write(muted ? "the mute" : "the unmute") { () async throws(EngineError) in
         try await engine.setThreadMuted(threadFBID: threadID, muted: muted)
      }

      switch outcome {
         case .success:
            break

         case .failure(.outcomeUnknown):
            await loadInbox()

         case .failure, .halted:
            if let revertIndex = threads.firstIndex(where: { $0.id == threadID }) {
               threads[revertIndex].isMuted = !muted
            }
      }
   }

   // MARK: Sending

   func send(_ text: String, to threadID: DirectThread.ID, replyingTo repliedToID: DirectMessage.ID? = nil) async {
      let trimmedText = text.trimmingCharacters(in: .whitespacesAndNewlines)
      guard !trimmedText.isEmpty else {
         return
      }

      let localID = "local." + UUID().uuidString
      let pending = DirectMessage(id: localID, senderID: viewerID, text: trimmedText, sentAt: .now, reactionCount: 0, delivery: .sending, repliedToID: repliedToID)
      messages[threadID, default: []].append(pending)
      touch(threadID, snippet: trimmedText, byViewer: true)

      let engine = engine
      let outcome = await gateway.write("the message") { () async throws(EngineError) in
         if let repliedToID {
            return try await engine.sendReply(threadFBID: threadID, text: trimmedText, replyingTo: repliedToID)
         }

         return try await engine.send(threadFBID: threadID, text: trimmedText)
      }

      settle(outcome, localID: localID, threadID: threadID)
   }

   func sendPhoto(_ imageURL: URL, to threadID: DirectThread.ID) async {
      let localID = "local." + UUID().uuidString
      let pending = DirectMessage(id: localID, senderID: viewerID, text: "", sentAt: .now, reactionCount: 0, delivery: .sending, imageURL: imageURL)
      messages[threadID, default: []].append(pending)
      touch(threadID, snippet: "Sent a photo", byViewer: true)

      let engine = engine
      let outcome = await gateway.write("the photo") { () async throws(EngineError) in
         try await engine.sendPhoto(threadFBID: threadID, imageURL: imageURL)
      }

      settle(outcome, localID: localID, threadID: threadID)
   }

   private func settle(_ outcome: CallOutcome<Engine.SentMessage>, localID: String, threadID: DirectThread.ID) {
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

      if let imageURL = failed.imageURL {
         await sendPhoto(imageURL, to: threadID)
      } else {
         await send(failed.text, to: threadID, replyingTo: failed.repliedToID)
      }
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

   func toggleReaction(_ messageID: DirectMessage.ID, in threadID: DirectThread.ID) async {
      guard let message = message(messageID, in: threadID), message.delivery == .sent else {
         return
      }

      let willReact = !message.viewerReacted
      updateMessage(messageID, in: threadID) { message in
         message.viewerReacted = willReact
         message.reactionCount += willReact ? 1 : -1
      }

      let engine = engine
      let emoji: String? = willReact ? Engine.Reaction.heart : nil
      let outcome = await gateway.write(willReact ? "the reaction" : "the reaction removal") { () async throws(EngineError) in
         try await engine.react(threadFBID: threadID, messageID: messageID, emoji: emoji)
      }

      switch outcome {
         case .success:
            break

         case .failure(.outcomeUnknown):
            await loadMessages(threadID)

         case .failure, .halted:
            updateMessage(messageID, in: threadID) { message in
               message.viewerReacted = !willReact
               message.reactionCount += willReact ? -1 : 1
            }
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
         await loadRequests()
         return
      }

      let message = DirectMessage(engineMessage, viewerFBID: viewerFBID)
      let isDuplicate = messages[threadID]?.contains { $0.id == message.id } ?? false

      if !isDuplicate, messageState(for: threadID).hasLoaded {
         messages[threadID, default: []].append(message)
      }

      touch(threadID, snippet: message.imageURL == nil ? message.text : "Sent a photo", byViewer: false)

      let isOpen = threadID == selectedThreadID
      if !isOpen, let index = threads.firstIndex(where: { $0.id == threadID }) {
         threads[index].isUnread = true
      }
   }
}
