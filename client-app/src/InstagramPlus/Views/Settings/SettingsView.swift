import SwiftUI

struct SettingsView: View {
   @Environment(ProfileStore.self) private var profiles
   @Environment(NavigationStore.self) private var navigation
   @Environment(AccountsStore.self) private var accounts

   @AppStorage(Appearance.storageKey) private var appearance = Appearance.system
   @AppStorage("showsMessagePreviews") private var showsMessagePreviews = true
   @AppStorage("playsSounds") private var playsSounds = true
   @AppStorage("autoplaysReels") private var autoplaysReels = true

   @State private var sessionAge = SessionAge.describe(refreshedAt: nil)

   var body: some View {
      ScrollView {
         VStack(alignment: .leading, spacing: 24) {
            SectionTitle(text: "Settings", size: 24)

            SettingsCard(title: "Account") {
               HStack(spacing: 14) {
                  Avatar(account: profiles.viewerAccount, diameter: 52, style: .soft)

                  VStack(alignment: .leading, spacing: 2) {
                     Text(profiles.viewerAccount.displayName)
                        .font(.system(size: 15, weight: .semibold))

                     Text(profiles.viewerAccount.username)
                        .font(.system(size: 13))
                        .foregroundStyle(Palette.textSecondary)
                  }

                  Spacer()

                  PrimaryButton(title: "View profile", isProminent: false) {
                     navigation.openProfile(profiles.viewerAccount.id)
                  }
               }

               SettingsRow(title: "Session", value: sessionAge)

               if accounts.isRealEngine {
                  SettingsRow(title: "Account id", value: profiles.viewerID)
               }
            }
            .task(id: accounts.activeID) {
               sessionAge = SessionAge.describe(refreshedAt: await accounts.active.gateway.engine.sessionRefreshedAt())
            }

            SettingsCard(title: "Accounts") {
               ForEach(accounts.sessions) { session in
                  let isActive = session.id == accounts.activeID
                  let account = session.profiles.viewerAccount

                  HStack(spacing: 12) {
                     Avatar(account: account, diameter: 36, style: .soft)

                     Text(account.username)
                        .font(.system(size: 14, weight: .medium))

                     Spacer()

                     if isActive {
                        Text("Current")
                           .foregroundStyle(Palette.textSecondary)
                     } else {
                        PrimaryButton(title: "Switch", isProminent: false) {
                           Task { await accounts.switchTo(session.id) }
                        }

                        PrimaryButton(title: "Remove", isProminent: false) {
                           Task { await accounts.remove(session.id) }
                        }
                     }
                  }
               }

               if accounts.canAddAccount {
                  Button("Add account") {
                     Task { await accounts.addAccount() }
                  }
                  .buttonStyle(.plain)
                  .font(.system(size: 14, weight: .semibold))
                  .foregroundStyle(Palette.link)
               }
            }

            SettingsCard(title: "Privacy") {
               ForEach(RelationshipList.allCases) { list in
                  SettingsLink(title: list.title) {
                     navigation.route = .relationships(list)
                  }
               }

               SettingsLink(title: "Stories archive") {
                  navigation.route = .archive
               }
            }

            SettingsCard(title: "Appearance") {
               Picker("Theme", selection: $appearance) {
                  Text("System").tag(Appearance.system)
                  Text("Light").tag(Appearance.light)
                  Text("Dark").tag(Appearance.dark)
               }
               .pickerStyle(.segmented)
               .frame(maxWidth: 320)
            }

            SettingsCard(title: "Notifications") {
               Toggle("Show message previews", isOn: $showsMessagePreviews)
               Toggle("Play sounds", isOn: $playsSounds)
            }

            SettingsCard(title: "Media") {
               Toggle("Autoplay reels", isOn: $autoplaysReels)
            }

            WritesCard()

            DummyEngineSection()

            SettingsCard(title: "About") {
               SettingsRow(title: "Version", value: Self.versionString)
               SettingsRow(title: "Engine", value: accounts.isRealEngine ? "Dumpsta-Engine in embedded Python" : "Dummy engine, mirroring Dumpsta-Engine 1.1.0")

               Button("Log out") {
                  navigation.isConfirmingLogOut = true
               }
               .buttonStyle(.plain)
               .font(.system(size: 14, weight: .semibold))
               .foregroundStyle(Palette.badge)
               .padding(.top, 4)
            }
         }
         .toggleStyle(.switch)
         .font(.system(size: 14))
         .foregroundStyle(Palette.textPrimary)
         .frame(maxWidth: 720)
         .padding(.horizontal, 40)
         .padding(.vertical, 36)
         .frame(maxWidth: .infinity)
      }
   }

