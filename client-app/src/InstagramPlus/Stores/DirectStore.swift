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
   private(set) var notesState = LoadState.idle
   private(set) var unreadCounts: Engine.UnreadCounts?
   private(set) var isLoadingMoreThreads = false

   // Set when the listener reports a message in a thread this store has not loaded, or dropped
   // events. The inbox is not read again on its own, since one read costs about 30 requests
   // under PARITY. A person refreshes it.
   private(set) var isInboxStale = false
   private var inboxCursor: String?
   private(set) var listener = ListenerState.idle

   // The id of the last message the listener delivered and this store handled. A restarted
   // listener is given it untouched, so it picks up after that message.
   private(set) var eventsWatermark: String?
   private(set) var eventsHandled = 0

   var selectedThreadID: DirectThread.ID?

   private var drainTask: Task<Void, Never>?
   private var messageLoads: [DirectThread.ID: Task<Void, Never>] = [:]
   private var inboxLoad: Task<Void, Never>?

   enum ListenerState: Equatable {
      case idle
      case listening
      case stopped(reason: String)
   }

   init(gateway: EngineGateway) {
      self.gateway = gateway
   }

   var engine: any AppEngine { gateway.client }

   var viewerID: String { gateway.viewerID }

   var isListening: Bool {
      listener == .listening
   }

   var listenerProblem: String? {
      guard case .stopped(let reason) = listener else {
         return nil
      }

      return reason
   }

   // The engine's count of unread inbox threads, nil until it has been read.
   var unreadThreadCount: Int? {
      unreadCounts?.inbox
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

   var hasMoreThreads: Bool {
      inboxCursor != nil
   }

   // MARK: Inbox and requests

   // One inbox load answers the first page, the notes tray and the unread count, which a
   // browser reads from one page load too, so opening Messages costs one load rather than one
   // per part. Callers that ask while a load is in flight wait for it instead of sending another.
   func loadInbox() async {
      if let inFlight = inboxLoad {
         await inFlight.value
         return
      }

      let load = Task { await readInbox() }
      inboxLoad = load
      await load.value
      inboxLoad = nil
   }

   private func readInbox() async {
      inboxState = .loading

      if !notesState.hasLoaded {
         notesState = .loading
      }

      let engine = engine
      switch await gateway.read("the inbox", { () async throws(EngineError) in try await engine.inboxLoad() }) {
         case .success(let load):
            threads = load.threads.items.map { DirectThread($0, viewerID: viewerID) }
            inboxCursor = load.threads.hasNextPage ? load.threads.endCursor : nil
            isInboxStale = false
            inboxState = .loaded
            notes = load.notes.map(note(from:))
            notesState = .loaded
            unreadCounts = load.unreadCounts

            // Only a listener that never ran starts here. One that stopped waits for a person.
            if listener == .idle {
               await startListening()
            }

         case .failure(let error):
            inboxState = .failed(HomeStore.describe(error))
            notesState = notesState.hasLoaded ? notesState : .failed(HomeStore.describe(error))

         case .halted:
            inboxState = .idle
            notesState = notesState.hasLoaded ? notesState : .idle
      }
   }

   // The next inbox page, its cursor passed back exactly as it came. A thread already listed is
   // not listed twice.
   func loadMoreThreads() async {
      guard let cursor = inboxCursor, !isLoadingMoreThreads else {
         return
      }

      isLoadingMoreThreads = true
      defer { isLoadingMoreThreads = false }

      let engine = engine
      guard case .success(let page) = await gateway.read("more conversations", { () async throws(EngineError) in try await engine.inbox(after: cursor) }) else {
         return
      }

      let known = Set(threads.map(\.id))
      let older = page.items.map { DirectThread($0, viewerID: viewerID) }.filter { !known.contains($0.id) }

      threads += older
      inboxCursor = page.hasNextPage ? page.endCursor : nil
   }

   func loadUnreadCounts() async {
      let engine = engine

      guard case .success(let counts) = await gateway.read("the unread count", { () async throws(EngineError) in try await engine.unreadCounts() }) else {
         return
      }

      unreadCounts = counts
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
            await markInboxStale()

            if accept {
               await rereadMessages(threadID)
            }

         case .failure, .halted:
            break
      }
   }

   // The tray read on its own, after the viewer's note changed. Opening the inbox reads it
   // with the inbox instead.
   func loadNotes() async {
      // Notes already shown stay on screen while they are read again.
      if !notesState.hasLoaded {
         notesState = .loading
      }

      let engine = engine
      switch await gateway.read("notes", { () async throws(EngineError) in try await engine.notes() }) {
         case .success(let engineNotes):
            notes = engineNotes.map(note(from:))
            notesState = .loaded

         case .failure(let error):
            notesState = .failed(HomeStore.describe(error))

         case .halted:
            notesState = notesState.hasLoaded ? notesState : .idle
      }
   }

   private func note(from engineNote: Engine.Note) -> Note {
      let knownAuthor = threads.flatMap(\.participants).first { $0.id == engineNote.authorID }
      let username = engineNote.authorUsername ?? engineNote.authorID
      let author = knownAuthor ?? Account(id: engineNote.authorID, username: username, displayName: username, location: nil)
      return Note(engineNote, author: author)
   }

   // MARK: Threads

   // Opening a thread reads its newest page, which is what has the engine mark it read
   // (Behavior.mark_threads_read). A loaded thread that is read already is shown as it is; one
   // that became unread since, through the listener, is read again so the mark is sent, rather
   // than only cleared here.
   func select(_ threadID: DirectThread.ID) async {
      selectedThreadID = threadID

      let hasMessages = messageState(for: threadID).hasLoaded
      let isUnread = threads.first { $0.id == threadID }?.isUnread ?? false

      if hasMessages, !isUnread {
         return
      }

      if hasMessages {
         await rereadMessages(threadID)
      } else {
         await loadMessages(threadID)
      }
   }

   // A thread is read once at a time. A caller that asks while a read of the same thread is in
   // flight waits for that read instead of sending a second one, whose answer could land after
   // an optimistic change and undo it.
   func loadMessages(_ threadID: DirectThread.ID) async {
      if let inFlight = messageLoads[threadID] {
         await inFlight.value
         return
      }

      await runFirstPageRead(threadID)
   }

   // A read that must see something newer than any load in flight, such as a write whose outcome
   // is unknown. A load that started earlier could answer from before it, so this waits that load
   // out and then reads the thread again.
   private func rereadMessages(_ threadID: DirectThread.ID) async {
      if let staleLoad = messageLoads[threadID] {
         await staleLoad.value
      }

      await runFirstPageRead(threadID)
   }

   private func runFirstPageRead(_ threadID: DirectThread.ID) async {
      let load = Task { await readFirstPage(threadID) }
      messageLoads[threadID] = load
      await load.value

      let isStillCurrent = messageLoads[threadID] == load
      if isStillCurrent {
         messageLoads[threadID] = nil
      }
   }

   private func readFirstPage(_ threadID: DirectThread.ID) async {
      // A thread read again keeps its messages on screen until the answer lands.
      let previousState = messageState(for: threadID)
      if !previousState.hasLoaded {
         messageStates[threadID] = .loading
      }

      let wasUnread = threads.first { $0.id == threadID }?.isUnread ?? false

      let engine = engine
      switch await gateway.read("the conversation", { () async throws(EngineError) in try await engine.messages(threadFBID: threadID, after: nil) }) {
         case .success(let page):
            let newest = page.items.map { DirectMessage($0, viewerID: viewerID) }
            let kept = olderLoadedMessages(threadID, before: newest)

            // A message still sending, or one that certainly failed and waits for a person, is
            // not in the answer and stays below it. An uncertain one is settled by the answer.
            let unsettled = messages[threadID]?.filter { $0.delivery == .sending || $0.delivery == .failed } ?? []

            messages[threadID] = kept + newest + unsettled

            // Older pages already scrolled in stay, with the cursor that continues below them.
            if kept.isEmpty {
               olderCursors[threadID] = page.hasNextPage ? page.endCursor : nil
            }

            messageStates[threadID] = .loaded
            markRead(threadID)

            if wasUnread {
               adjustUnreadCount(by: -1)
            }

         case .failure(let error):
            if !previousState.hasLoaded {
               messageStates[threadID] = .failed(HomeStore.describe(error))
            }

         case .halted:
            if !previousState.hasLoaded {
               messageStates[threadID] = .idle
            }
      }
   }

   // The loaded messages older than a newest page read again, so a reread does not drop the
   // pages a person scrolled back through. Local messages are handled by the caller.
   private func olderLoadedMessages(_ threadID: DirectThread.ID, before newest: [DirectMessage]) -> [DirectMessage] {
      guard let oldestNew = newest.map(\.sentAt).min(), let loaded = messages[threadID] else {
         return []
      }

      let newIDs = Set(newest.map(\.id))
      return loaded.filter { message in
         let isServerMessage = !message.id.hasPrefix("local.")
         return isServerMessage && message.sentAt < oldestNew && !newIDs.contains(message.id)
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

      let known = Set(messages[threadID]?.map(\.id) ?? [])
      let older = page.items
         .map { DirectMessage($0, viewerID: viewerID) }
         .filter { !known.contains($0.id) }

      messages[threadID] = older + (messages[threadID] ?? [])
      olderCursors[threadID] = page.hasNextPage ? page.endCursor : nil
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
            // The thread list may be out of date, so it is marked stale for the person to refresh,
            // and only the affected conversation is read again.
            await markInboxStale()
            await rereadMessages(threadID)

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
            // A read that landed while this was sending may already list it.
            let isAlreadyListed = messages[threadID]?.contains { $0.id == sent.id } ?? false
            if isAlreadyListed {
               messages[threadID]?.removeAll { $0.id == localID }
               return
            }

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
            await rereadMessages(threadID)

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
            await rereadMessages(threadID)

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

   // Events come out of a buffer the app drains on a timer, through the gateway. The engine
   // never calls back into Swift, which is the rule the bridge has to keep. A listener that
   // stopped stays stopped with the engine's reason until a person resumes it.
   func startListening() async {
      guard !isListening else {
         return
      }

      guard await gateway.startEvents(since: eventsWatermark) else {
         return
      }

      listener = .listening

      drainTask = Task { [weak self] in
         while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(1.5))

            guard let self else {
               return
            }

            await self.drainOnce()
         }
      }
   }

   // This account became the active one again. Only a listener that ran for a loaded inbox
   // starts again, and one the engine stopped keeps waiting for a person.
   func resumeListening() async {
      let hasLoadedInbox = inboxState == .loaded
      let isIdle = listener == .idle

      guard hasLoadedInbox, isIdle else {
         return
      }

      await startListening()
   }

   func stopListening() async {
      drainTask?.cancel()
      drainTask = nil

      if isListening {
         listener = .idle
      }

      await gateway.stopEvents()
   }

   private func drainOnce() async {
      guard gateway.isActive else {
         await stopAfterSessionHalt()
         return
      }

      let events = await gateway.drainEvents()
      await apply(events)
   }

   private func stopAfterSessionHalt() async {
      drainTask?.cancel()
      drainTask = nil
      listener = .stopped(reason: "The session stopped, so the listener stopped with it.")
      await gateway.stopEvents()
   }

   private func apply(_ events: [Engine.Event]) async {
      for event in events {
         eventsHandled += 1

         switch event {
            case .newMessage(let engineMessage):
               await receive(engineMessage)
               eventsWatermark = engineMessage.id

            case .eventsDropped(_, let droppedThreadID):
               await markInboxStale()

               let concernsOpenThread = droppedThreadID == nil || droppedThreadID == selectedThreadID
               if concernsOpenThread, let selectedThreadID {
                  await rereadMessages(selectedThreadID)
               }

            case .listenerStopped(let reason):
               drainTask?.cancel()
               drainTask = nil
               listener = .stopped(reason: Self.describe(reason))
               await gateway.stopEvents()
         }
      }
   }

   private func receive(_ engineMessage: Engine.Message) async {
      let threadID = engineMessage.threadFBID
      let isKnownThread = threads.contains { $0.id == threadID }

      guard isKnownThread else {
         await markInboxStale()
         return
      }

      let message = DirectMessage(engineMessage, viewerID: viewerID)
      let isDuplicate = messages[threadID]?.contains { $0.id == message.id } ?? false

      if !isDuplicate, messageState(for: threadID).hasLoaded {
         messages[threadID, default: []].append(message)
      }

      // The listener delivers the viewer's own messages too, including ones sent elsewhere.
      let isFromViewer = engineMessage.isFromViewer == true
      touch(threadID, snippet: message.imageURL == nil ? message.text : "Sent a photo", byViewer: isFromViewer)

      let isOpen = threadID == selectedThreadID
      let becomesUnread = !isOpen && !isFromViewer
      if becomesUnread, let index = threads.firstIndex(where: { $0.id == threadID }), !threads[index].isUnread {
         threads[index].isUnread = true
         adjustUnreadCount(by: 1)
      }
   }

   // The inbox is not read again here: under the default behavior that is a whole inbox page
   // load, about thirty requests, for each message in a thread not listed. A person refreshes.
   private func markInboxStale() async {
      isInboxStale = true
   }

   // The engine's count moved by a thread this store saw change: one it opened, which the read
   // marked read, or one a listener message made unread. The count stays the engine's, read
   // again whole with the next inbox load; between loads only these changes are applied to it.
   private func adjustUnreadCount(by change: Int) {
      guard let counts = unreadCounts else {
         return
      }

      unreadCounts = Engine.UnreadCounts(inbox: max(0, counts.inbox + change), pending: counts.pending)
   }

   private static func describe(_ reason: Engine.ListenerStopReason) -> String {
      switch reason {
         case .checkpoint:
            return "Instagram asked for a security check, so the listener stopped."

         case .error(.upstreamRejected(let code?)):
            return "The listener stopped because Instagram refused a poll (\(code))."

         case .error(let error):
            return "The listener stopped. \(HomeStore.describe(error))"
      }
   }
}
