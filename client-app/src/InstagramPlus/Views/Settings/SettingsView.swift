import SwiftUI

struct SettingsView: View {
   @Environment(ProfileStore.self) private var profiles
   @Environment(NavigationStore.self) private var navigation

   @AppStorage(Appearance.storageKey) private var appearance = Appearance.system
   @AppStorage("showsMessagePreviews") private var showsMessagePreviews = true
   @AppStorage("playsSounds") private var playsSounds = true
   @AppStorage("autoplaysReels") private var autoplaysReels = true

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

               SettingsRow(title: "Session", value: "Adopted, served by the dummy engine")
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

            DummyEngineSection()

            SettingsCard(title: "About") {
               SettingsRow(title: "Version", value: Self.versionString)
               SettingsRow(title: "Engine", value: "Dummy engine, mirroring Dumpsta-Engine 1.1.0")

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
