"""Public exception hierarchy.

Callers catch these. A transport exception, an ``httpx`` exception, or an upstream payload
never reaches a caller in any other form.

The hierarchy is deliberately flat. Retryability is expressed by membership of
:data:`RETRYABLE` rather than by a shared base class, because a base class named for
retryability is something a later refactor can make :class:`CheckpointRequired` inherit from
by accident. Retrying around a challenge escalates a soft block into a locked account, so that
exclusion is structural rather than conventional.
"""

__all__ = [
   "RETRYABLE",
   "AuthenticationFailed",
   "CheckpointRequired",
   "DumpstagramError",
   "NotFound",
   "OperationCancelled",
   "RateLimited",
   "SchemaChanged",
   "TransportFailure",
   "UpstreamRejected",
]


class DumpstagramError(Exception):
   """Base class for every error this library raises deliberately.

   Catching this catches every expected failure and no defect. A bug in the library
   propagates as its own type, because catching it makes it harder to find.
   """


class AuthenticationFailed(DumpstagramError):
   """The credentials or the adopted session are not usable.

   Raised when required cookie material is missing, when the session was revoked upstream,
   and when a bootstrap token could not be read from an authenticated page. A server-initiated
   logout arrives as an empty cookie value rather than as a status code.

   Not retryable. The library adopted this session rather than creating it, so it cannot renew
   what it did not create.
   """


class CheckpointRequired(DumpstagramError):
   """The account is in a challenge or checkpoint and needs the user to act.

   This is a state, not a failure to retry. It is excluded from every retry path by
   construction: it is absent from :data:`RETRYABLE` and it shares no base class with any
   member of it.

   A false positive here is a serious defect in its own right. Because the error is never
   retried, a classifier that fires on innocent message content does not degrade an operation,
   it makes the operation permanently unfinishable, with every resume aborting at the same
   point.
   """

   def __init__(self, message: str = "", *, required_action: str | None = None) -> None:
      super().__init__(message)
      self.required_action = required_action


class UpstreamRejected(DumpstagramError):
   """Instagram rejected the request.

   Arrives as HTTP 200 carrying an error envelope rather than as a 4xx, so this is decided by
   reading the body. Missing or stale request tokens land here, as does a response that is the
   HTML application shell instead of the expected payload.

   Whether it is worth retrying depends on ``code``, so this type is not a member of
   :data:`RETRYABLE`.
   """

   def __init__(self, message: str = "", *, code: str | None = None) -> None:
      super().__init__(message)
      self.code = code


class RateLimited(DumpstagramError):
   """The pacer or the upstream says to wait.

   Retryable, with backoff that applies to the whole account rather than to one request.
   ``retry_after`` carries the upstream value in seconds when one was supplied.
   """

   def __init__(self, message: str = "", *, retry_after: float | None = None) -> None:
      super().__init__(message)
      self.retry_after = retry_after


class NotFound(DumpstagramError):
   """The target does not exist, or it is not visible to this account.

   Ordinary absence is not this error. A profile with no posts returns an empty sequence. This
   is raised when the object itself cannot be reached, which on this upstream includes passing
   the wrong kind of identifier, since that returns nothing rather than an error.
   """


class SchemaChanged(DumpstagramError):
   """A response could not be mapped, so the library refuses to guess.

   Loud on purpose. The worst failure this upstream produces is a field rename that degrades
   records silently under a permissive mapper, which is caught only by comparison against a
   recorded capture. ``path`` names where the mapping gave up.
   """

   def __init__(self, message: str = "", *, path: str | None = None) -> None:
      super().__init__(message)
      self.path = path


class TransportFailure(DumpstagramError):
   """A network-level failure, translated at the transport boundary.

   Every underlying HTTP client exception is converted here and chained with ``raise ... from``,
   so the HTTP library stays an implementation choice rather than part of the contract.
   """


class OperationCancelled(DumpstagramError):
   """The awaited work was cancelled.

   Exists because of the threading model rather than because of Instagram.
   ``asyncio.CancelledError`` is a ``BaseException`` and would slip past a caller's
   ``except Exception``, so the facade translates it at the loop-thread boundary. That is the
   only translation the facade performs.
   """


RETRYABLE: tuple[type[DumpstagramError], ...] = (TransportFailure, RateLimited)
"""The only error types a retry path may act on.

Membership is the whole mechanism. Adding a type here is a decision about account safety, and
:class:`CheckpointRequired` is excluded structurally rather than by a comment asking nobody to
retry it.
"""
