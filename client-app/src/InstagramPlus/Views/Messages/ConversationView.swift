import AppKit
import SwiftUI

struct ConversationView: View {
   @Environment(DirectStore.self) private var direct
   @Environment(NavigationStore.self) private var navigation

   let thread: DirectThread

   @State private var draft = ""
   @State private var isShowingDetails = false
   @State private var replyTarget: DirectMessage?
   @State private var isPickingPhoto = false

   var body: some View {
      HStack(spacing: 0) {
         VStack(spacing: 0) {
            header
            Hairline()

            LoadStateContainer(state: direct.messageState(for: thread.id), loadingLabel: "Loading conversation", retry: reload) {
               messageList
            }
            .frame(maxHeight: .infinity)

            if direct.isRequest(thread.id) {
               requestBanner
            } else {
               composer
            }
         }

         if isShowingDetails {
            Hairline(axis: .vertical)

            details
               .frame(width: 280)
               .background(Palette.panel)
         }
      }
      .background(Palette.card)
      .task {
         if !direct.messageState(for: thread.id).hasLoaded {
            await direct.loadMessages(thread.id)
         }
      }
      .fileImporter(isPresented: $isPickingPhoto, allowedContentTypes: [.image]) { result in
         if case .success(let url) = result {
            Task { await direct.sendPhoto(url, to: thread.id) }
         }
      }
   }

   private func reload() {
      Task { await direct.loadMessages(thread.id) }
   }

