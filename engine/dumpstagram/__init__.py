"""Dumpsta-Engine, a high-level Python client for Instagram.

Everything importable from here without a leading underscore carries the stability promise in
`docs/public-api.md`. `dumpstagram._core` and `dumpstagram._private` carry none.
"""

from logging import NullHandler as _NullHandler
from logging import getLogger as _getLogger

from dumpstagram.aio import AsyncClient
from dumpstagram.client import SyncClient
from dumpstagram.errors import (
   RETRYABLE,
   AuthenticationFailed,
   CheckpointRequired,
   DumpstagramError,
   NotFound,
   OperationCancelled,
   RateLimited,
   SchemaChanged,
   TransportFailure,
   UpstreamRejected,
)
from dumpstagram.models import (
   BioLink,
   FeedItem,
   FeedItemKind,
   MediaImage,
   Message,
   MessageSender,
   Page,
   Post,
   PostAuthor,
   Profile,
   Reaction,
)
from dumpstagram.session import SCHEMA_VERSION, ProxyConfig, Session, SpinParameters

__all__ = [
   "RETRYABLE",
   "SCHEMA_VERSION",
   "AsyncClient",
   "AuthenticationFailed",
   "BioLink",
   "CheckpointRequired",
   "DumpstagramError",
   "FeedItem",
   "FeedItemKind",
   "MediaImage",
   "Message",
   "MessageSender",
   "NotFound",
   "OperationCancelled",
   "Page",
   "Post",
   "PostAuthor",
   "Profile",
   "RateLimited",
   "ProxyConfig",
   "Reaction",
   "SchemaChanged",
   "Session",
   "SpinParameters",
   "SyncClient",
   "TransportFailure",
   "UpstreamRejected",
]

_getLogger("dumpstagram").addHandler(_NullHandler())
