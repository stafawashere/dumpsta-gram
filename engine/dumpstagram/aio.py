"""``AsyncClient``, the awaitable public surface.

One account, one client, per ADR-0004. The caller builds a :class:`~dumpstagram.session.Session`
and passes it in, and the client never creates one of its own. That is the whole reason login
can arrive later as another way to populate a `Session` without touching this signature.

This module is thin by rule. It owns the connection pool and the pacer for one account, and
it delegates everything else. It knows nothing about endpoints, headers, cursors, or GraphQL,
and `engine/docs/architecture.md` forbids it from learning any of them.

Capabilities are one method each and hold no logic of their own. Every one of them delegates
to `_core`, which is where pacing, retries, pagination and the token recovery live.
"""

from __future__ import annotations

import os
from types import TracebackType

from dumpstagram._core.direct import read_thread_messages
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import HttpxTransport, cookies_for
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT
from dumpstagram.models import Message, Page
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

   async def thread_messages(
      self,
      thread_fbid: str,
      *,
      after: str | None = None,
      newer_than_message_id: str | None = None,
   ) -> Page[Message]:
      """Read one page of one direct thread.

      ``thread_fbid`` is the thread's ``fbid``, which is one of three identifiers the same
      thread has. The other two return an empty answer rather than an error, so the parameter
      name says which one it wants.

      ``after`` is an ``end_cursor`` from a previous page. ``newer_than_message_id`` fetches
      only what has arrived since a message already seen, which makes a poll a top-up rather
      than a full re-read.

      The returned page's ``has_next_page`` is the only thing that says whether more exist. A
      short page is not the end of the thread.
      """

      self._refuse_when_closed()

      return await read_thread_messages(
         self._sender,
         self._session,
         thread_fbid,
         after=after,
         newer_than_message_id=newer_than_message_id,
         user_agent=self._user_agent,
      )

   def _refuse_when_closed(self) -> None:
      if self._closed:
         raise RuntimeError("this client is closed, so its connection pool is gone")

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
