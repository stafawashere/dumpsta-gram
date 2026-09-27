import SwiftUI
import UniformTypeIdentifiers

struct CreateView: View {
   @Environment(HomeStore.self) private var home
   @Environment(ProfileStore.self) private var profiles
   @Environment(NavigationStore.self) private var navigation

   @State private var mediaURLs: [URL] = []
   @State private var previewIndex = 0
   @State private var caption = ""
   @State private var location = ""
   @State private var hidesLikeCount = false
   @State private var commentsDisabled = false
   @State private var isImporting = false
   @State private var isDropTargeted = false

   private static let captionLimit = 2_200
   private static let carouselLimit = 10

   var body: some View {
      ScrollView {
         VStack(alignment: .leading, spacing: 24) {
            SectionTitle(text: "Create new post", size: 24)

            HStack(alignment: .top, spacing: 24) {
               mediaPane
                  .frame(maxWidth: 520)
                  .aspectRatio(1, contentMode: .fit)

               detailsPane
                  .frame(width: 340)
            }
         }
         .frame(maxWidth: 900)
         .padding(.horizontal, 40)
         .padding(.vertical, 36)
         .frame(maxWidth: .infinity)
      }
      .fileImporter(isPresented: $isImporting, allowedContentTypes: [.image], allowsMultipleSelection: true) { result in
         if case .success(let urls) = result {
            add(urls)
         }
      }
   }

   private var mediaPane: some View {
      ZStack {
         if mediaURLs.isEmpty {
            RoundedRectangle(cornerRadius: 16, style: .continuous)
               .fill(isDropTargeted ? Palette.raised : Palette.card)
               .overlay(
                  RoundedRectangle(cornerRadius: 16, style: .continuous)
                     .strokeBorder(Palette.hairline, style: StrokeStyle(lineWidth: 1.5, dash: [6, 6]))
               )
               .overlay {
                  VStack(spacing: 16) {
                     Image(systemName: "photo.on.rectangle.angled")
                        .font(.system(size: 52, weight: .light))
                        .foregroundStyle(Palette.textPrimary)

                     Text("Drag photos here")
                        .font(.system(size: 18))
                        .foregroundStyle(Palette.textPrimary)

                     Text("Choose two to ten to share a carousel.")
                        .font(.system(size: 12))
                        .foregroundStyle(Palette.textSecondary)

                     PrimaryButton(title: "Select from computer") {
                        isImporting = true
                     }
                  }
               }
         } else {
            let shownIndex = min(previewIndex, mediaURLs.count - 1)

            MediaView(seed: "create", url: mediaURLs[shownIndex], cornerRadius: 16)
               .overlay(alignment: .bottom) {
                  HStack(spacing: 8) {
                     ForEach(Array(mediaURLs.enumerated()), id: \.element) { position, url in
                        MediaView(seed: "thumb", url: url, cornerRadius: 6)
                           .frame(width: 48, height: 48)
                           .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(.white, lineWidth: position == shownIndex ? 2 : 0))
                           .overlay(alignment: .topTrailing) {
                              Button {
                                 remove(at: position)
                              } label: {
                                 Image(systemName: "xmark.circle.fill")
                                    .foregroundStyle(.white, .black.opacity(0.6))
                              }
                              .buttonStyle(.plain)
                              .offset(x: 5, y: -5)
                           }
                           .onTapGesture { previewIndex = position }
                     }

                     if mediaURLs.count < Self.carouselLimit {
                        Button {
                           isImporting = true
                        } label: {
                           Image(systemName: "plus")
                              .font(.system(size: 16, weight: .semibold))
                              .foregroundStyle(.white)
                              .frame(width: 48, height: 48)
                              .background(.black.opacity(0.4), in: RoundedRectangle(cornerRadius: 6))
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("Add photos")
                     }
                  }
                  .padding(12)
                  .background(.black.opacity(0.25), in: RoundedRectangle(cornerRadius: 12))
                  .padding(16)
               }
         }
      }
      .dropDestination(for: URL.self) { urls, _ in
         add(urls)
         return !urls.isEmpty
      } isTargeted: { isDropTargeted = $0 }
   }

