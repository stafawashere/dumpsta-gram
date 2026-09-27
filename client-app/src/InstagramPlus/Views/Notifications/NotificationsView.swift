import SwiftUI

struct NotificationsView: View {
   @Environment(ActivityStore.self) private var activity
   @Environment(ProfileStore.self) private var profiles

   @State private var filter = ActivityFilter.all
   @State private var isShowingRequests = false

   private struct Section: Identifiable {
      let title: String
      let items: [ActivityItem]

      var id: String { title }
   }

   var body: some View {
      ScrollView {
         VStack(alignment: .leading, spacing: 0) {
            HStack {
               SectionTitle(text: "Notifications", size: 24)

               Spacer()

               SegmentedPills(options: ActivityFilter.allCases, selection: $filter) { $0.title }
            }

            if !activity.followRequests.isEmpty {
               followRequests
                  .padding(.top, 24)
            }

            if !activity.state.hasLoaded {
               LoadStateContainer(state: activity.state, loadingLabel: "Loading activity", retry: { Task { await activity.load() } }) {
                  EmptyView()
               }
            }

            ForEach(sections) { section in
               VStack(alignment: .leading, spacing: 6) {
                  Text(section.title)
                     .font(.system(size: 16, weight: .semibold))
                     .foregroundStyle(Palette.textPrimary)
                     .padding(.bottom, 8)

                  ForEach(section.items) { item in
                     ActivityRow(item: item, isFollowing: followState(for: item)) {
                        if let actor = item.actors.first {
                           Task { await profiles.toggleFollow(actor.id) }
                        }
                     }
                  }
               }
               .padding(.top, 30)
            }

            if sections.isEmpty, activity.state.hasLoaded {
               EmptyStateView(symbolName: "heart", title: "Nothing here yet", message: "Activity on your posts will show up here.")
                  .frame(height: 360)
            }
         }
         .frame(maxWidth: 680)
         .padding(.horizontal, 40)
         .padding(.vertical, 36)
         .frame(maxWidth: .infinity)
      }
      .onAppear { activity.markSeen() }
      .task {
         if !activity.state.hasLoaded {
            await activity.load()
         }
      }
   }

   private var sections: [Section] {
      let now = Date.now
      let visibleItems = activity.items.filter { filter.includes($0.kind) }
      let buckets: [(String, TimeInterval)] = [
         ("Today", 60 * 60 * 24),
         ("This week", 60 * 60 * 24 * 7),
         ("This month", 60 * 60 * 24 * 30),
         ("Earlier", .infinity),
      ]

      var remaining = visibleItems
      var sections: [Section] = []

      for (title, maximumAge) in buckets {
         let matching = remaining.filter { now.timeIntervalSince($0.occurredAt) < maximumAge }
         remaining.removeAll { now.timeIntervalSince($0.occurredAt) < maximumAge }

         if !matching.isEmpty {
            sections.append(Section(title: title, items: matching))
         }
      }

      return sections
   }

   private func followState(for item: ActivityItem) -> Bool? {
      guard case .followed = item.kind, let actor = item.actors.first else {
         return nil
      }

      return profiles.isFollowing(actor.id)
   }

   private var followRequests: some View {
      VStack(alignment: .leading, spacing: 12) {
         Button {
            withAnimation(.easeOut(duration: 0.2)) {
               isShowingRequests.toggle()
            }
         } label: {
            HStack(spacing: 12) {
               ZStack {
                  ForEach(Array(activity.followRequests.prefix(2).enumerated()), id: \.element.id) { position, account in
                     Avatar(account: account, diameter: 34)
                        .overlay(Circle().strokeBorder(Palette.canvas, lineWidth: 2))
                        .offset(x: CGFloat(position) * 16, y: CGFloat(position) * 12)
                  }
               }
               .frame(width: 50, height: 46, alignment: .topLeading)

               VStack(alignment: .leading, spacing: 2) {
                  Text("Follow requests")
                     .font(.system(size: 14, weight: .semibold))

                  Text(activity.followRequests.map(\.username).joined(separator: " and "))
                     .font(.system(size: 13))
                     .foregroundStyle(Palette.textSecondary)
               }
               .foregroundStyle(Palette.textPrimary)

               Spacer()

               Image(systemName: isShowingRequests ? "chevron.up" : "chevron.down")
                  .foregroundStyle(Palette.textSecondary)
            }
            .contentShape(Rectangle())
         }
         .buttonStyle(.plain)

         if isShowingRequests {
            ForEach(activity.followRequests) { account in
               HStack(spacing: 12) {
                  AvatarLink(account: account, diameter: 40)

                  VStack(alignment: .leading, spacing: 2) {
                     AccountLink(account: account, size: 14, usesUsername: true)

                     Text(account.displayName)
                        .font(.system(size: 12))
                        .foregroundStyle(Palette.textSecondary)
                  }

                  Spacer()

                  let isPending = activity.pendingRequestIDs.contains(account.id)

                  PrimaryButton(title: "Confirm") {
                     Task { await activity.resolveRequest(from: account.id, approve: true) }
                  }
                  .disabled(isPending)

                  PrimaryButton(title: "Delete", isProminent: false) {
                     Task { await activity.resolveRequest(from: account.id, approve: false) }
                  }
                  .disabled(isPending)
               }
               .padding(.leading, 8)
            }
         }
      }
      .padding(16)
      .background(Palette.card, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
      .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Palette.hairline))
   }
}

private struct ActivityRow: View {
   @Environment(NavigationStore.self) private var navigation

   let item: ActivityItem
   let isFollowing: Bool?
   let toggleFollow: () -> Void

   var body: some View {
      HStack(spacing: 12) {
         if let actor = item.actors.first {
            AvatarLink(account: actor, diameter: 44)
         }

         description
            .font(.system(size: 14))
            .foregroundStyle(Palette.textPrimary)
            .fixedSize(horizontal: false, vertical: true)

         Spacer(minLength: 12)

         if let isFollowing {
            PrimaryButton(title: isFollowing ? "Following" : "Follow back", isProminent: !isFollowing, action: toggleFollow)
         } else if let mediaCode = item.mediaCode {
            Button {
               navigation.showPost(code: mediaCode)
            } label: {
               MediaView(seed: mediaCode, cornerRadius: 6)
                  .frame(width: 44, height: 44)
            }
            .buttonStyle(.plain)
         }
      }
      .padding(.vertical, 8)
   }

   private var description: Text {
      let names = actorNames
      let time = Text(" " + RelativeTime.short(since: item.occurredAt)).foregroundStyle(Palette.textSecondary)

      switch item.kind {
         case .likedPost:
            return Text("\(names) liked your photo.\(time)")
         case .likedComment(let comment):
            return Text("\(names) liked your comment: \(comment)\(time)")
         case .commented(let comment):
            return Text("\(names) commented: \(comment)\(time)")
         case .mentioned(let comment):
            return Text("\(names) mentioned you in a comment: \(comment)\(time)")
         case .followed:
            return Text("\(names) started following you.\(time)")
      }
   }

   private var actorNames: Text {
      let usernames = item.actors.map(\.username)
      let first = Text(usernames.first ?? "").fontWeight(.semibold)
      let othersCount = usernames.count - 1

      if othersCount == 1 {
         return Text("\(first) and \(Text(usernames[1]).fontWeight(.semibold))")
      }

      if othersCount > 1 {
         return Text("\(first) and \(othersCount) others")
      }

      return first
   }
}
