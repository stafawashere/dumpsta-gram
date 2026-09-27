import SwiftUI

struct SectionTitle: View {
   let text: String
   var size: CGFloat = 20

   var body: some View {
      Text(text)
         .font(.system(size: size, weight: .semibold))
         .foregroundStyle(Palette.textPrimary)
   }
}

struct EmptyStateView: View {
   let symbolName: String
   let title: String
   let message: String
   var actionTitle: String?
   var action: () -> Void = {}

   var body: some View {
      VStack(spacing: 14) {
         Image(systemName: symbolName)
            .font(.system(size: 34, weight: .light))
            .foregroundStyle(Palette.textPrimary)
            .frame(width: 88, height: 88)
            .overlay(Circle().strokeBorder(Palette.textPrimary, lineWidth: 1.5))

         Text(title)
            .font(.system(size: 20, weight: .semibold))
            .foregroundStyle(Palette.textPrimary)
            .padding(.top, 4)

         Text(message)
            .font(.system(size: 14))
            .foregroundStyle(Palette.textSecondary)
            .multilineTextAlignment(.center)
            .frame(maxWidth: 340)

         if let actionTitle {
            PrimaryButton(title: actionTitle, action: action)
               .padding(.top, 6)
         }
      }
      .frame(maxWidth: .infinity, maxHeight: .infinity)
      .padding(40)
   }
}

struct PrimaryButton: View {
   let title: String
   var isProminent = true
   let action: () -> Void

   var body: some View {
      Button(action: action) {
         Text(title)
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(isProminent ? Color.white : Palette.textPrimary)
            .padding(.horizontal, 16)
            .frame(height: 32)
            .background(isProminent ? Palette.primaryButton : Palette.raised, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
   }
}

struct VerifiedBadge: View {
   var size: CGFloat = 13

   var body: some View {
      Image(systemName: "checkmark.seal.fill")
         .font(.system(size: size))
         .foregroundStyle(Palette.link)
         .accessibilityLabel("Verified")
   }
}
