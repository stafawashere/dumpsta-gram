import SwiftUI

struct OverlayCloseButton: View {
   let action: () -> Void

   var body: some View {
      Button(action: action) {
         Image(systemName: "xmark")
            .font(.system(size: 18, weight: .semibold))
            .foregroundStyle(.white)
            .frame(width: 44, height: 44)
            .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
      .keyboardShortcut(.cancelAction)
      .accessibilityLabel("Close")
   }
}
