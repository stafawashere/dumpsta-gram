"""Typed models, the boundary where upstream schema churn stops.

Everything here is a frozen dataclass holding immutable members. No model parses, validates a
credential, or touches the network, and no model carries an extras bag of unmapped upstream
fields, because an extras bag reopens the boundary this package exists to close.
"""

from dumpstagram.models.account import (
   ActivityCounts,
   ActivityFeed,
   ActivityItem,
   ActivityLink,
   ActivityMedia,
   ActivitySection,
   FollowRequests,
)
from dumpstagram.models.comments import Comment, CommentAuthor
from dumpstagram.models.discovery import (
   ExploreGrid,
   ExploreSection,
   LocationPosts,
   LocationTab,
   Place,
)
from dumpstagram.models.events import Event, EventsDropped, ListenerStopped, NewMessage
from dumpstagram.models.feed import (
   AudioKind,
   CarouselChild,
   FeedItem,
   FeedItemKind,
   Location,
   MediaAudio,
   MediaImage,
   Post,
   PostAuthor,
   UserTag,
   VideoRendition,
)
from dumpstagram.models.highlights import Highlight, HighlightTray
from dumpstagram.models.messages import Message, MessageSender, Reaction, SentMessage
from dumpstagram.models.notes import Note, NoteAudience
from dumpstagram.models.pagination import Page
from dumpstagram.models.posts import PostDetail, PostThumbnail, PublishedPost
from dumpstagram.models.profiles import (
   BioLink,
   FriendshipStatus,
   ListFriendshipStatus,
   Profile,
   ProfileSummary,
   SuggestedAccount,
)
from dumpstagram.models.search import Hashtag, RecentSearch, RecentSearchKind
from dumpstagram.models.stories import (
   StoryItem,
   StoryMention,
   StoryMusic,
   StoryOwner,
   StoryReel,
   StoryVideo,
   TrayReel,
)
from dumpstagram.models.threads import (
   DirectThread,
   MessageRequests,
   ThreadParticipant,
   UnreadCounts,
)

__all__ = [
   "ActivityCounts",
   "ActivityFeed",
   "ActivityItem",
   "ActivityLink",
   "ActivityMedia",
   "ActivitySection",
   "FollowRequests",
   "AudioKind",
   "BioLink",
   "CarouselChild",
   "Comment",
   "CommentAuthor",
   "DirectThread",
   "Event",
   "EventsDropped",
   "ExploreGrid",
   "ExploreSection",
   "FeedItem",
   "FeedItemKind",
   "FriendshipStatus",
   "Hashtag",
   "Highlight",
   "HighlightTray",
   "ListFriendshipStatus",
   "ListenerStopped",
   "Location",
   "LocationPosts",
   "LocationTab",
   "MediaAudio",
   "MediaImage",
   "Message",
   "MessageRequests",
   "MessageSender",
   "NewMessage",
   "Note",
   "NoteAudience",
   "Page",
   "Place",
   "Post",
   "PostAuthor",
   "PostDetail",
   "PostThumbnail",
   "PublishedPost",
   "Profile",
   "ProfileSummary",
   "Reaction",
   "RecentSearch",
   "RecentSearchKind",
   "SentMessage",
   "StoryItem",
   "StoryMention",
   "StoryMusic",
   "StoryOwner",
   "StoryReel",
   "StoryVideo",
   "SuggestedAccount",
   "ThreadParticipant",
   "TrayReel",
   "UnreadCounts",
   "UserTag",
   "VideoRendition",
]