   private var header: some View {
      HStack(spacing: 12) {
         ThreadAvatar(thread: thread, diameter: 44)

         VStack(alignment: .leading, spacing: 2) {
            Text(thread.title)
               .font(.system(size: 16, weight: .semibold))
               .foregroundStyle(Palette.textPrimary)
               .lineLimit(1)

            Text(thread.isGroup ? "\(thread.participants.count + 1) members" : thread.participants.first?.username ?? "")
               .font(.system(size: 12))
               .foregroundStyle(Palette.textSecondary)
         }

         Spacer()

         HStack(spacing: 20) {
            Image(systemName: "phone")
               .foregroundStyle(Palette.textTertiary)
               .help("Calls are not in the engine")

            Image(systemName: "video")
               .foregroundStyle(Palette.textTertiary)
               .help("Calls are not in the engine")

            Button {
               withAnimation(.easeOut(duration: 0.2)) {
                  isShowingDetails.toggle()
               }
            } label: {
               Image(systemName: isShowingDetails ? "info.circle.fill" : "info.circle")
                  .foregroundStyle(Palette.textPrimary)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Conversation details")
         }
         .font(.system(size: 19))
      }
      .padding(.horizontal, 20)
      .frame(height: 76)
   }

   private var messageList: some View {
      let messages = direct.messages(in: thread.id)

      return ScrollViewReader { proxy in
         ScrollView {
            LazyVStack(spacing: 2) {
               if direct.hasOlderMessages(thread.id) {
                  Button(direct.loadingOlder.contains(thread.id) ? "Loading" : "Load earlier messages") {
                     Task { await direct.loadOlder(thread.id) }
                  }
                  .buttonStyle(.plain)
                  .font(.system(size: 12, weight: .semibold))
                  .foregroundStyle(Palette.link)
                  .padding(.bottom, 16)
               } else {
                  conversationIntro
                     .padding(.bottom, 28)
               }

               ForEach(Array(messages.enumerated()), id: \.element.id) { position, message in
                  let previous = position > 0 ? messages[position - 1] : nil
                  let next = position + 1 < messages.count ? messages[position + 1] : nil
                  let isOutgoing = message.senderID == direct.viewerID

                  if startsNewDay(message, after: previous) {
                     Text(message.sentAt.formatted(date: .abbreviated, time: .shortened))
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(Palette.textSecondary)
                        .padding(.vertical, 14)
                  }

                  MessageBubble(
                     message: message,
                     sender: sender(of: message),
                     quoted: message.repliedToID.flatMap { direct.message($0, in: thread.id) },
                     isOutgoing: isOutgoing,
                     showsSender: thread.isGroup && previous?.senderID != message.senderID,
                     endsGroup: next?.senderID != message.senderID
                  ) {
                     Task { await direct.toggleReaction(message.id, in: thread.id) }
                  } resend: {
                     Task { await direct.resend(message.id, in: thread.id) }
                  } recheck: {
                     Task { await direct.loadMessages(thread.id) }
                  }
                  .contextMenu {
                     if message.delivery == .sent {
                        Button("Reply") {
                           replyTarget = message
                        }

                        Button(message.viewerReacted ? "Remove like" : "Like") {
                           Task { await direct.toggleReaction(message.id, in: thread.id) }
                        }
                     }

                     if isOutgoing, message.delivery == .sent {
                        Button("Unsend", role: .destructive) {
                           Task { await direct.unsend(message.id, in: thread.id) }
                        }
                     }

                     Button("Copy") {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(message.text, forType: .string)
                     }
                  }
                  .id(message.id)
               }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 20)
         }
         .onAppear {
            proxy.scrollTo(messages.last?.id, anchor: .bottom)
         }
         .onChange(of: messages.count) {
            withAnimation {
               proxy.scrollTo(direct.messages(in: thread.id).last?.id, anchor: .bottom)
            }
         }
      }
   }

   private var conversationIntro: some View {
      VStack(spacing: 6) {
         ThreadAvatar(thread: thread, diameter: 88)

         Text(thread.title)
            .font(.system(size: 18, weight: .semibold))
            .foregroundStyle(Palette.textPrimary)
            .padding(.top, 8)

         if let participant = thread.participants.first, !thread.isGroup {
            Text("\(participant.username) on Instagram")
               .font(.system(size: 13))
               .foregroundStyle(Palette.textSecondary)

            PrimaryButton(title: "View profile", isProminent: false) {
               navigation.openProfile(participant.id)
            }
            .padding(.top, 10)
         }
      }
      .frame(maxWidth: .infinity)
      .padding(.top, 12)
   }

   private var requestBanner: some View {
      let isPending = direct.pendingRequestIDs.contains(thread.id)

      return VStack(spacing: 10) {
         Text("\(thread.title) wants to send you a message. They won't know you've seen it until you accept.")
            .font(.system(size: 12))
            .foregroundStyle(Palette.textSecondary)
            .multilineTextAlignment(.center)

         HStack(spacing: 10) {
            PrimaryButton(title: "Delete", isProminent: false) {
               Task { await direct.resolveRequest(thread.id, accept: false) }
            }

            PrimaryButton(title: "Accept") {
               Task { await direct.resolveRequest(thread.id, accept: true) }
            }
         }
         .disabled(isPending)
      }
      .padding(16)
      .frame(maxWidth: .infinity)
      .overlay(alignment: .top) { Hairline() }
   }

   private var composer: some View {
      let hasDraft = !draft.trimmingCharacters(in: .whitespaces).isEmpty

      return VStack(spacing: 0) {
         if let replyTarget {
            HStack(spacing: 8) {
               Rectangle()
                  .fill(Palette.link)
                  .frame(width: 3)

               VStack(alignment: .leading, spacing: 2) {
                  Text(replyTarget.senderID == direct.viewerID ? "Replying to yourself" : "Replying to \(sender(of: replyTarget)?.displayName ?? "them")")
                     .font(.system(size: 11, weight: .semibold))

                  Text(replyTarget.text.isEmpty ? "Photo" : replyTarget.text)
                     .font(.system(size: 12))
                     .foregroundStyle(Palette.textSecondary)
                     .lineLimit(1)
               }

               Spacer()

               Button {
                  self.replyTarget = nil
               } label: {
                  Image(systemName: "xmark")
                     .font(.system(size: 10, weight: .bold))
               }
               .buttonStyle(.plain)
            }
            .frame(height: 36)
            .padding(.horizontal, 22)
            .padding(.top, 10)
         }

         HStack(spacing: 14) {
            Button {
               NSApp.orderFrontCharacterPalette(nil)
            } label: {
               Image(systemName: "face.smiling")
                  .font(.system(size: 20))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Emoji")

            TextField("Message", text: $draft)
               .textFieldStyle(.plain)
               .font(.system(size: 14))
               .onSubmit(send)

            if hasDraft {
               Button("Send", action: send)
                  .buttonStyle(.plain)
                  .font(.system(size: 14, weight: .semibold))
                  .foregroundStyle(Palette.link)
            } else {
               Image(systemName: "mic")
                  .foregroundStyle(Palette.textTertiary)
                  .help("Voice messages are not supported")

               Button {
                  isPickingPhoto = true
               } label: {
                  Image(systemName: "photo")
               }
               .buttonStyle(.plain)
               .accessibilityLabel("Send a photo")

               Button {
                  Task { await direct.send(Engine.Reaction.heart, to: thread.id) }
               } label: {
                  Image(systemName: "heart")
               }
               .buttonStyle(.plain)
               .accessibilityLabel("Send a heart")
            }
         }
         .font(.system(size: 18))
         .foregroundStyle(Palette.textPrimary)
         .padding(.horizontal, 18)
         .frame(height: 46)
         .overlay(Capsule().strokeBorder(Palette.hairline))
         .padding(16)
      }
   }

   private var details: some View {
      VStack(alignment: .leading, spacing: 0) {
         Text("Details")
            .font(.system(size: 16, weight: .semibold))
            .foregroundStyle(Palette.textPrimary)
            .padding(20)

         Hairline()

         Toggle("Mute messages", isOn: Binding(
            get: { thread.isMuted },
            set: { newValue in
               Task { await direct.setMuted(newValue, threadID: thread.id) }
            }
         ))
         .toggleStyle(.switch)
         .font(.system(size: 13))
         .padding(20)

         Hairline()

         Text("Members")
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(Palette.textPrimary)
            .padding(.horizontal, 20)
            .padding(.top, 18)

         ForEach(thread.participants) { participant in
            HStack(spacing: 10) {
               AvatarLink(account: participant, diameter: 36)

               VStack(alignment: .leading, spacing: 1) {
                  AccountLink(account: participant, size: 13)

                  Text(participant.username)
                     .font(.system(size: 11))
                     .foregroundStyle(Palette.textSecondary)
               }
            }
            .padding(.horizontal, 20)
            .padding(.top, 12)
         }

         Spacer()
      }
   }

   private func sender(of message: DirectMessage) -> Account? {
      thread.participants.first { $0.id == message.senderID }
   }

   private func startsNewDay(_ message: DirectMessage, after previous: DirectMessage?) -> Bool {
      guard let previous else {
         return true
      }

      let gap = message.sentAt.timeIntervalSince(previous.sentAt)
      return gap > 60 * 60
   }

   private func send() {
      let text = draft
      let repliedToID = replyTarget?.id
      draft = ""
      replyTarget = nil

      Task { await direct.send(text, to: thread.id, replyingTo: repliedToID) }
   }
}

private struct MessageBubble: View {
   let message: DirectMessage
   let sender: Account?
   let quoted: DirectMessage?
   let isOutgoing: Bool
   let showsSender: Bool
   let endsGroup: Bool
   let react: () -> Void
   let resend: () -> Void
   let recheck: () -> Void

   var body: some View {
      let showsAvatar = !isOutgoing && endsGroup
      let hasReaction = message.reactionCount > 0
      let isSettled = message.delivery == .sent

      VStack(alignment: isOutgoing ? .trailing : .leading, spacing: 4) {
         if showsSender, !isOutgoing, let sender {
            Text(sender.displayName)
               .font(.system(size: 11))
               .foregroundStyle(Palette.textSecondary)
               .padding(.leading, 50)
               .padding(.top, 8)
         }

         HStack(alignment: .bottom, spacing: 8) {
            if isOutgoing {
               Spacer(minLength: 120)
            } else {
               Group {
                  if showsAvatar, let sender {
                     Avatar(account: sender, diameter: 28)
                  } else {
                     Color.clear
                  }
               }
               .frame(width: 28, height: 28)
            }

            VStack(alignment: isOutgoing ? .trailing : .leading, spacing: 4) {
               if let quoted {
                  Text(quoted.text.isEmpty ? "Photo" : quoted.text)
                     .font(.system(size: 12))
                     .foregroundStyle(Palette.textSecondary)
                     .lineLimit(2)
                     .padding(.horizontal, 12)
                     .padding(.vertical, 7)
                     .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Palette.hairline))
               }

               bubbleContent
            }
            .opacity(isSettled ? 1 : 0.6)
               .overlay(alignment: isOutgoing ? .bottomLeading : .bottomTrailing) {
                  if hasReaction {
                     Image(systemName: "heart.fill")
                        .font(.system(size: 10))
                        .foregroundStyle(Color(hex: 0xED4956))
                        .padding(5)
                        .background(Palette.card, in: Circle())
                        .overlay(Circle().strokeBorder(Palette.hairline))
                        .offset(x: isOutgoing ? -8 : 8, y: 12)
                  }
               }
               .help(message.sentAt.formatted(date: .abbreviated, time: .shortened))
               .onTapGesture(count: 2, perform: react)

            if !isOutgoing {
               Spacer(minLength: 120)
            }
         }

         deliveryStatus
      }
      .padding(.bottom, hasReaction ? 14 : (endsGroup ? 8 : 0))
   }

