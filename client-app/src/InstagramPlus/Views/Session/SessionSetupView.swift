import SwiftUI

// On the real engine the typed cookies go to the engine, which builds and saves the Session.
// Nothing here stores, prints or logs them, and the fields are cleared as soon as they are sent.
// The dummy engine accepts any session and the fields are discarded. Opened as a sheet to add
// an account, a session the engine refuses is reported here and the account in use stays.
struct SessionSetupView: View {
   @Environment(NavigationStore.self) private var navigation
   @Environment(EngineGateway.self) private var gateway
   @Environment(AccountsStore.self) private var accounts

   @State private var sessionID = ""
   @State private var userID = ""
   @State private var csrfToken = ""
   @State private var isConnecting = false
   @State private var addProblem: String?

   var isAddingAccount = false

   var body: some View {
      let hasSessionID = !sessionID.isEmpty
      let hasUserID = !userID.isEmpty
      let hasCSRFToken = !csrfToken.isEmpty
      let canContinue = hasSessionID && hasUserID && hasCSRFToken && !isConnecting

      ScrollView {
         VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 14) {
               InstagramGlyph()
                  .frame(width: 44, height: 44)

               Text("Instagram+")
                  .font(.system(size: 26, weight: .bold))
            }

            Text("Connect your Instagram session")
               .font(.system(size: 20, weight: .semibold))
               .padding(.top, 28)

            Text("Instagram+ does not ask for your password. It uses the session from a browser where you are already signed in to instagram.com.")
               .font(.system(size: 14))
               .foregroundStyle(Palette.textSecondary)
               .fixedSize(horizontal: false, vertical: true)
               .padding(.top, 8)

            VStack(alignment: .leading, spacing: 10) {
               SetupStep(number: 1, text: "Open instagram.com in your browser and sign in.")
               SetupStep(number: 2, text: "Open the developer tools, then Application, Cookies, instagram.com.")
               SetupStep(number: 3, text: "Copy sessionid, ds_user_id and csrftoken into the fields below.")
            }
            .padding(.top, 22)

            VStack(spacing: 10) {
               SecureField("sessionid", text: $sessionID)
                  .modifier(SetupFieldChrome())

               TextField("ds_user_id", text: $userID)
                  .modifier(SetupFieldChrome())

               SecureField("csrftoken", text: $csrfToken)
                  .modifier(SetupFieldChrome())
            }
            .padding(.top, 22)

            HStack(alignment: .top, spacing: 10) {
               Image(systemName: "exclamationmark.shield")
                  .foregroundStyle(Palette.badge)

               Text("A session cookie gives full access to your account with no second factor. Never paste it anywhere else or share it with anyone.")
                  .font(.system(size: 12))
                  .foregroundStyle(Palette.textSecondary)
                  .fixedSize(horizontal: false, vertical: true)
            }
            .padding(14)
            .background(Palette.raised, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            .padding(.top, 18)

            Button(action: connect) {
               Text(isConnecting ? "Connecting" : "Continue")
                  .font(.system(size: 14, weight: .semibold))
                  .foregroundStyle(.white)
                  .frame(maxWidth: .infinity)
                  .frame(height: 42)
                  .background(Palette.createGradient, in: Capsule())
                  .opacity(canContinue ? 1 : 0.55)
            }
            .buttonStyle(.plain)
            .disabled(!canContinue)
            .padding(.top, 22)

            if let addProblem {
               Text(addProblem)
                  .font(.system(size: 12))
                  .foregroundStyle(Palette.badge)
                  .fixedSize(horizontal: false, vertical: true)
                  .padding(.top, 12)
            }

            if isAddingAccount {
               Button("Cancel") {
                  accounts.isAddingAccount = false
               }
               .buttonStyle(.plain)
               .font(.system(size: 13, weight: .semibold))
               .foregroundStyle(Palette.link)
               .frame(maxWidth: .infinity)
               .padding(.top, 14)
            }

            if !accounts.isRealEngine {
               Button("Continue with the dummy engine") {
                  connect()
               }
               .buttonStyle(.plain)
               .font(.system(size: 13, weight: .semibold))
               .foregroundStyle(Palette.link)
               .frame(maxWidth: .infinity)
               .padding(.top, 14)
            }
         }
         .foregroundStyle(Palette.textPrimary)
         .padding(36)
         .frame(width: 460)
         .background(Palette.card, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
         .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).strokeBorder(Palette.hairline))
         .padding(.vertical, 60)
         .frame(maxWidth: .infinity)
      }
      .background(Palette.canvas)
   }

   private func connect() {
      let typedSessionID = sessionID
      let typedUserID = userID
      let typedCSRFToken = csrfToken

      sessionID = ""
      userID = ""
      csrfToken = ""
      addProblem = nil

      if !isAddingAccount {
         navigation.route = .home
      }

      guard accounts.isRealEngine else {
         Task { await gateway.connect() }
         return
      }

      isConnecting = true

      Task {
         addProblem = await accounts.adoptBrowserSession(sessionID: typedSessionID, userID: typedUserID, csrfToken: typedCSRFToken)
         isConnecting = false
      }
   }
}

private struct SetupStep: View {
   let number: Int
   let text: String

   var body: some View {
      HStack(alignment: .firstTextBaseline, spacing: 10) {
         Text(String(number))
            .font(.system(size: 11, weight: .bold))
            .foregroundStyle(.white)
            .frame(width: 20, height: 20)
            .background(Palette.accent, in: Circle())

         Text(text)
            .font(.system(size: 13))
            .fixedSize(horizontal: false, vertical: true)
      }
   }
}

private struct SetupFieldChrome: ViewModifier {
   func body(content: Content) -> some View {
      content
         .textFieldStyle(.plain)
         .font(.system(size: 14, design: .monospaced))
         .padding(.horizontal, 14)
         .frame(height: 40)
         .background(Palette.field, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
         .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).strokeBorder(Palette.hairline))
   }
}
