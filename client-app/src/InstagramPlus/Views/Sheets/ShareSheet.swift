import AppKit
import SwiftUI

struct ShareSheet: View {
   @Environment(HomeStore.self) private var home
   @Environment(DirectStore.self) private var direct
   @Environment(\.dismiss) private var dismiss

   let postPK: Post.ID

   @State private var selectedThreadIDs: Set<DirectThread.ID> = []
   @State private var filter = ""
   @State private var isSending = false
   @State private var didCopy = false

   var body: some View {
      let post = home.post(pk: postPK)
      let canSend = !selectedThreadIDs.isEmpty && !isSending

      VStack(spacing: 0) {
         SheetHeader(title: "Share") { dismiss() }

         TextField("Search", text: $filter)
            .textFieldStyle(.roundedBorder)
            .padding(16)

         ScrollView {
            VStack(spacing: 2) {
               ForEach(visibleThreads) { thread in
                  let isSelected = selectedThreadIDs.contains(thread.id)

                  Button {
                     if isSelected {
                        selectedThreadIDs.remove(thread.id)
                     } else {
                        selectedThreadIDs.insert(thread.id)
                     }
                  } label: {
                     HStack(spacing: 12) {
                        ThreadAvatar(thread: thread, diameter: 40)

                        Text(thread.title)
                           .font(.system(size: 13, weight: .medium))
                           .lineLimit(1)

                        Spacer()

                        Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                           .font(.system(size: 18))
                           .foregroundStyle(isSelected ? Palette.link : Palette.textTertiary)
                     }
                     .padding(.horizontal, 16)
                     .padding(.vertical, 6)
                     .contentShape(Rectangle())
                  }
                  .buttonStyle(.plain)
               }
            }
         }
         .frame(maxHeight: .infinity)

         Hairline()

         HStack {
            Button(didCopy ? "Link copied" : "Copy link") {
               guard let post else {
                  return
               }

               NSPasteboard.general.clearContents()
               NSPasteboard.general.setString("https://www.instagram.com/p/\(post.code)/", forType: .string)
               didCopy = true
            }

            Spacer()

            Button(isSending ? "Sending" : "Send") {
               isSending = true

               Task {
                  let didShare = await home.share(postPK: postPK, to: Array(selectedThreadIDs))
                  isSending = false

                  if didShare {
                     dismiss()
                  }
               }
            }
            .keyboardShortcut(.defaultAction)
            .disabled(!canSend)
         }
         .padding(16)
      }
      .frame(width: 380, height: 500)
      .task {
         if !direct.inboxState.hasLoaded {
            await direct.loadInbox()
         }
      }
   }

   private var visibleThreads: [DirectThread] {
      let needle = filter.lowercased()
      let threads = direct.orderedThreads

      guard !needle.isEmpty else {
         return threads
      }

      return threads.filter { $0.title.lowercased().contains(needle) }
   }
}

struct SheetHeader: View {
   let title: String
   let close: () -> Void

   var body: some View {
      HStack {
         Text(title)
            .font(.system(size: 16, weight: .semibold))

         Spacer()

         Button("Cancel", action: close)
            .keyboardShortcut(.cancelAction)
      }
      .padding(16)
      .overlay(alignment: .bottom) { Hairline() }
   }
}
