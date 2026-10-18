import SwiftUI

// Guided cookie import (ADR-0008). On the real engine the typed cookies go to the engine, which
// builds and saves the Session, then reads the account's own profile back. The person confirms
// that account before it is installed. Nothing here stores, prints or logs a cookie, and the
// fields are cleared as soon as they are sent. The dummy engine accepts any session and the
// fields are discarded. Opened as a sheet to add an account, a session the engine refuses is
// reported here and the account in use stays. A checkpoint or a revoked session routes to its
// own state view, and nothing is retried.
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
      ScrollView {
         VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 14) {
               InstagramGlyph()
                  .frame(width: 44, height: 44)

               Text("Instagram+")
                  .font(.system(size: 26, weight: .bold))
            }

            if let pending = accounts.pending {
               VerifiedAccountCard(pending: pending) {
                  Task { await accounts.confirmPending() }
               } onRefuse: {
                  Task { await accounts.cancelPending() }
               }
               .padding(.top, 28)
            } else {
               entry
            }

            if isAddingAccount {
               Button("Cancel") {
                  Task { await accounts.cancelPending() }
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

   @ViewBuilder
   private var entry: some View {
      let report = SessionCookieInput(sessionID: sessionID, userID: userID, csrfToken: csrfToken).check()
      let canContinue = report.cleaned != nil && !isConnecting

      Text("Connect your Instagram session")
         .font(.system(size: 20, weight: .semibold))
         .padding(.top, 28)

      Text("Instagram+ does not ask for your password. It uses the session from a browser where you are already signed in to instagram.com. This takes about a minute.")
         .font(.system(size: 14))
         .foregroundStyle(Palette.textSecondary)
         .fixedSize(horizontal: false, vertical: true)
         .padding(.top, 8)

      VStack(alignment: .leading, spacing: 12) {
         SetupStep(number: 1, text: "In a browser, open instagram.com and sign in to the account you want to use.")
         SetupStep(number: 2, text: "Open the developer tools with ⌥⌘I. In Safari, first turn on Settings, Advanced, Show features for web developers.")
         SetupStep(number: 3, text: "Chrome, Brave, Helium and Edge: open the Application tab, then Storage, Cookies, https://www.instagram.com. Safari and Firefox: open the Storage tab, then Cookies, www.instagram.com.")
         SetupStep(number: 4, text: "Find sessionid, ds_user_id and csrftoken in the list. Double-click the Value cell of each, copy it, and paste it below. Copy the value only, not the name.")
      }
      .padding(.top, 22)

      Text("sessionid is marked HttpOnly, so the browser hides it from scripts. It cannot be read for you and has to be copied by hand.")
         .font(.system(size: 12))
         .foregroundStyle(Palette.textSecondary)
         .fixedSize(horizontal: false, vertical: true)
         .padding(.top, 12)

      VStack(alignment: .leading, spacing: 10) {
         SetupField(problem: report.problems[.sessionID]) {
            SecureField("sessionid", text: $sessionID)
         }

         SetupField(problem: report.problems[.userID]) {
            TextField("ds_user_id", text: $userID)
         }

         SetupField(problem: report.problems[.csrfToken]) {
            SecureField("csrftoken", text: $csrfToken)
         }
      }
      .padding(.top, 18)

      HStack(alignment: .top, spacing: 10) {
         Image(systemName: "exclamationmark.shield")
            .foregroundStyle(Palette.badge)

         Text("The sessionid cookie is a key to your account: whoever holds it is signed in as you, with no password and no second factor. Instagram+ keeps it in one file only you can read, on this Mac. Never paste it anywhere else or share it with anyone. Signing out of Instagram in that browser ends the session.")
            .font(.system(size: 12))
            .foregroundStyle(Palette.textSecondary)
            .fixedSize(horizontal: false, vertical: true)
      }
      .padding(14)
      .background(Palette.raised, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
      .padding(.top, 18)

      Button(action: connect) {
         Text(isConnecting ? "Checking the account" : "Continue")
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
   }

   private func connect() {
      let report = SessionCookieInput(sessionID: sessionID, userID: userID, csrfToken: csrfToken).check()

      sessionID = ""
      userID = ""
      csrfToken = ""
      addProblem = nil

      guard accounts.isRealEngine else {
         if !isAddingAccount {
            navigation.route = .home
         }

         Task { await gateway.connect() }
         return
      }

      guard let cleaned = report.cleaned else {
         return
      }

      isConnecting = true

      Task {
         let outcome = await accounts.verifyBrowserSession(cleaned)
         isConnecting = false

         if case .rejected(let problem) = outcome {
            addProblem = problem
         }
      }
   }
}

// The account the engine read back for the pasted session. Only an id, a name, an avatar and two
// counts are shown, never a cookie.
private struct VerifiedAccountCard: View {
   let pending: PendingAccount
   let onConfirm: () -> Void
   let onRefuse: () -> Void

   var body: some View {
      VStack(spacing: 14) {
         Text("Is this your account?")
            .font(.system(size: 20, weight: .semibold))

         Avatar(account: pending.account, diameter: 88)

         VStack(spacing: 2) {
            Text(pending.account.username)
               .font(.system(size: 17, weight: .semibold))

            if pending.account.displayName != pending.account.username {
               Text(pending.account.displayName)
                  .font(.system(size: 13))
                  .foregroundStyle(Palette.textSecondary)
            }

            Text("\(pending.followerCount.formatted()) followers · \(pending.followingCount.formatted()) following")
               .font(.system(size: 12))
               .foregroundStyle(Palette.textSecondary)
               .padding(.top, 4)
         }

         Button(action: onConfirm) {
            Text("Yes, use this account")
               .font(.system(size: 14, weight: .semibold))
               .foregroundStyle(.white)
               .frame(maxWidth: .infinity)
               .frame(height: 42)
               .background(Palette.createGradient, in: Capsule())
         }
         .buttonStyle(.plain)

         Button("No, remove it and start over", action: onRefuse)
            .buttonStyle(.plain)
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(Palette.link)
      }
      .frame(maxWidth: .infinity)
      .padding(.top, 6)
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

private struct SetupField<Field: View>: View {
   let problem: String?
   @ViewBuilder let field: Field

   var body: some View {
      VStack(alignment: .leading, spacing: 4) {
         field
            .modifier(SetupFieldChrome(hasProblem: problem != nil))

         if let problem {
            Text(problem)
               .font(.system(size: 11))
               .foregroundStyle(Palette.badge)
               .fixedSize(horizontal: false, vertical: true)
         }
      }
   }
}

private struct SetupFieldChrome: ViewModifier {
   var hasProblem = false

   func body(content: Content) -> some View {
      content
         .textFieldStyle(.plain)
         .font(.system(size: 14, design: .monospaced))
         .padding(.horizontal, 14)
         .frame(height: 40)
         .background(Palette.field, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
         .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).strokeBorder(hasProblem ? Palette.badge : Palette.hairline))
   }
}
