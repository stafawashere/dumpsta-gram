"""``AsyncClient``, the awaitable public surface.

One account, one client, per ADR-0004. The caller builds a :class:`~dumpstagram.session.Session`
and passes it in, and the client never creates one of its own. That is the whole reason login
can arrive later as another way to populate a `Session` without touching this signature.

This module is thin by rule. It owns the connection pool and the pacer for one account, and
it delegates everything else. It knows nothing about endpoints, headers, cursors, or GraphQL,
and `engine/docs/architecture.md` forbids it from learning any of them.

Capabilities arrive with the typed models in the rest of Phase 2. What is here now is the
lifecycle and the ownership contract they will hang off, which is deliberately the first thing
written: the public surface snapshot gates every name added after it.
"""

from __future__ import annotations

import os
from types import TracebackType

from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import HttpxTransport, cookies_for
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT
from dumpstagram.session import Session

__all__ = ["AsyncClient"]


class AsyncClient:
   """The awaitable surface over one account.

   The client owns the HTTP connection pool it creates and closes it in :meth:`aclose`. The
   `Session` belongs to the caller: the library mutates its documented token fields and never
   writes its file. Closing twice is a no-op, and a closed client stays closed.

   ``user_agent`` defaults to the string the request builders were measured against. Passing a
   different one changes what every request this client sends claims to be, which is a
   fingerprint decision rather than a cosmetic one.
   """

   def __init__(self, session: Session, *, user_agent: str | None = None) -> None:
      self._session = session
      self._user_agent = user_agent or DEFAULT_USER_AGENT
      self._closed = False

      transport = HttpxTransport(cookies=cookies_for(session), proxy=session.proxy)

      self._sender = PacedSender(transport, Pacer())

   @classmethod
   def from_session_file(
      cls, path: str | os.PathLike[str], *, user_agent: str | None = None
   ) -> AsyncClient:
      """Load a saved session from ``path`` and build a client around it.

      Raises the same errors :meth:`~dumpstagram.session.Session.load` raises, before any
      pool is created, so a refused file leaves nothing to close.
      """

      return cls(Session.load(path), user_agent=user_agent)

   @property
   def session(self) -> Session:
      """The session this client was built with, which the caller still owns."""

      return self._session

   @property
   def user_agent(self) -> str:
      """The user-agent string every request from this client carries."""

      return self._user_agent

   @property
   def closed(self) -> bool:
      """Whether :meth:`aclose` has run."""

      return self._closed

   async def aclose(self) -> None:
      """Close the connection pool this client created. Idempotent."""

      if self._closed:
         return

      self._closed = True

      await self._sender.aclose()

   async def __aenter__(self) -> AsyncClient:
      return self

   async def __aexit__(
      self,
      exc_type: type[BaseException] | None,
      exc: BaseException | None,
      traceback: TracebackType | None,
   ) -> None:
      await self.aclose()
