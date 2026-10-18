import SwiftUI

struct MessagesView: View {
   @Environment(DirectStore.self) private var direct
   @Environment(ProfileStore.self) private var profiles
   @Environment(NavigationStore.self) private var navigation
   @Environment(EngineGateway.self) private var gateway

   @State private var filter = ""
   @State private var isComposingNote = false
   @State private var isShowingRequests = false

   var body: some View {
      HStack(spacing: 0) {
         threadList
            .frame(width: 340)
            .background(Palette.panel)

         Hairline(axis: .vertical)

         if let thread = direct.selectedThread {
            ConversationView(thread: thread)
               .id(thread.id)
         } else {
            EmptyStateView(
               symbolName: "paperplane",
               title: "Your messages",
               message: "Send private photos and messages to a friend or group."
            )
         }
      }
      .task {
         // The inbox load brings the notes and the unread count with it. Requests are their own
         // read, sent once here and again on a refresh.
         if !direct.inboxState.hasLoaded {
            await direct.loadInbox()
         }

         if !direct.requestsState.hasLoaded {
            await direct.loadRequests()
         }
      }
      .sheet(isPresented: $isComposingNote) {
         NoteComposer()
      }
   }

   private var visibleThreads: [DirectThread] {
      let needle = filter.trimmingCharacters(in: .whitespaces).lowercased()
      let source = isShowingRequests ? direct.requests : direct.orderedThreads

      guard !needle.isEmpty else {
         return source
      }

      return source.filter { $0.title.lowercased().contains(needle) }
   }

   private var threadList: some View {
      VStack(alignment: .leading, spacing: 0) {
         HStack(spacing: 8) {
            Text(profiles.viewerAccount.username)
               .font(.system(size: 18, weight: .bold))
               .foregroundStyle(Palette.textPrimary)

            ListenerBadge(isListening: direct.isListening, problem: direct.listenerProblem) {
               Task { await direct.startListening() }
            }

            Spacer()

            Button {
               navigation.isComposingMessage = true
            } label: {
               Image(systemName: "square.and.pencil")
                  .font(.system(size: 17))
                  .foregroundStyle(gateway.isWired(.newThread) ? Palette.textPrimary : Palette.textTertiary)
            }
            .buttonStyle(.plain)
            .disabled(!gateway.isWired(.newThread))
            .help(gateway.isWired(.newThread) ? "New message" : Engine.UnwiredWrite.newThread.tooltip)
            .accessibilityLabel("New message")
         }
         .padding(.horizontal, 22)
         .padding(.top, 24)

         NotesTray(notes: direct.notes, state: direct.notesState, viewer: profiles.viewerAccount, viewerNote: direct.viewerNote) {
            isComposingNote = true
         } retry: {
            Task { await direct.loadNotes() }
         }
         .padding(.top, 16)

         HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
               .font(.system(size: 12))
               .foregroundStyle(Palette.textSecondary)

            TextField("Search messages", text: $filter)
               .textFieldStyle(.plain)
               .font(.system(size: 13))
         }
         .padding(.horizontal, 14)
         .frame(height: 36)
         .background(Palette.raised, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
         .padding(.horizontal, 22)
         .padding(.top, 14)

         HStack {
            Button("Messages") {
               isShowingRequests = false
            }
            .buttonStyle(.plain)
            .font(.system(size: 15, weight: .semibold))
            .foregroundStyle(isShowingRequests ? Palette.textSecondary : Palette.textPrimary)

            Spacer()

            Button {
               isShowingRequests = true
            } label: {
               HStack(spacing: 4) {
                  Text("Requests")

                  if !direct.requests.isEmpty {
                     Text(String(direct.requests.count))
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 5)
                        .background(Palette.link, in: Capsule())
                  }
               }
            }
            .buttonStyle(.plain)
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(isShowingRequests ? Palette.textPrimary : Palette.textSecondary)
         }
         .padding(.horizontal, 22)
         .padding(.top, 18)
         .padding(.bottom, 8)

         LoadStateContainer(state: isShowingRequests ? direct.requestsState : direct.inboxState, loadingLabel: "Loading inbox", retry: reload) {
            ScrollView {
               LazyVStack(spacing: 0) {
                  if visibleThreads.isEmpty {
                     Text(emptyListText)
                        .font(.system(size: 13))
                        .foregroundStyle(Palette.textSecondary)
                        .padding(24)
                  }

                  if !isShowingRequests, direct.isInboxStale {
                     HStack {
                        Text("New activity in a conversation not listed here.")
                           .font(.system(size: 12))
                           .foregroundStyle(Palette.textSecondary)

                        Spacer()

                        Button("Refresh", action: reload)
                           .buttonStyle(.plain)
                           .font(.system(size: 12, weight: .semibold))
                           .foregroundStyle(Palette.link)
                     }
                     .padding(.horizontal, 22)
                     .padding(.vertical, 10)
                  }

                  ForEach(visibleThreads) { thread in
                     ThreadRow(
                        thread: thread,
                        isSelected: thread.id == direct.selectedThreadID
                     ) {
                        Task { await direct.select(thread.id) }
                     }
                  }

                  if !isShowingRequests, direct.hasMoreThreads {
                     Button(direct.isLoadingMoreThreads ? "Loading conversations" : "Load more conversations") {
                        Task { await direct.loadMoreThreads() }
                     }
                     .buttonStyle(.plain)
                     .font(.system(size: 13, weight: .semibold))
                     .foregroundStyle(Palette.textSecondary)
                     .disabled(direct.isLoadingMoreThreads)
                     .padding(16)
                  }
               }
            }
         }
      }
   }

   private var emptyListText: String {
      let isFiltering = !filter.trimmingCharacters(in: .whitespaces).isEmpty

      if isFiltering {
         return "No conversations match."
      }

      return isShowingRequests ? "No message requests." : "No messages yet."
   }

   private func reload() {
      Task {
         await direct.loadInbox()
         await direct.loadRequests()
      }
   }
}

