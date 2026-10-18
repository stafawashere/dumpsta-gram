import SwiftUI

struct StoriesSection: View {
   @Environment(HomeStore.self) private var home
   @Environment(NavigationStore.self) private var navigation

   var body: some View {
      VStack(alignment: .leading, spacing: 22) {
         HStack {
            SectionTitle(text: "Stories")

            Spacer()

            Button {
               if let firstStory = home.stories.first {
                  navigation.showStory(authorID: firstStory.id)
               }
            } label: {
               HStack(spacing: 4) {
                  Text("Watch all")
                     .font(.system(size: 13, weight: .semibold))

                  Image(systemName: "arrowtriangle.right.fill")
                     .font(.system(size: 6))
               }
               .foregroundStyle(Palette.textPrimary)
            }
            .buttonStyle(.plain)
         }

         ScrollView(.horizontal) {
            HStack(alignment: .top, spacing: 22) {
               AddStoryBubble {
                  navigation.isComposingStory = true
               }

               if home.stories.isEmpty {
                  ForEach(0..<5, id: \.self) { _ in
                     StoryPlaceholder()
                  }
               }

               ForEach(home.stories) { story in
                  StoryBubble(story: story) {
                     navigation.showStory(authorID: story.id)
                  }
               }
            }
         }
         .scrollIndicators(.never)
      }
   }
}

private struct StoryBubble: View {
   let story: Story
   let action: () -> Void

   var body: some View {
      Button(action: action) {
         VStack(spacing: 10) {
            ringedAvatar

            Text(story.author.displayName)
               .font(.system(size: 13))
               .foregroundStyle(Palette.textPrimary.opacity(0.75))
               .lineLimit(1)
               .frame(width: 80)
         }
      }
      .buttonStyle(.plain)
   }

   // The engine's tray row has no unseen flag. An unknown row draws a plain ring with a question
   // badge rather than the seen or the unseen ring, and rather than a dashed one that reads as
   // the Add story bubble.
   @ViewBuilder
   private var ringedAvatar: some View {
      if let hasUnseenItems = story.hasUnseenItems {
         RingedAvatar(account: story.author, diameter: 76, showsRing: hasUnseenItems)
      } else {
         ZStack(alignment: .bottomTrailing) {
            Circle()
               .strokeBorder(Palette.textTertiary, lineWidth: 2)

            Avatar(account: story.author, diameter: 66)
               .frame(maxWidth: .infinity, maxHeight: .infinity)

            Image(systemName: "questionmark.circle.fill")
               .font(.system(size: 16))
               .foregroundStyle(Palette.textSecondary, Palette.card)
         }
         .frame(width: 76, height: 76)
         .help(unknownHelp)
      }
   }

   // TrayReel.seen_at is shown as the engine gave it. Whether an item newer than it exists is the
   // engine's inference, not a property, so the app does not decide it.
   private var unknownHelp: String {
      guard let seenAt = story.seenAt else {
         return "Instagram+ cannot read yet whether you have seen this story"
      }

      return "You last saw these stories at \(seenAt.formatted(date: .abbreviated, time: .shortened)). Instagram+ cannot read yet whether there is a newer one"
   }
}

private struct AddStoryBubble: View {
   let action: () -> Void

   var body: some View {
      Button(action: action) {
         VStack(spacing: 10) {
            Circle()
               .strokeBorder(Palette.accent, style: StrokeStyle(lineWidth: 1.5, dash: [4, 4]))
               .overlay {
                  Image(systemName: "plus")
                     .font(.system(size: 20, weight: .light))
                     .foregroundStyle(Palette.accent)
               }
               .frame(width: 76, height: 76)

            Text("Add story")
               .font(.system(size: 13))
               .foregroundStyle(Palette.textPrimary.opacity(0.75))
               .frame(width: 80)
         }
      }
      .buttonStyle(.plain)
   }
}


private struct StoryPlaceholder: View {
   var body: some View {
      VStack(spacing: 10) {
         Circle()
            .fill(Palette.raised)
            .frame(width: 76, height: 76)

         Capsule()
            .fill(Palette.raised)
            .frame(width: 54, height: 10)
      }
      .frame(width: 80)
   }
}