   private func add(_ urls: [URL]) {
      let room = Self.carouselLimit - mediaURLs.count
      mediaURLs.append(contentsOf: urls.prefix(max(0, room)))
   }

   private func remove(at position: Int) {
      mediaURLs.remove(at: position)
      previewIndex = 0
   }

   private var detailsPane: some View {
      let hasImage = !mediaURLs.isEmpty
      let isWithinLimit = caption.count <= Self.captionLimit
      let canShare = hasImage && isWithinLimit && !home.isPublishing

      return VStack(alignment: .leading, spacing: 0) {
         HStack(spacing: 10) {
            Avatar(account: profiles.viewerAccount, diameter: 30, style: .soft)

            Text(profiles.viewerAccount.username)
               .font(.system(size: 14, weight: .semibold))
               .foregroundStyle(Palette.textPrimary)
         }
         .padding(16)

         ZStack(alignment: .topLeading) {
            if caption.isEmpty {
               Text("Write a caption")
                  .font(.system(size: 14))
                  .foregroundStyle(Palette.textTertiary)
                  .padding(.top, 1)
                  .padding(.leading, 5)
            }

            TextEditor(text: $caption)
               .font(.system(size: 14))
               .scrollContentBackground(.hidden)
               .foregroundStyle(Palette.textPrimary)
         }
         .frame(height: 160)
         .padding(.horizontal, 12)

         Text("\(caption.count)/\(Self.captionLimit)")
            .font(.system(size: 11))
            .foregroundStyle(isWithinLimit ? Palette.textTertiary : Palette.badge)
            .frame(maxWidth: .infinity, alignment: .trailing)
            .padding(.horizontal, 16)
            .padding(.bottom, 10)

         Hairline()

         HStack {
            TextField("Add location", text: $location)
               .textFieldStyle(.plain)
               .font(.system(size: 14))

            Image(systemName: "mappin.and.ellipse")
               .foregroundStyle(Palette.textSecondary)
         }
         .padding(16)

         Hairline()

         VStack(alignment: .leading, spacing: 14) {
            Text("Advanced settings")
               .font(.system(size: 14, weight: .semibold))
               .foregroundStyle(Palette.textPrimary)

            Toggle("Hide like and view counts", isOn: $hidesLikeCount)
            Toggle("Turn off commenting", isOn: $commentsDisabled)

            Text("Location and these two settings are not in the engine's publish call yet, so they are not sent.")
               .font(.system(size: 11))
               .foregroundStyle(Palette.textTertiary)
               .fixedSize(horizontal: false, vertical: true)
         }
         .toggleStyle(.switch)
         .font(.system(size: 13))
         .padding(16)

         Hairline()

         HStack(spacing: 12) {
            PrimaryButton(title: "Discard", isProminent: false, action: reset)

            Spacer()

            Button(action: share) {
               Text(home.isPublishing ? "Sharing" : "Share")
                  .font(.system(size: 14, weight: .semibold))
                  .foregroundStyle(.white)
                  .padding(.horizontal, 26)
                  .frame(height: 36)
                  .background(Palette.createGradient, in: Capsule())
                  .opacity(canShare ? 1 : 0.55)
            }
            .buttonStyle(.plain)
            .disabled(!canShare)
         }
         .padding(16)
      }
      .background(Palette.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
      .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(Palette.hairline))
   }

   private func share() {
      let trimmedCaption = caption.trimmingCharacters(in: .whitespacesAndNewlines)
      let urls = mediaURLs

      Task {
         let didPublish = await home.publish(imageURLs: urls, caption: trimmedCaption)

         if didPublish {
            reset()
            navigation.route = .home
         }
      }
   }

   private func reset() {
      mediaURLs = []
      previewIndex = 0
      caption = ""
      location = ""
      hidesLikeCount = false
      commentsDisabled = false
   }
}