private struct ListenerBadge: View {
   let isListening: Bool
   let problem: String?
   let restart: () -> Void

   var body: some View {
      if isListening {
         HStack(spacing: 4) {
            Circle()
               .fill(Palette.online)
               .frame(width: 6, height: 6)

            Text("Live")
               .font(.system(size: 10, weight: .semibold))
               .foregroundStyle(Palette.textSecondary)
         }
         .help("New messages arrive through the engine's polling listener")
      } else if let problem {
         HStack(spacing: 6) {
            Text("Live stopped")
               .font(.system(size: 10, weight: .semibold))
               .foregroundStyle(Palette.textSecondary)

            Button("Resume", action: restart)
               .buttonStyle(.plain)
               .font(.system(size: 10, weight: .semibold))
               .foregroundStyle(Palette.badge)
         }
         .help(problem)
         .accessibilityElement(children: .combine)
         .accessibilityLabel("Live stopped. \(problem)")
      }
   }
}

private struct NotesTray: View {
   let notes: [Note]
   let state: LoadState
   let viewer: Account
   let viewerNote: Note?
   let compose: () -> Void
   let retry: () -> Void

   var body: some View {
      let otherNotes = notes.filter { $0.author.id != viewer.id }

      ScrollView(.horizontal) {
         HStack(alignment: .top, spacing: 14) {
            Button(action: compose) {
               NoteBubble(author: viewer, text: viewerNote?.text ?? "Your note", isPlaceholder: viewerNote == nil, isCloseFriends: viewerNote?.isCloseFriends ?? false, isPending: viewerNote?.isPending ?? false)
            }
            .buttonStyle(.plain)

            ForEach(otherNotes) { note in
               NoteBubble(author: note.author, text: note.text, isPlaceholder: false, isCloseFriends: note.isCloseFriends)
            }

            trayStatus(isEmpty: otherNotes.isEmpty)
               .frame(height: 48)
               .padding(.top, 26)
         }
         .padding(.horizontal, 22)
      }
      .scrollIndicators(.never)
   }

   @ViewBuilder
   private func trayStatus(isEmpty: Bool) -> some View {
      switch state {
         case .idle, .notFound:
            EmptyView()

         case .loading:
            HStack(spacing: 6) {
               ProgressView()
                  .controlSize(.small)

               Text("Loading notes")
            }
            .font(.system(size: 11))
            .foregroundStyle(Palette.textSecondary)

         case .failed(let message):
            HStack(spacing: 6) {
               Text("Notes did not load.")
                  .help(message)

               Button("Retry", action: retry)
                  .buttonStyle(.plain)
                  .font(.system(size: 11, weight: .semibold))
                  .foregroundStyle(Palette.link)
            }
            .font(.system(size: 11))
            .foregroundStyle(Palette.textSecondary)

         case .loaded:
            if isEmpty {
               Text("No notes from people you follow right now.")
                  .font(.system(size: 11))
                  .foregroundStyle(Palette.textTertiary)
                  .frame(maxWidth: 150, alignment: .leading)
            }
      }
   }
}

private struct NoteBubble: View {
   let author: Account
   let text: String
   let isPlaceholder: Bool
   let isCloseFriends: Bool
   var isPending = false

