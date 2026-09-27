import SwiftUI

struct StoryComposer: View {
   @Environment(HomeStore.self) private var home
   @Environment(\.dismiss) private var dismiss

   @State private var imageURL: URL?
   @State private var isImporting = false
   @State private var isSharing = false

   var body: some View {
      let canShare = imageURL != nil && !isSharing

      VStack(spacing: 16) {
         SheetHeader(title: "New story") { dismiss() }

         Group {
            if let imageURL {
               MediaView(seed: "story.new", url: imageURL, cornerRadius: 12)
            } else {
               RoundedRectangle(cornerRadius: 12, style: .continuous)
                  .strokeBorder(Palette.hairline, style: StrokeStyle(lineWidth: 1.5, dash: [6, 6]))
                  .overlay {
                     VStack(spacing: 12) {
                        Image(systemName: "photo.badge.plus")
                           .font(.system(size: 36, weight: .light))

                        PrimaryButton(title: "Choose a photo") {
                           isImporting = true
                        }
                     }
                  }
            }
         }
         .aspectRatio(9 / 16, contentMode: .fit)
         .frame(height: 380)

         Text("Stories last 24 hours, then move to your archive.")
            .font(.system(size: 12))
            .foregroundStyle(Palette.textSecondary)

         Button(isSharing ? "Sharing" : "Share to your story") {
            guard let imageURL else {
               return
            }

            isSharing = true

            Task {
               let didShare = await home.publishStory(imageURL: imageURL)
               isSharing = false

               if didShare {
                  dismiss()
               }
            }
         }
         .buttonStyle(GradientButtonStyle())
         .disabled(!canShare)
         .padding(.horizontal, 16)
         .padding(.bottom, 16)
      }
      .frame(width: 360)
      .fileImporter(isPresented: $isImporting, allowedContentTypes: [.image]) { result in
         if case .success(let url) = result {
            imageURL = url
         }
      }
   }
}
