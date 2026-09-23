"""Dumpsta-Engine, a high-level Python client for Instagram.

Everything importable from here without a leading underscore carries the stability promise in
`docs/public-api.md`. `dumpstagram._core` and `dumpstagram._private` carry none.
"""

from logging import NullHandler as _NullHandler
from logging import getLogger as _getLogger

from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import (
   EXPORT,
   FAST,
   PARITY,
   Behavior,
   FeedFirstPage,
   ProfileRoute,
   Spacing,
   ThreadFirstPage,
)
from dumpstagram.client import SyncClient
from dumpstagram.errors import (
   RETRYABLE,
   AuthenticationFailed,
   CheckpointRequired,
   DumpstagramError,
   NotFound,
   OperationCancelled,
   OutcomeUnknown,
   RateLimited,
   SchemaChanged,
   TransportFailure,
   UpstreamRejected,
)
from dumpstagram.listener import EventListener
from dumpstagram.models import (
   BioLink,
   Comment,
   CommentAuthor,
   Event,
   EventsDropped,
   FeedItem,
   FeedItemKind,
   FriendshipStatus,
   ListenerStopped,
   MediaImage,
   Message,
   MessageSender,
   NewMessage,
   Note,
   NoteAudience,
   Page,
   Post,
   PostAuthor,
   PostDetail,
   Profile,
   Reaction,
)
from dumpstagram.session import SCHEMA_VERSION, ProxyConfig, Session, SpinParameters

__all__ = [
   "EXPORT",
   "FAST",
   "PARITY",
   "RETRYABLE",
   "SCHEMA_VERSION",
   "AsyncClient",
   "AuthenticationFailed",
   "Behavior",
   "BioLink",
   "CheckpointRequired",
   "Comment",
   "CommentAuthor",
   "DumpstagramError",
   "Event",
   "EventListener",
   "EventsDropped",
   "FeedFirstPage",
   "FeedItem",
   "FeedItemKind",
   "FriendshipStatus",
   "ListenerStopped",
   "MediaImage",
   "Message",
   "MessageSender",
   "NewMessage",
   "NotFound",
   "Note",
   "NoteAudience",
   "OperationCancelled",
   "OutcomeUnknown",
   "Page",
   "Post",
   "PostAuthor",
   "PostDetail",
   "Profile",
   "ProfileRoute",
   "RateLimited",
   "ProxyConfig",
   "Reaction",
   "SchemaChanged",
   "Session",
   "Spacing",
   "SpinParameters",
   "SyncClient",
   "ThreadFirstPage",
   "TransportFailure",
   "UpstreamRejected",
]

_getLogger("dumpstagram").addHandler(_NullHandler())
