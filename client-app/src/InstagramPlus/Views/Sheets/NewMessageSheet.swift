import SwiftUI

struct NewMessageSheet: View {
   @Environment(SearchStore.self) private var search
   @Environment(DirectStore.self) private var direct
   @Environment(NavigationStore.self) private var navigation
   @Environment(\.dismiss) private var dismiss

   @State private var query = ""
   @State private var selected: [Account] = []
   @State private var isCreating = false

   var body: some View {
      let canChat = !selected.isEmpty && !isCreating

      VStack(spacing: 0) {
         SheetHeader(title: "New message") { dismiss() }

         HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text("To:")
               .font(.system(size: 13, weight: .semibold))

            ForEach(selected) { account in
               Button {
                  selected.removeAll { $0.id == account.id }
               } label: {
                  HStack(spacing: 4) {
                     Text(account.username)
                     Image(systemName: "xmark")
                        .font(.system(size: 9, weight: .bold))
                  }
                  .font(.system(size: 12, weight: .medium))
                  .foregroundStyle(Palette.link)
                  .padding(.horizontal, 8)
                  .padding(.vertical, 4)
                  .background(Palette.link.opacity(0.12), in: Capsule())
               }
               .buttonStyle(.plain)
            }

            TextField("Search", text: $query)
               .textFieldStyle(.plain)
         }
         .padding(16)

         Hairline()

         ScrollView {
            VStack(spacing: 2) {
               if query.isEmpty {
                  Text("Search for people to message.")
                     .font(.system(size: 13))
                     .foregroundStyle(Palette.textSecondary)
                     .padding(24)
               } else if search.resultsState.isLoading {
                  LoadingStateView(label: "Searching")
               } else {
                  ForEach(search.results) { account in
                     let isSelected = selected.contains { $0.id == account.id }

                     Button {
                        if isSelected {
                           selected.removeAll { $0.id == account.id }
                        } else {
                           selected.append(account)
                        }
                     } label: {
                        HStack(spacing: 12) {
                           Avatar(account: account, diameter: 40)

                           VStack(alignment: .leading, spacing: 2) {
                              Text(account.displayName)
                                 .font(.system(size: 13, weight: .semibold))

                              Text(account.username)
                                 .font(.system(size: 12))
                                 .foregroundStyle(Palette.textSecondary)
                           }

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
         }
         .frame(maxHeight: .infinity)

         Hairline()

         Button(isCreating ? "Opening" : "Chat") {
            isCreating = true

            Task {
               let didOpen = await direct.createThread(with: selected)
               isCreating = false

               if didOpen {
                  navigation.route = .messages
                  dismiss()
               }
            }
         }
         .buttonStyle(GradientButtonStyle())
         .disabled(!canChat)
         .padding(16)
      }
      .frame(width: 400, height: 520)
      .task(id: query) {
         await search.search(query)
      }
   }
}
