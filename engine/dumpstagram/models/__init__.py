"""Typed models, the boundary where upstream schema churn stops.

Everything here is a frozen dataclass holding immutable members. No model parses, validates a
credential, or touches the network, and no model carries an extras bag of unmapped upstream
fields, because an extras bag reopens the boundary this package exists to close.
"""

from dumpstagram.models.feed import FeedItem, FeedItemKind, MediaImage, Post, PostAuthor
from dumpstagram.models.messages import Message, MessageSender, Reaction
from dumpstagram.models.notes import Note, NoteAudience
from dumpstagram.models.pagination import Page
from dumpstagram.models.profiles import BioLink, Profile

__all__ = [
   "BioLink",
   "FeedItem",
   "FeedItemKind",
   "MediaImage",
   "Message",
   "MessageSender",
   "Note",
   "NoteAudience",
   "Page",
   "Post",
   "PostAuthor",
   "Profile",
   "Reaction",
]
