import SwiftUI

// Controls for the dummy engine: its timing preset, the failures it can be told to produce,
// and a live log of every request it paced. None of this exists once the bridge lands.
struct DummyEngineSection: View {
   @Environment(EngineGateway.self) private var gateway
   @AppStorage("dummyTiming") private var storedTiming = DummyEngine.Timing.fast.rawValue

   @State private var status: DummyEngine.Status?
   @State private var faults = DummyEngine.Faults()

   var body: some View {
      VStack(alignment: .leading, spacing: 16) {
         HStack {
            Text("Dummy engine")
               .font(.system(size: 13, weight: .semibold))
               .foregroundStyle(Palette.textSecondary)

            Spacer()

            Text("Stands in for Dumpsta-Engine until the bridge lands")
               .font(.system(size: 11))
               .foregroundStyle(Palette.textTertiary)
         }

         timing
         Hairline()
         faultControls
         Hairline()
         meters
         Hairline()
         requestLog
      }
      .padding(20)
      .frame(maxWidth: .infinity, alignment: .leading)
      .background(Palette.card, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
      .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Palette.hairline))
      .task {
         faults = await gateway.engine.status().faults

         while !Task.isCancelled {
            status = await gateway.engine.status()
            try? await Task.sleep(for: .seconds(1))
         }
      }
      .onChange(of: faults) { _, newFaults in
         Task { await gateway.engine.configure(faults: newFaults) }
      }
   }

   private var timing: some View {
      let selection = Binding<DummyEngine.Timing>(
         get: { DummyEngine.Timing(rawValue: storedTiming) ?? .fast },
         set: { newTiming in
            storedTiming = newTiming.rawValue
            Task { await gateway.engine.configure(timing: newTiming) }
         }
      )

      return VStack(alignment: .leading, spacing: 8) {
         Picker("Timing", selection: selection) {
            ForEach(DummyEngine.Timing.allCases) { timing in
               Text(timing.title).tag(timing)
            }
         }
         .pickerStyle(.segmented)
         .frame(maxWidth: 320)

         Text(selection.wrappedValue.detail)
            .font(.system(size: 12))
            .foregroundStyle(Palette.textSecondary)
      }
   }

   private var faultControls: some View {
      VStack(alignment: .leading, spacing: 10) {
         Text("Next failures")
            .font(.system(size: 13, weight: .semibold))

         Toggle("Checkpoint on the next request", isOn: $faults.checkpointOnNextRequest)
         Toggle("Revoke the session", isOn: $faults.sessionRevoked)
         Toggle("Outcome unknown on the next write", isOn: $faults.outcomeUnknownOnNextWrite)
         Toggle("Unrecognised rejection on the next write (stops writes)", isOn: $faults.unrecognisedRejectionOnNextWrite)
         Toggle("Schema change on the next feed read", isOn: $faults.schemaChangeOnNextFeed)
         Toggle("Others reply to messages you send", isOn: $faults.repliesFromOthers)

         HStack {
            Text("Transport failure rate")

            Slider(value: $faults.transportFailureRate, in: 0...0.5, step: 0.05)
               .frame(width: 180)

            Text("\(Int(faults.transportFailureRate * 100))%")
               .monospacedDigit()
               .foregroundStyle(Palette.textSecondary)
         }
      }
      .toggleStyle(.switch)
      .font(.system(size: 13))
   }

   private var meters: some View {
      let used = status?.writesUsedThisHour ?? 0
      let budget = status?.writeBudget ?? DummyEngine.writeBudgetPerHour
      let writesStopped = status?.writesStopped ?? false

      return VStack(alignment: .leading, spacing: 10) {
         HStack {
            Text("Writes this hour")
            Spacer()
            Text("\(used) of \(budget)")
               .monospacedDigit()
               .foregroundStyle(Palette.textSecondary)
         }

         ProgressView(value: Double(used), total: Double(budget))
            .tint(used >= budget ? Palette.badge : Palette.accent)

         HStack {
            Text("Listener")
            Spacer()
            Text(status?.isListening == true ? "Polling, \(status?.bufferedEvents ?? 0) buffered" : "Stopped")
               .foregroundStyle(Palette.textSecondary)
         }

         if writesStopped {
            HStack {
               Text("Writes are stopped after an unrecognised rejection.")
                  .foregroundStyle(Palette.badge)

               Spacer()

               PrimaryButton(title: "Resume writes", isProminent: false) {
                  Task { await gateway.engine.reconnect() }
               }
            }
         }
      }
      .font(.system(size: 13))
   }

   private var requestLog: some View {
      VStack(alignment: .leading, spacing: 8) {
         Text("Requests")
            .font(.system(size: 13, weight: .semibold))

         if let requests = status?.requests, !requests.isEmpty {
            VStack(spacing: 0) {
               ForEach(requests) { request in
                  RequestRow(request: request)
               }
            }
            .background(Palette.raised, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
         } else {
            Text("Nothing sent yet.")
               .font(.system(size: 12))
               .foregroundStyle(Palette.textSecondary)
         }
      }
   }
}

private struct RequestRow: View {
   let request: DummyEngine.RequestRecord

   var body: some View {
      let waited = request.departedAt.map { $0.timeIntervalSince(request.queuedAt) }
      let kindColor: Color = switch request.kind {
         case .read: Palette.link
         case .write: Palette.accent
         case .poll: Palette.online
      }

      HStack(spacing: 10) {
         Text(request.kind.rawValue.uppercased())
            .font(.system(size: 9, weight: .bold))
            .foregroundStyle(kindColor)
            .frame(width: 44, alignment: .leading)

         Text(request.name)
            .font(.system(size: 12, design: .monospaced))
            .lineLimit(1)

         Spacer()

         if let waited {
            Text(String(format: "waited %.1fs", waited))
               .font(.system(size: 11))
               .foregroundStyle(Palette.textTertiary)
               .monospacedDigit()
         }

         Text(request.outcome)
            .font(.system(size: 11, weight: .medium))
            .foregroundStyle(request.outcome == "ok" ? Palette.textSecondary : Palette.badge)
            .frame(width: 190, alignment: .trailing)
            .lineLimit(1)
      }
      .padding(.horizontal, 12)
      .padding(.vertical, 6)
   }
}
