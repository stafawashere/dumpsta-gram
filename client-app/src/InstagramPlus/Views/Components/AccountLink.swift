import SwiftUI

struct AccountLink: View {
   @Environment(NavigationStore.self) private var navigation

   let account: Account
   var size: CGFloat = 15
   var usesUsername = false

   var body: some View {
      Button {
         navigation.openProfile(account.id)
      } label: {
         HStack(spacing: 4) {
            Text(usesUsername ? account.username : account.displayName)
               .font(.system(size: size, weight: .semibold))
               .foregroundStyle(Palette.textPrimary)

            if account.isVerified {
               VerifiedBadge(size: size - 3)
            }
         }
         .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
   }
}

struct AvatarLink: View {
   @Environment(NavigationStore.self) private var navigation
   @Environment(EngineGateway.self) private var gateway

   let account: Account
   var diameter: CGFloat = 40

   var body: some View {
      Button {
         navigation.openProfile(account.id)
      } label: {
         Avatar(account: account, diameter: diameter, style: account.id == gateway.viewerID ? .soft : .solid)
      }
      .buttonStyle(.plain)
   }
}