   var body: some View {
      VStack(spacing: 6) {
         Text(text)
            .font(.system(size: 10, weight: isPlaceholder ? .regular : .medium))
            .foregroundStyle(isPlaceholder ? Palette.textTertiary : Palette.textPrimary)
            .lineLimit(2)
            .multilineTextAlignment(.center)
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            .frame(maxWidth: 76)
            .background(Palette.card, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(isCloseFriends ? Palette.online : Palette.hairline))

         Avatar(account: author, diameter: 48)

         Text(isPending ? "Sharing, paced" : isPlaceholder ? "Your note" : author.username)
            .font(.system(size: 10))
            .foregroundStyle(Palette.textSecondary)
            .lineLimit(1)
            .frame(width: 70)
      }
      .opacity(isPending ? 0.6 : 1)
      .help(isPending ? "The note shows now and is shared when the engine's pacer lets the write go, about 30 seconds apart." : "")
   }
}

private struct NoteComposer: View {
   @Environment(DirectStore.self) private var direct
   @Environment(\.dismiss) private var dismiss

   @State private var text = ""
   @State private var closeFriendsOnly = false
   @State private var isSaving = false

   private static let limit = 60

   var body: some View {
      let trimmedText = text.trimmingCharacters(in: .whitespacesAndNewlines)
      let isWithinLimit = text.count <= Self.limit
      let canShare = !trimmedText.isEmpty && isWithinLimit && !isSaving

      VStack(alignment: .leading, spacing: 16) {
         Text("New note")
            .font(.system(size: 17, weight: .semibold))

         TextField("Share a thought", text: $text)
            .textFieldStyle(.roundedBorder)

         HStack {
            Toggle("Close friends only", isOn: $closeFriendsOnly)
               .toggleStyle(.switch)

            Spacer()

            Text("\(text.count)/\(Self.limit)")
               .font(.system(size: 11))
               .foregroundStyle(isWithinLimit ? Palette.textTertiary : Palette.badge)
         }

         Text("Notes last 24 hours and show at the top of your followers' inboxes.")
            .font(.system(size: 12))
            .foregroundStyle(Palette.textSecondary)

         HStack {
            // The store updates the tray at once and settles it when the paced write answers, so
            // the sheet closes without waiting for the write.
            if let viewerNote = direct.viewerNote, !viewerNote.isPending {
               Button("Delete current note", role: .destructive) {
                  Task { await direct.deleteViewerNote() }
                  dismiss()
               }
            }

            Spacer()

            Button("Cancel") { dismiss() }
               .keyboardShortcut(.cancelAction)

            Button("Share") {
               isSaving = true
               Task { await direct.setNote(trimmedText, closeFriendsOnly: closeFriendsOnly) }
               dismiss()
            }
            .keyboardShortcut(.defaultAction)
            .disabled(!canShare)
         }
      }
      .padding(24)
      .frame(width: 380)
   }
}

private struct ThreadRow: View {
   let thread: DirectThread
   let isSelected: Bool
   let action: () -> Void

   @State private var isHovered = false

   var body: some View {
      let snippet = thread.snippet ?? "Start a conversation"
      let preview = thread.lastSenderIsViewer ? "You: \(snippet)" : snippet
      let showsHover = isHovered && !isSelected

      Button(action: action) {
         HStack(spacing: 12) {
            ThreadAvatar(thread: thread, diameter: 52)

            VStack(alignment: .leading, spacing: 3) {
               Text(thread.title)
                  .font(.system(size: 14, weight: thread.isUnread ? .semibold : .regular))
                  .foregroundStyle(Palette.textPrimary)
                  .lineLimit(1)

               HStack(spacing: 6) {
                  Text(preview)
                     .lineLimit(1)

                  Text(RelativeTime.short(since: thread.lastActivity))
                     .foregroundStyle(Palette.textTertiary)
                     .layoutPriority(1)
               }
               .font(.system(size: 12, weight: thread.isUnread ? .semibold : .regular))
               .foregroundStyle(thread.isUnread ? Palette.textPrimary : Palette.textSecondary)
            }

            Spacer(minLength: 4)

            if thread.isMuted {
               Image(systemName: "bell.slash")
                  .font(.system(size: 11))
                  .foregroundStyle(Palette.textTertiary)
            }

            if thread.isUnread {
               Circle()
                  .fill(Palette.link)
                  .frame(width: 8, height: 8)
            }
         }
         .padding(.horizontal, 22)
         .padding(.vertical, 9)
         .background(isSelected ? Palette.raised : (showsHover ? Palette.raised.opacity(0.6) : Color.clear))
         .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
      .onHover { isHovered = $0 }
   }
}

struct ThreadAvatar: View {
   let thread: DirectThread
   let diameter: CGFloat

   var body: some View {
      if thread.isGroup, thread.participants.count >= 2 {
         ZStack(alignment: .bottomTrailing) {
            Avatar(account: thread.participants[0], diameter: diameter * 0.72)
               .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

            Avatar(account: thread.participants[1], diameter: diameter * 0.72)
               .overlay(Circle().strokeBorder(Palette.panel, lineWidth: 2))
         }
         .frame(width: diameter, height: diameter)
      } else if let participant = thread.participants.first {
         Avatar(account: participant, diameter: diameter)
      }
   }
}
