import SwiftUI

struct SegmentedPills<Option: Identifiable & Hashable>: View {
   let options: [Option]
   @Binding var selection: Option
   let title: (Option) -> String

   var body: some View {
      HStack(spacing: 6) {
         ForEach(options) { option in
            let isSelected = option == selection

            Button {
               withAnimation(.snappy(duration: 0.25)) {
                  selection = option
               }
            } label: {
               Text(title(option))
                  .font(.system(size: 13, weight: isSelected ? .semibold : .medium))
                  .foregroundStyle(isSelected ? Palette.textPrimary : Palette.textSecondary)
                  .padding(.horizontal, 16)
                  .frame(height: 34)
                  .background {
                     if isSelected {
                        Capsule()
                           .fill(Palette.card)
                           .overlay(Capsule().strokeBorder(Palette.hairline))
                     }
                  }
                  .contentShape(Capsule())
            }
            .buttonStyle(.plain)
         }
      }
   }
}
