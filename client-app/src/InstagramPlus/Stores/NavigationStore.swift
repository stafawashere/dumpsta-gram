import Observation
import SwiftUI

enum Route: Hashable {
   case home
   case reels
   case messages
   case search
   case notifications
   case create
   case settings
   case profile(Account.ID)
   case hashtag(String)
   case place(id: String, name: String)
   case archive
   case relationships(RelationshipList)
}

enum RelationshipList: String, Hashable, CaseIterable, Identifiable {
   case closeFriends
   case blocked
   case muted

   var id: String { rawValue }

   var title: String {
      switch self {
         case .closeFriends: "Close friends"
         case .blocked: "Blocked accounts"
         case .muted: "Muted accounts"
      }
   }
}

struct ShareTarget: Identifiable, Hashable {
   let postPK: Post.ID

   var id: String { postPK }
}

struct PresentedHighlight: Hashable {
   let owner: Account
   let highlight: Highlight
   let itemCount: Int
}

enum SidebarDestination: String, CaseIterable, Identifiable {
   case home
   case reels
   case messages
   case search
   case notifications
   case create

   var id: String { rawValue }

   var title: String {
      switch self {
         case .home: "Home"
         case .reels: "Reels"
         case .messages: "Messages"
         case .search: "Search"
         case .notifications: "Notifications"
         case .create: "Create"
      }
   }

   var symbolName: String {
      switch self {
         case .home: "house"
         case .reels: "play.rectangle"
         case .messages: "paperplane"
         case .search: "magnifyingglass"
         case .notifications: "heart"
         case .create: "plus"
      }
   }

   var selectedSymbolName: String {
      switch self {
         case .search, .create: symbolName
         default: symbolName + ".fill"
      }
   }

   var route: Route {
      switch self {
         case .home: .home
         case .reels: .reels
         case .messages: .messages
         case .search: .search
         case .notifications: .notifications
         case .create: .create
      }
   }

   var shortcutKey: KeyEquivalent {
      let position = SidebarDestination.allCases.firstIndex(of: self) ?? 0
      return KeyEquivalent(Character(String(position + 1)))
   }
}

@MainActor
@Observable
final class NavigationStore {
   var route: Route = .home
   var searchQuery = ""
   var presentedStoryAuthorID: Account.ID?
   var presentedPostCode: String?
   var presentedHighlight: PresentedHighlight?
   var sharing: ShareTarget?
   var isComposingMessage = false
   var isComposingStory = false
   var isEditingProfile = false
   var isConfirmingLogOut = false

   var sidebarSelection: SidebarDestination? {
      SidebarDestination.allCases.first { $0.route == route }
   }

   var showsRightRail: Bool {
      route == .home
   }

   var isShowingOverlay: Bool {
      let isShowingStory = presentedStoryAuthorID != nil
      let isShowingPost = presentedPostCode != nil
      let isShowingHighlight = presentedHighlight != nil
      return isShowingStory || isShowingPost || isShowingHighlight
   }

   func open(_ destination: SidebarDestination) {
      route = destination.route
   }

   func openProfile(_ accountID: Account.ID) {
      dismissOverlays()
      route = .profile(accountID)
   }

   func showStory(authorID: Account.ID) {
      presentedStoryAuthorID = authorID
   }

   func showPost(code: String) {
      presentedPostCode = code
   }

   func share(postPK: Post.ID) {
      sharing = ShareTarget(postPK: postPK)
   }

   func dismissOverlays() {
      presentedStoryAuthorID = nil
      presentedPostCode = nil
      presentedHighlight = nil
   }
}
