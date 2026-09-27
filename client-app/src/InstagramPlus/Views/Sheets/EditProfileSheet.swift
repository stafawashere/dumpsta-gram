import SwiftUI

struct EditProfileSheet: View {
   @Environment(ProfileStore.self) private var profiles
   @Environment(\.dismiss) private var dismiss

   @State private var fullName = ""
   @State private var biography = ""
   @State private var website = ""
   @State private var isSaving = false

   private static let bioLimit = 150

   var body: some View {
      let isWithinLimit = biography.count <= Self.bioLimit
      let hasName = !fullName.trimmingCharacters(in: .whitespaces).isEmpty
      let canSave = isWithinLimit && hasName && !isSaving

      VStack(alignment: .leading, spacing: 0) {
         SheetHeader(title: "Edit profile") { dismiss() }

         VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 14) {
               Avatar(account: profiles.viewerAccount, diameter: 56, style: .soft)

               VStack(alignment: .leading, spacing: 2) {
                  Text(profiles.viewerAccount.username)
                     .font(.system(size: 15, weight: .semibold))

                  Text("Changing the photo is not supported yet")
                     .font(.system(size: 12))
                     .foregroundStyle(Palette.textTertiary)
               }
            }

            LabeledField(title: "Name") {
               TextField("Name", text: $fullName)
            }

            LabeledField(title: "Website") {
               TextField("Website", text: $website)
            }

            LabeledField(title: "Bio") {
               VStack(alignment: .trailing, spacing: 4) {
                  TextEditor(text: $biography)
                     .font(.system(size: 13))
                     .frame(height: 80)
                     .scrollContentBackground(.hidden)
                     .padding(4)
                     .background(Palette.field, in: RoundedRectangle(cornerRadius: 8))

                  Text("\(biography.count)/\(Self.bioLimit)")
                     .font(.system(size: 11))
                     .foregroundStyle(isWithinLimit ? Palette.textTertiary : Palette.badge)
               }
            }
         }
         .textFieldStyle(.roundedBorder)
         .padding(20)

         HStack {
            Spacer()

            Button(isSaving ? "Saving" : "Save") {
               isSaving = true

               Task {
                  let trimmedWebsite = website.trimmingCharacters(in: .whitespaces)
                  let didSave = await profiles.editProfile(fullName: fullName, biography: biography, website: trimmedWebsite.isEmpty ? nil : trimmedWebsite)
                  isSaving = false

                  if didSave {
                     dismiss()
                  }
               }
            }
            .keyboardShortcut(.defaultAction)
            .disabled(!canSave)
         }
         .padding(16)
      }
      .frame(width: 440)
      .onAppear {
         let details = profiles.viewer
         fullName = details?.account.displayName ?? ""
         biography = details?.bio ?? ""
         website = details?.website ?? ""
      }
   }
}

private struct LabeledField<Content: View>: View {
   let title: String
   @ViewBuilder let content: Content

   var body: some View {
      VStack(alignment: .leading, spacing: 6) {
         Text(title)
            .font(.system(size: 12, weight: .semibold))
            .foregroundStyle(Palette.textSecondary)

         content
      }
   }
}