   @ViewBuilder
   private var bubbleContent: some View {
      if let imageURL = message.imageURL {
         MediaView(seed: message.id, url: imageURL, cornerRadius: 18)
            .frame(width: 220, height: 220)
      } else {
         Text(message.text)
            .font(.system(size: 15))
            .lineSpacing(2)
            .foregroundStyle(isOutgoing ? Color.white : Palette.textPrimary)
            .padding(.horizontal, 14)
            .padding(.vertical, 9)
            .background(isOutgoing ? Palette.outgoingBubble : Palette.incomingBubble, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
      }
   }

   @ViewBuilder
   private var deliveryStatus: some View {
      switch message.delivery {
         case .sent:
            EmptyView()

         case .sending:
            Text("Sending")
               .font(.system(size: 11))
               .foregroundStyle(Palette.textSecondary)

         case .failed:
            HStack(spacing: 6) {
               Text("Not delivered.")
                  .foregroundStyle(Palette.badge)

               Button("Send again", action: resend)
                  .buttonStyle(.plain)
                  .foregroundStyle(Palette.link)
            }
            .font(.system(size: 11, weight: .medium))

         case .uncertain:
            HStack(spacing: 6) {
               Text("Couldn't confirm this was delivered.")
                  .foregroundStyle(Color(hex: 0xE3A008))

               Button("Check", action: recheck)
                  .buttonStyle(.plain)
                  .foregroundStyle(Palette.link)
            }
            .font(.system(size: 11, weight: .medium))
      }
   }
}
