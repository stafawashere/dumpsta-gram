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
from dumpstagram._core.feed import read_feed_page
from dumpstagram._core.pacer import Pacer, PacingPolicy
from dumpstagram._core.profiles import read_profile, read_profile_by_id
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import HttpxTransport, cookies_for
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT
from dumpstagram.behavior import PARITY, Behavior
from dumpstagram.models import FeedItem, Message, Page, Profile
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

   ``behavior`` defaults to :data:`~dumpstagram.behavior.PARITY`. It governs this client's
   traffic across requests, and :meth:`with_behavior` changes it for a stretch of calls
   without a second pool or a second pacer.
   """

   def __init__(
      self,
      session: Session,
      *,
      user_agent: str | None = None,
      behavior: Behavior = PARITY,
   ) -> None:
      self._session = session
      self._user_agent = user_agent or DEFAULT_USER_AGENT
      self._behavior = behavior
      self._closed = False
      self._owner: AsyncClient | None = None

      transport = HttpxTransport(cookies=cookies_for(session), proxy=session.proxy)

      self._sender = PacedSender(transport, Pacer(), pacing_for(behavior))

   @classmethod
   def from_session_file(
      cls,
      path: str | os.PathLike[str],
      *,
      user_agent: str | None = None,
      behavior: Behavior = PARITY,
   ) -> AsyncClient:
      """Load a saved session from ``path`` and build a client around it.

      Raises the same errors :meth:`~dumpstagram.session.Session.load` raises, before any
      pool is created, so a refused file leaves nothing to close.
      """

      return cls(Session.load(path), user_agent=user_agent, behavior=behavior)

   def with_behavior(self, behavior: Behavior) -> AsyncClient:
      """Another client over the same account that differs only in ``behavior``.

      It shares this client's session, connection pool and pacer. Sharing the pacer is the
      point: pacing is per account, so a request from either client is spaced from the
      account's previous request, whichever of the two sent it.

      The returned client does not own the pool. Closing it only stops it, and closing this
      client stops both.
      """

      self._refuse_when_closed()

      scoped = object.__new__(AsyncClient)
      scoped._session = self._session
      scoped._user_agent = self._user_agent
      scoped._behavior = behavior
      scoped._closed = False
      scoped._owner = self._owner or self
      scoped._sender = self._sender.with_pacing(pacing_for(behavior))

      return scoped

   @property
   def session(self) -> Session:
      """The session this client was built with, which the caller still owns."""

      return self._session

   @property
   def user_agent(self) -> str:
      """The user-agent string every request from this client carries."""

      return self._user_agent

   @property
   def behavior(self) -> Behavior:
      """The behavior configuration this client's traffic follows."""

      return self._behavior

   @property
   def closed(self) -> bool:
      """Whether :meth:`aclose` has run, on this client or on the one that owns its pool."""

      owner_closed = self._owner is not None and self._owner.closed

      return self._closed or owner_closed

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

      Under the default behavior the newest page is read with the query a browser sends when
      it opens the thread, and every other page with the query it sends as the thread scrolls.
      :attr:`~dumpstagram.behavior.Behavior.thread_first_page` set to
      :attr:`~dumpstagram.behavior.ThreadFirstPage.QUERY` reads the newest page with the
      scrolling query too. One live request either way.
      """

      self._refuse_when_closed()

      return await read_thread_messages(
         self._sender,
         self._session,
         thread_fbid,
         after=after,
         newer_than_message_id=newer_than_message_id,
         first_page=self._behavior.thread_first_page,
         user_agent=self._user_agent,
      )

   async def profile(self, username: str) -> Profile:
      """Read one account's profile by username.

      Under the default behavior this loads the profile page and sends the page's six queries
      at once, seven requests in one action, as a browser does. It raises
      :class:`~dumpstagram.errors.NotFound` when no account has the username.

      :attr:`~dumpstagram.behavior.Behavior.profile_route` set to
      :attr:`~dumpstagram.behavior.ProfileRoute.QUERIES` spends two requests instead, resolving
      the username through the account's timeline and then reading the profile. That route
      raises :class:`~dumpstagram.errors.NotFound` when the account does not exist, or its
      posts are not visible to this session, or it has none, and cannot say which.

      A caller that already holds the id wants :meth:`profile_by_id`, one request.
      """

      self._refuse_when_closed()

      return await read_profile(
         self._sender,
         self._session,
         username,
         route=self._behavior.profile_route,
         user_agent=self._user_agent,
      )

   async def profile_by_id(self, user_id: str) -> Profile:
      """Read one account's profile by its numeric account id. One live request.

      ``user_id`` is the account's ``pk``, which is what :attr:`~dumpstagram.models.Profile.id`
      carries. It is not the ``fbid`` the same account carries as a message sender, and the
      two are different numbers for the same person.
      """

      self._refuse_when_closed()

      return await read_profile_by_id(
         self._sender,
         self._session,
         user_id,
         user_agent=self._user_agent,
      )

   async def feed(self, *, after: str | None = None) -> Page[FeedItem]:
      """Read one page of the signed-in account's home timeline. One live request.

      ``after`` is an ``end_cursor`` from a previous page, and omitting it asks for the first
      page. Under the default behavior the first page is read out of the home document, as a
      browser reads it, and it is short: four measured loads carried 3 or 4 items.
      :attr:`~dumpstagram.behavior.Behavior.feed_first_page` set to
      :attr:`~dumpstagram.behavior.FeedFirstPage.QUERY` asks the pagination query instead.

      The returned page holds :class:`~dumpstagram.models.FeedItem` rather than posts, because
      most of a timeline is not posts: of fifteen measured items, six were posts and the rest
      were advertisements and suggestions. An item carrying a post has
      :attr:`~dumpstagram.models.FeedItem.kind` equal to
      :attr:`~dumpstagram.models.FeedItemKind.POST`, and every other kind is reported by name
      and carries nothing.

      The page's length is the upstream's decision. Three measured pages carried 14, 12 and 5
      items for the same request, so a caller collecting posts keeps asking and stops on
      ``has_next_page``, never on a page looking short.
      """

      self._refuse_when_closed()

      return await read_feed_page(
         self._sender,
         self._session,
         after=after,
         first_page=self._behavior.feed_first_page,
         user_agent=self._user_agent,
      )

   def _refuse_when_closed(self) -> None:
      if self.closed:
         raise RuntimeError("this client is closed, so its connection pool is gone")

   async def aclose(self) -> None:
      """Close the connection pool this client created. Idempotent.

      A client from :meth:`with_behavior` created no pool, so closing it only stops it.
      """

      if self._closed:
         return

      self._closed = True

      owns_the_pool = self._owner is None
      if owns_the_pool:
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


def pacing_for(behavior: Behavior) -> PacingPolicy:
   return PacingPolicy(
      floor_seconds=behavior.spacing.floor_seconds,
      mean_jitter_seconds=behavior.spacing.mean_jitter_seconds,
   )
