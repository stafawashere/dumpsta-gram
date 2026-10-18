import SwiftUI

struct LoadingStateView: View {
   var label = "Loading"

   var body: some View {
      VStack(spacing: 12) {
         ProgressView()
            .controlSize(.small)

         Text(label)
            .font(.system(size: 13))
            .foregroundStyle(Palette.textSecondary)
      }
      .frame(maxWidth: .infinity)
      .padding(.vertical, 60)
   }
}

struct ErrorStateView: View {
   let message: String
   let retry: () -> Void

   var body: some View {
      VStack(spacing: 12) {
         Image(systemName: "exclamationmark.triangle")
            .font(.system(size: 26, weight: .light))
            .foregroundStyle(Palette.textSecondary)

         Text(message)
            .font(.system(size: 14))
            .foregroundStyle(Palette.textPrimary)
            .multilineTextAlignment(.center)

         PrimaryButton(title: "Try again", isProminent: false, action: retry)
      }
      .frame(maxWidth: .infinity)
      .padding(.vertical, 60)
   }
}

struct LoadStateContainer<Content: View>: View {
   let state: LoadState
   var loadingLabel = "Loading"
   var notFoundTitle = "Not available"
   let retry: () -> Void
   @ViewBuilder let content: () -> Content

   var body: some View {
      switch state {
         case .idle, .loading:
            LoadingStateView(label: loadingLabel)

         case .notFound:
            EmptyStateView(symbolName: "questionmark.circle", title: notFoundTitle, message: "It may have been removed, or it is private.")
               .frame(height: 320)

         case .failed(let message):
            ErrorStateView(message: message, retry: retry)

         case .loaded:
            content()
      }
   }
}

struct NoticeStack: View {
   @Environment(EngineGateway.self) private var gateway

   var body: some View {
      VStack(alignment: .trailing, spacing: 10) {
         ForEach(gateway.notices) { notice in
            NoticeCard(notice: notice) {
               gateway.dismiss(notice.id)
            }
            .transition(.move(edge: .trailing).combined(with: .opacity))
         }
      }
      .animation(.snappy(duration: 0.25), value: gateway.notices)
      .padding(24)
      .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomTrailing)
      .allowsHitTesting(!gateway.notices.isEmpty)
   }
}

private struct NoticeCard: View {
   let notice: Notice
   let dismiss: () -> Void

   var body: some View {
      let tint: Color = switch notice.tone {
         case .info: Palette.link
         case .warning: Color(hex: 0xE3A008)
         case .error: Palette.badge
      }

      HStack(alignment: .top, spacing: 12) {
         Circle()
            .fill(tint)
            .frame(width: 8, height: 8)
            .padding(.top, 5)

         VStack(alignment: .leading, spacing: 3) {
            Text(notice.title)
               .font(.system(size: 13, weight: .semibold))
               .foregroundStyle(Palette.textPrimary)

            Text(notice.message)
               .font(.system(size: 12))
               .foregroundStyle(Palette.textSecondary)
               .fixedSize(horizontal: false, vertical: true)
         }

         Button(action: dismiss) {
            Image(systemName: "xmark")
               .font(.system(size: 10, weight: .bold))
               .foregroundStyle(Palette.textTertiary)
         }
         .buttonStyle(.plain)
         .accessibilityLabel("Dismiss")
      }
      .padding(14)
      .frame(width: 340, alignment: .leading)
      .background(Palette.card, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
      .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Palette.hairline))
      .shadow(color: .black.opacity(0.12), radius: 16, y: 6)
   }
}

struct PendingWritesPill: View {
   @Environment(EngineGateway.self) private var gateway

   var body: some View {
      let count = gateway.pendingWrites

      if count > 0 {
         HStack(spacing: 8) {
            ProgressView()
               .controlSize(.mini)

            Text(count == 1 ? "1 action queued" : "\(count) actions queued")
               .font(.system(size: 12, weight: .medium))
               .foregroundStyle(Palette.textSecondary)
         }
         .padding(.horizontal, 12)
         .frame(height: 30)
         .background(Palette.raised, in: Capsule())
         .help("Writes wait their turn in the engine's pacer. On parity timing that is about 30 seconds apart.")
      }
   }
}
