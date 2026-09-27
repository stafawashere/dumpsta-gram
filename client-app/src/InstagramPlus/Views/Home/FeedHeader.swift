import SwiftUI

struct FeedHeader: View {
   @Environment(HomeStore.self) private var home

   var body: some View {
      @Bindable var home = home

      HStack {
         SectionTitle(text: "Feeds")

         Spacer()

         SegmentedPills(options: FeedOrdering.allCases, selection: $home.feedOrdering) { $0.title }
      }
   }
}
