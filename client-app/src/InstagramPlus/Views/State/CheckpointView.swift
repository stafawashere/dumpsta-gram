import SwiftUI

// A checkpoint is a state a person resolves in their browser, never an error to retry.
struct CheckpointView: View {
   @Environment(EngineGateway.self) private var gateway

   let checkpoint: Checkpoint

   @State private var isResuming = false

   var body: some View {
      StateCard(symbolName: "checkmark.shield", tint: Color(hex: 0xE3A008), title: "Instagram wants to confirm it's you") {
         Text("Instagram+ has stopped sending anything to Instagram. Nothing will be retried.")

         VStack(alignment: .leading, spacing: 10) {
            StepRow(number: 1, text: "Open instagram.com in the browser this session came from.")
            StepRow(number: 2, text: "Complete the check Instagram shows there.")
            StepRow(number: 3, text: "Come back here and continue.")
         }
         .padding(.top, 6)

         if let action = checkpoint.requiredAction {
            Text("Instagram asked for: \(action)")
               .font(.system(size: 12, design: .monospaced))
               .foregroundStyle(Palette.textSecondary)
         }
      } actions: {
         Button {
            isResuming = true

            Task {
               await gateway.resumeAfterCheckpoint()
               isResuming = false
            }
         } label: {
            Text(isResuming ? "Resuming" : "I've confirmed it in my browser")
         }
         .buttonStyle(GradientButtonStyle())
         .disabled(isResuming)

         Button("Log out instead") {
            Task { await gateway.signOut() }
         }
         .buttonStyle(.plain)
         .font(.system(size: 13, weight: .semibold))
         .foregroundStyle(Palette.link)
      }
   }
}

struct SessionRevokedView: View {
   @Environment(EngineGateway.self) private var gateway

   var body: some View {
      StateCard(symbolName: "person.crop.circle.badge.xmark", tint: Palette.badge, title: "This session has ended") {
         Text("Instagram signed this session out. Instagram+ cannot renew a session it did not create, so it needs a fresh one from your browser.")
      } actions: {
         Button("Connect a new session") {
            gateway.acknowledgeRevoked()
         }
         .buttonStyle(GradientButtonStyle())
      }
   }
}

struct StateCard<Message: View, Actions: View>: View {
   let symbolName: String
   let tint: Color
   let title: String
   @ViewBuilder let message: Message
   @ViewBuilder let actions: Actions

   var body: some View {
      VStack(alignment: .leading, spacing: 16) {
         HStack(spacing: 12) {
            InstagramGlyph()
               .frame(width: 36, height: 36)

            Text("Instagram+")
               .font(.system(size: 22, weight: .bold))
         }

         Image(systemName: symbolName)
            .font(.system(size: 34, weight: .light))
            .foregroundStyle(tint)
            .padding(.top, 12)

         Text(title)
            .font(.system(size: 20, weight: .semibold))

         VStack(alignment: .leading, spacing: 10) {
            message
         }
         .font(.system(size: 14))
         .foregroundStyle(Palette.textSecondary)
         .fixedSize(horizontal: false, vertical: true)

         VStack(spacing: 12) {
            actions
         }
         .frame(maxWidth: .infinity)
         .padding(.top, 10)
      }
      .foregroundStyle(Palette.textPrimary)
      .padding(36)
      .frame(width: 460)
      .background(Palette.card, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
      .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).strokeBorder(Palette.hairline))
      .frame(maxWidth: .infinity, maxHeight: .infinity)
      .background(Palette.canvas)
   }
}

struct StepRow: View {
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
            .foregroundStyle(Palette.textPrimary)
            .fixedSize(horizontal: false, vertical: true)
      }
   }
}

struct GradientButtonStyle: ButtonStyle {
   @Environment(\.isEnabled) private var isEnabled

   func makeBody(configuration: Configuration) -> some View {
      configuration.label
         .font(.system(size: 14, weight: .semibold))
         .foregroundStyle(.white)
         .frame(maxWidth: .infinity)
         .frame(height: 42)
         .background(Palette.createGradient, in: Capsule())
         .opacity(isEnabled ? (configuration.isPressed ? 0.85 : 1) : 0.55)
         .contentShape(Capsule())
   }
}