   private static var versionString: String {
      let info = Bundle.main.infoDictionary
      let version = info?["CFBundleShortVersionString"] as? String ?? "0"
      let build = info?["CFBundleVersion"] as? String ?? "0"
      return "\(version) (\(build))"
   }
}

// What the engine sends that other people see, and the write stop. Both switches change the
// engine's Behavior for every open account and are kept for the next launch. Resuming writes is
// only ever this button: the engine stops writes after a refusal nothing explains, and lifting
// that is a person's call after checking the account.
private struct WritesCard: View {
   @Environment(AccountsStore.self) private var accounts

   @State private var isResuming = false

   var body: some View {
      let behavior = accounts.active.gateway.behavior

      SettingsCard(title: "Writes and receipts") {
         SettingsSwitch(
            title: "Send read receipts",
            detail: "Opening an unread conversation tells the sender you read it, as instagram.com does. When off, it stays unread for them and here.",
            isOn: binding(behavior.markThreadsRead) { $0.markThreadsRead = $1 }
         )

         SettingsSwitch(
            title: "Mark stories seen",
            detail: "Opening someone's story adds you to its viewers, as instagram.com does.",
            isOn: binding(behavior.markStoriesSeen) { $0.markStoriesSeen = $1 }
         )

         Hairline()

         HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
               Text("Resume writes")

               Text("The engine stops every write after Instagram refuses one for a reason nothing explains, which can be an action block. Check the account in a browser first. The hourly write budget still applies.")
                  .font(.system(size: 12))
                  .foregroundStyle(Palette.textSecondary)
                  .fixedSize(horizontal: false, vertical: true)
            }

            Spacer()

            PrimaryButton(title: isResuming ? "Resuming" : "Resume writes", isProminent: false) {
               isResuming = true

               Task {
                  await accounts.active.resumeWrites()
                  isResuming = false
               }
            }
            .disabled(isResuming)
         }
      }
   }

   private func binding(_ value: Bool, _ change: @escaping (inout Engine.BehaviorChoice, Bool) -> Void) -> Binding<Bool> {
      Binding(
         get: { value },
         set: { newValue in
            var choice = accounts.active.gateway.behavior
            change(&choice, newValue)

            if accounts.isRealEngine {
               choice.store()
            }

            Task {
               for session in accounts.sessions {
                  await session.gateway.setBehavior(choice)
               }
            }
         }
      )
   }
}

private struct SettingsSwitch: View {
   let title: String
   let detail: String
   @Binding var isOn: Bool

   var body: some View {
      VStack(alignment: .leading, spacing: 4) {
         Toggle(title, isOn: $isOn)

         Text(detail)
            .font(.system(size: 12))
            .foregroundStyle(Palette.textSecondary)
            .fixedSize(horizontal: false, vertical: true)
      }
   }
}

private struct SettingsCard<Content: View>: View {
   let title: String
   @ViewBuilder let content: Content

   var body: some View {
      VStack(alignment: .leading, spacing: 14) {
         Text(title)
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(Palette.textSecondary)

         content
      }
      .padding(20)
      .frame(maxWidth: .infinity, alignment: .leading)
      .background(Palette.card, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
      .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Palette.hairline))
   }
}

private struct SettingsRow: View {
   let title: String
   let value: String

   var body: some View {
      HStack {
         Text(title)

         Spacer()

         Text(value)
            .foregroundStyle(Palette.textSecondary)
      }
   }
}


private struct SettingsLink: View {
   let title: String
   let action: () -> Void

   var body: some View {
      Button(action: action) {
         HStack {
            Text(title)

            Spacer()

            Image(systemName: "chevron.right")
               .font(.system(size: 11, weight: .semibold))
               .foregroundStyle(Palette.textTertiary)
         }
         .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
   }
}