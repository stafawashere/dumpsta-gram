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
from dumpstagram.session import SCHEMA_VERSION, ProxyConfig, Session, SpinParameters

__all__ = [
   "RETRYABLE",
   "SCHEMA_VERSION",
   "AsyncClient",
   "AuthenticationFailed",
   "CheckpointRequired",
   "DumpstagramError",
   "NotFound",
   "OperationCancelled",
   "RateLimited",
   "ProxyConfig",
   "SchemaChanged",
   "Session",
   "SpinParameters",
   "SyncClient",
   "TransportFailure",
   "UpstreamRejected",
]

_getLogger("dumpstagram").addHandler(_NullHandler())
