"""Typed models, the boundary where upstream schema churn stops.

Everything here is a frozen dataclass holding immutable members. No model parses, validates a
credential, or touches the network, and no model carries an extras bag of unmapped upstream
fields, because an extras bag reopens the boundary this package exists to close.
"""

from dumpstagram.models.comments import Comment, CommentAuthor
from dumpstagram.models.events import Event, EventsDropped, ListenerStopped, NewMessage
from dumpstagram.models.feed import (
   AudioKind,
   CarouselChild,
   FeedItem,
   FeedItemKind,
   MediaAudio,
   MediaImage,
   Post,
   PostAuthor,
   VideoRendition,
)
from dumpstagram.models.messages import Message, MessageSender, Reaction, SentMessage
from dumpstagram.models.notes import Note, NoteAudience
from dumpstagram.models.pagination import Page
from dumpstagram.models.posts import PostDetail, PublishedPost
from dumpstagram.models.profiles import BioLink, FriendshipStatus, Profile

__all__ = [
   "AudioKind",
   "BioLink",
   "CarouselChild",
   "Comment",
   "CommentAuthor",
   "Event",
   "EventsDropped",
   "FeedItem",
   "FeedItemKind",
   "FriendshipStatus",
   "ListenerStopped",
   "MediaAudio",
   "MediaImage",
   "Message",
   "MessageSender",
   "NewMessage",
   "Note",
   "NoteAudience",
   "Page",
   "Post",
   "PostAuthor",
   "PostDetail",
   "PublishedPost",
   "Profile",
   "Reaction",
   "SentMessage",
   "VideoRendition",
]
