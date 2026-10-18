import SwiftUI

// The real engine is the default, and it needs the embedded Python runtime that
// scripts/build-runtime.command builds. Without it the app says so and sends nothing anywhere.
struct EngineUnavailableView: View {
   @AppStorage(EngineSelection.nextLaunchKey) private var nextLaunchEngine = EngineSelection.real.rawValue

   let problem: String

   var body: some View {
      let isDummyChosen = nextLaunchEngine == EngineSelection.dummy.rawValue

      StateCard(symbolName: "shippingbox", tint: Palette.badge, title: "The engine could not start") {
         Text("Instagram+ runs Dumpsta-Engine in an embedded Python runtime, and that runtime did not start. Nothing was sent to Instagram.")

         VStack(alignment: .leading, spacing: 10) {
            StepRow(number: 1, text: "In a terminal, run client-app/scripts/build-runtime.command from the repository.")
            StepRow(number: 2, text: "Build the app again with client-app/scripts/build-app.command.")
            StepRow(number: 3, text: "Open Instagram+ again.")
         }
         .padding(.top, 6)

         Text(problem)
            .font(.system(size: 12, design: .monospaced))
            .foregroundStyle(Palette.textSecondary)
            .textSelection(.enabled)
      } actions: {
         Button {
            nextLaunchEngine = isDummyChosen ? EngineSelection.real.rawValue : EngineSelection.dummy.rawValue
         } label: {
            Text(isDummyChosen ? "The dummy engine opens on the next launch" : "Use the dummy engine on the next launch")
         }
         .buttonStyle(.plain)
         .font(.system(size: 13, weight: .semibold))
         .foregroundStyle(Palette.link)
      }
      .frame(maxWidth: .infinity, maxHeight: .infinity)
      .background(Palette.window)
   }
}
