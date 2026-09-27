import Foundation

// The capabilities the engine's SyncClient exposes at 1.1.0. The bridge wrapper (roadmap 5.2)
// and DummyEngine both conform, so stores cannot tell which one they are talking to.
protocol EngineClient: Sendable {
   var viewerID: String { get }

   func feed(after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.FeedItem>>
   func profile(username: String) async throws(EngineError) -> EngineResult<Engine.Profile>
   func profile(id userID: String) async throws(EngineError) -> EngineResult<Engine.Profile>
   func post(code: String) async throws(EngineError) -> EngineResult<Engine.Post>
   func comments(postPK: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.Comment>>

   func like(postPK: String) async throws(EngineError) -> EngineResult<Void>
   func unlike(postPK: String) async throws(EngineError) -> EngineResult<Void>
   func comment(postPK: String, text: String) async throws(EngineError) -> EngineResult<Engine.Comment>
   func deleteComment(postPK: String, commentID: String) async throws(EngineError) -> EngineResult<Void>
   func follow(userID: String) async throws(EngineError) -> EngineResult<Void>
   func unfollow(userID: String) async throws(EngineError) -> EngineResult<Void>
   func publishPhoto(imageURL: URL, caption: String) async throws(EngineError) -> EngineResult<Engine.PublishedPost>
   func publishCarousel(imageURLs: [URL], caption: String) async throws(EngineError) -> EngineResult<Engine.PublishedPost>
   func download(image: Engine.MediaImage, to destination: URL) async throws(EngineError) -> EngineResult<URL>
   func deletePost(postPK: String, code: String) async throws(EngineError) -> EngineResult<Void>

   func inbox(after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.DirectThread>>
   func messages(threadFBID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.Message>>
   func messageRequests() async throws(EngineError) -> EngineResult<Engine.MessageRequests>
   func unreadCounts() async throws(EngineError) -> EngineResult<Engine.UnreadCounts>
   func send(threadFBID: String, text: String) async throws(EngineError) -> EngineResult<Engine.SentMessage>
   func unsend(threadFBID: String, messageID: String) async throws(EngineError) -> EngineResult<Void>
   func notes() async throws(EngineError) -> EngineResult<[Engine.Note]>
   func setNote(text: String, audience: Engine.NoteAudience) async throws(EngineError) -> EngineResult<Engine.Note>
   func deleteNote(noteID: String) async throws(EngineError) -> EngineResult<Void>

   func startEvents(since messageID: String?) async
   func drainEvents() async -> [Engine.Event]
   func stopEvents() async
}

// Capabilities the interface needs that the engine does not have at 1.1.0. Each one is an
// engine gap to close before the bridge can replace the dummy for that page.
protocol ProposedEngineSurface: Sendable {
   func storiesTray() async throws(EngineError) -> EngineResult<[Engine.StoryTrayEntry]>
   func markStorySeen(userID: String) async throws(EngineError) -> EngineResult<Void>
   func reels(after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.Reel>>
   func search(query: String) async throws(EngineError) -> EngineResult<[Engine.UserSummary]>
   func explore() async throws(EngineError) -> EngineResult<[Engine.GridTile]>
   func activity() async throws(EngineError) -> EngineResult<[Engine.ActivityEntry]>
   func followRequests() async throws(EngineError) -> EngineResult<[Engine.UserSummary]>
   func resolveFollowRequest(userID: String, approve: Bool) async throws(EngineError) -> EngineResult<Void>
   func suggestedUsers() async throws(EngineError) -> EngineResult<[Engine.UserSummary]>
   func profileActivity() async throws(EngineError) -> EngineResult<Engine.ProfileActivity>
   func profilePosts(userID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>>
   func profileReels(userID: String) async throws(EngineError) -> EngineResult<[Engine.GridTile]>
   func taggedPosts(userID: String) async throws(EngineError) -> EngineResult<[Engine.GridTile]>
   func savedPosts() async throws(EngineError) -> EngineResult<[Engine.GridTile]>
   func highlights(userID: String) async throws(EngineError) -> EngineResult<[Engine.Highlight]>
   func followers(userID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.UserSummary>>
   func following(userID: String, after cursor: String?) async throws(EngineError) -> EngineResult<Engine.Page<Engine.UserSummary>>
   func save(postPK: String) async throws(EngineError) -> EngineResult<Void>
   func unsave(postPK: String) async throws(EngineError) -> EngineResult<Void>
   func hidePost(postPK: String) async throws(EngineError) -> EngineResult<Void>
   func sharePost(postPK: String, threadFBIDs: [String]) async throws(EngineError) -> EngineResult<Void>
   func likeComment(postPK: String, commentID: String, liked: Bool) async throws(EngineError) -> EngineResult<Void>
   func replyToComment(postPK: String, parentCommentID: String, text: String) async throws(EngineError) -> EngineResult<Engine.Comment>

   func resolveMessageRequest(threadFBID: String, accept: Bool) async throws(EngineError) -> EngineResult<Void>
   func createThread(userIDs: [String]) async throws(EngineError) -> EngineResult<Engine.DirectThread>
   func react(threadFBID: String, messageID: String, emoji: String?) async throws(EngineError) -> EngineResult<Void>
   func sendReply(threadFBID: String, text: String, replyingTo messageID: String) async throws(EngineError) -> EngineResult<Engine.SentMessage>
   func sendPhoto(threadFBID: String, imageURL: URL) async throws(EngineError) -> EngineResult<Engine.SentMessage>
   func setThreadMuted(threadFBID: String, muted: Bool) async throws(EngineError) -> EngineResult<Void>

   func publishStory(imageURL: URL) async throws(EngineError) -> EngineResult<Void>
   func likeStory(userID: String) async throws(EngineError) -> EngineResult<Void>
   func archivedStories() async throws(EngineError) -> EngineResult<[Engine.GridTile]>

   func editProfile(fullName: String, biography: String, externalURL: String?) async throws(EngineError) -> EngineResult<Engine.Profile>
   func removeFollower(userID: String) async throws(EngineError) -> EngineResult<Void>
   func relationships() async throws(EngineError) -> EngineResult<Engine.Relationships>
   func setCloseFriend(userID: String, included: Bool) async throws(EngineError) -> EngineResult<Void>
   func setBlocked(userID: String, blocked: Bool) async throws(EngineError) -> EngineResult<Void>
   func setMuted(userID: String, muted: Bool) async throws(EngineError) -> EngineResult<Void>

   func searchTags(query: String) async throws(EngineError) -> EngineResult<[Engine.Hashtag]>
   func searchPlaces(query: String) async throws(EngineError) -> EngineResult<[Engine.Place]>
   func hashtagPosts(name: String) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>>
   func placePosts(placeID: String) async throws(EngineError) -> EngineResult<Engine.Page<Engine.GridTile>>
}

typealias AppEngine = EngineClient & ProposedEngineSurface
