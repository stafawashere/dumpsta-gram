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

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from types import TracebackType

from dumpstagram._core.comments import read_comment_page
from dumpstagram._core.cookie_sync import CookieSync
from dumpstagram._core.direct import read_thread_messages
from dumpstagram._core.feed import read_feed_page
from dumpstagram._core.notes import read_notes
from dumpstagram._core.pacer import Pacer, PacingPolicy, WritePolicy
from dumpstagram._core.posts import read_post
from dumpstagram._core.profiles import read_profile, read_profile_by_id
from dumpstagram._core.realtime.buffer import EventBuffer
from dumpstagram._core.realtime.poller import inbox_poller
from dumpstagram._core.realtime.pump import SourceContext, SourceFactory, pump_events
from dumpstagram._core.requesting import BackgroundSender, PacedSender
from dumpstagram._core.writes.comments import create_comment, delete_comment
from dumpstagram._core.writes.likes import like_post, unlike_post
from dumpstagram._private.transport import HttpxTransport, cookies_for
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, FACEBOOK_HOST, INSTAGRAM_HOST
from dumpstagram.behavior import PARITY, Behavior
from dumpstagram.errors import CheckpointRequired
from dumpstagram.models import (
   Comment,
   Event,
   FeedItem,
   ListenerStopped,
   Message,
   Note,
   Page,
   PostDetail,
   Profile,
)
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

      transport = HttpxTransport(
         cookies=cookies_for(session),
         proxy=session.proxy,
         allowed_host=INSTAGRAM_HOST,
      )
      self._facebook = HttpxTransport(
         proxy=session.proxy,
         allowed_host=FACEBOOK_HOST,
         cookieless=True,
      )

      self._sender = PacedSender(
         transport, Pacer(), pacing_for(behavior), write_policy_for(behavior)
      )
      self._cookie_sync = CookieSync(
         self._sender.background(),
         BackgroundSender(self._facebook, self._sender.pacer),
      )
      self._event_source: SourceFactory = inbox_poller

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
      scoped._facebook = self._facebook
      scoped._sender = self._sender.with_pacing(pacing_for(behavior), write_policy_for(behavior))
      scoped._cookie_sync = self._cookie_sync
      scoped._event_source = self._event_source

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

      return await self._watch_for_checkpoint(
         read_thread_messages(
            self._sender,
            self._session,
            thread_fbid,
            after=after,
            newer_than_message_id=newer_than_message_id,
            first_page=self._behavior.thread_first_page,
            user_agent=self._user_agent,
         )
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

      return await self._watch_for_checkpoint(
         read_profile(
            self._sender,
            self._session,
            username,
            route=self._behavior.profile_route,
            companions=self._behavior.page_load_companions,
            cookie_sync=self._cookie_sync_if_on(),
            user_agent=self._user_agent,
         )
      )

   async def profile_by_id(self, user_id: str) -> Profile:
      """Read one account's profile by its numeric account id. One live request.

      ``user_id`` is the account's ``pk``, which is what :attr:`~dumpstagram.models.Profile.id`
      carries. It is not the ``fbid`` the same account carries as a message sender, and the
      two are different numbers for the same person.
      """

      self._refuse_when_closed()

      return await self._watch_for_checkpoint(
         read_profile_by_id(
            self._sender,
            self._session,
            user_id,
            user_agent=self._user_agent,
         )
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

      return await self._watch_for_checkpoint(
         read_feed_page(
            self._sender,
            self._session,
            after=after,
            first_page=self._behavior.feed_first_page,
            companions=self._behavior.page_load_companions,
            cookie_sync=self._cookie_sync_if_on(),
            user_agent=self._user_agent,
         )
      )

   async def notes(self) -> tuple[Note, ...]:
      """Read the notes tray on the direct inbox, whole, in the tray's order. One live request.

      Each author has at most one note, and the viewer's own is the one whose
      :attr:`~dumpstagram.models.Note.author_id` equals this session's ``ds_user_id``. It is
      absent when the viewer has no note.

      The tray is one call with no cursor. If the upstream ever starts paging it, this raises
      :class:`~dumpstagram.errors.SchemaChanged` rather than returning the first page as the
      whole tray.

      A browser reads the tray inside an inbox page load, beside nine other queries. This sends
      the tray query alone under every behavior, a departure recorded in
      ``docs/web-request-contract.md`` until the inbox load is modelled.
      """

      self._refuse_when_closed()

      return await self._watch_for_checkpoint(
         read_notes(
            self._sender,
            self._session,
            user_agent=self._user_agent,
         )
      )

   async def post(self, code: str) -> PostDetail:
      """Read one post by the shortcode in its web address. One live request.

      The answer carries both of the post's identifiers, and :attr:`PostDetail.pk
      <dumpstagram.models.PostDetail.pk>` is the one :meth:`like` and :meth:`unlike` take. It
      carries ``has_liked`` and ``like_count`` for this viewer, which is how a like is
      confirmed, and how one whose outcome was unknown is reconciled.

      A browser reads a post inside a post page load. This sends the post query alone under
      every behavior, a departure recorded in ``docs/web-request-contract.md``.
      """

      self._refuse_when_closed()

      return await self._watch_for_checkpoint(
         read_post(
            self._sender,
            self._session,
            code,
            user_agent=self._user_agent,
         )
      )

   async def like(self, post_pk: str) -> None:
      """Like the post whose media ``pk`` is ``post_pk``. One write, sent once, never retried.

      ``post_pk`` is :attr:`Post.pk <dumpstagram.models.Post.pk>` or
      :attr:`PostDetail.pk <dumpstagram.models.PostDetail.pk>`. The ``<pk>_<author id>`` form in
      their ``id`` raises :class:`ValueError` before anything is sent.

      Liking a post that is already liked succeeds and changes nothing, observed once. The write
      waits out the behavior's write spacing, counts against its write budget, and raises
      :class:`~dumpstagram.errors.OutcomeUnknown` if the connection fails while it is in flight.
      To reconcile that, read the post with :meth:`post` and look at ``has_liked``.

      The request a browser sends around a like has not been recorded, so this sends the like
      alone, a departure recorded in ``docs/web-request-contract.md``.
      """

      self._refuse_when_closed()

      await self._watch_for_checkpoint(
         like_post(
            self._sender,
            self._session,
            post_pk,
            user_agent=self._user_agent,
         )
      )

   async def unlike(self, post_pk: str) -> None:
      """Unlike the post whose media ``pk`` is ``post_pk``. One write, sent once, never retried.

      The same identifier, rules and reconciliation as :meth:`like`. Unliking a post that is
      not liked succeeds and changes nothing, observed once.
      """

      self._refuse_when_closed()

      await self._watch_for_checkpoint(
         unlike_post(
            self._sender,
            self._session,
            post_pk,
            user_agent=self._user_agent,
         )
      )

   async def comments(self, post_pk: str, *, after: str | None = None) -> Page[Comment]:
      """Read one page of the comments on the post whose media ``pk`` is ``post_pk``.

      One live request. ``after`` is the previous page's ``end_cursor``, and ``has_next_page``
      is the only sign that more exist: a short or empty page is not the end. This is the read
      that confirms :meth:`comment` and :meth:`delete_comment`, and the one that reconciles
      either after :class:`~dumpstagram.errors.OutcomeUnknown`.

      ``post_pk`` is :attr:`Post.pk <dumpstagram.models.Post.pk>` or
      :attr:`PostDetail.pk <dumpstagram.models.PostDetail.pk>`, and the ``<pk>_<author id>``
      form raises :class:`ValueError` before anything is sent.

      A browser reads comments inside a post page load, its first page with a query of its
      own. This sends the pagination query alone for every page, a departure recorded in
      ``docs/web-request-contract.md``.
      """

      self._refuse_when_closed()

      return await self._watch_for_checkpoint(
         read_comment_page(
            self._sender,
            self._session,
            post_pk,
            after=after,
            user_agent=self._user_agent,
         )
      )

   async def comment(self, post_pk: str, text: str) -> Comment:
      """Comment ``text`` on the post whose media ``pk`` is ``post_pk``. One write, sent once.

      Returns the created comment, whose ``id`` is what :meth:`delete_comment` takes. Its
      ``like_count``, ``reply_count``, ``parent_comment_id`` and ``has_liked`` are None, because
      the answer to a new comment does not carry them. Empty text raises :class:`ValueError`.

      A comment appends, so it is never sent again, by this library or by any retry path. If
      the connection fails while it is in flight this raises
      :class:`~dumpstagram.errors.OutcomeUnknown`, and sending again may post it twice where
      everyone who can see the post sees it. To reconcile, read the post's comments with
      :meth:`comments` and look for the viewer's own comment with this text created after the
      attempt began, and only then decide.

      The write waits out the behavior's write spacing and counts against its write budget.
      The request a browser sends around a comment has not been recorded, so this sends the
      comment alone, a departure recorded in ``docs/web-request-contract.md``.
      """

      self._refuse_when_closed()

      return await self._watch_for_checkpoint(
         create_comment(
            self._sender,
            self._session,
            post_pk,
            text,
            user_agent=self._user_agent,
         )
      )

   async def delete_comment(self, post_pk: str, comment_id: str) -> None:
      """Delete the comment ``comment_id`` on the post whose media ``pk`` is ``post_pk``.

      One write, sent once, never retried. Both identifiers are digits only, and the upstream
      takes them together. ``comment_id`` is :attr:`Comment.id
      <dumpstagram.models.Comment.id>`.

      Raises :class:`~dumpstagram.errors.UpstreamRejected` with code ``comment_not_deleted``
      when the upstream answers that nothing was deleted, which is how it answered a delete
      naming no existing comment. After :class:`~dumpstagram.errors.OutcomeUnknown`, read the
      comments with :meth:`comments`: a comment that is no longer listed is gone.
      """

      self._refuse_when_closed()

      await self._watch_for_checkpoint(
         delete_comment(
            self._sender,
            self._session,
            post_pk,
            comment_id,
            user_agent=self._user_agent,
         )
      )

   async def events(self, *, since: str | None = None) -> AsyncIterator[Event]:
      """Every new direct message on this account, for as long as the iteration runs.

      ``async for event in client.events()`` yields a :class:`~dumpstagram.models.NewMessage`
      for each message not delivered before, in any thread, including the viewer's own messages
      sent from elsewhere. Within a thread they arrive in ascending ``sent_at``, and no message
      arrives twice. ``since`` is the id of the last message the consumer handled, so a
      restarted listener picks up after it and never delivers it again. Without it the listener
      starts from what it first sees.

      The listener polls, waiting :attr:`~dumpstagram.behavior.Behavior.poll_interval_seconds`
      between polls, and every request a poll sends passes this account's pacer. A
      :class:`~dumpstagram.errors.TransportFailure` or :class:`~dumpstagram.errors.RateLimited`
      is retried with account-wide backoff, and one that outlasts its retries costs that poll
      only. Anything else ends the iteration by raising the object the poll raised, and a
      :class:`~dumpstagram.errors.CheckpointRequired` is never polled through.

      Events wait in a buffer of 1000 while the consumer is busy. Past that the oldest are
      dropped, and a :class:`~dumpstagram.models.EventsDropped` saying how many stands where
      they were. Leaving the loop stops the polling. Closing it explicitly, with
      ``contextlib.aclosing``, stops it at once rather than when the iterator is collected.

      Each poll reads the inbox's first page of threads, one request, and reads back each
      thread whose newest message moved, one request per page of up to 20 messages. The first
      poll delivers nothing without ``since``, and nothing a poll cannot account for is skipped
      quietly: a gap it could not read back, or a ``since`` it could not find, arrives as an
      :class:`~dumpstagram.models.EventsDropped` with ``count`` None. No thread is marked seen.
      """

      self._refuse_when_closed()

      buffer = EventBuffer()
      arrived = asyncio.Event()

      def emit(event: Event) -> None:
         buffer.put(event)
         arrived.set()

      async def poll_until_stopped() -> None:
         try:
            await self._poll_for_events(emit, since=since)
         except Exception as failure:
            buffer.finish(ListenerStopped(error=failure))
            arrived.set()

      polling = asyncio.create_task(poll_until_stopped())

      try:
         while True:
            arrived.clear()

            for event in buffer.drain():
               if isinstance(event, ListenerStopped):
                  raise event.error

               yield event

            await arrived.wait()
      finally:
         polling.cancel()
         await asyncio.wait([polling])

   async def _poll_for_events(self, emit: Callable[[Event], None], *, since: str | None) -> None:
      """The pump both ``events`` methods run, which returns only by raising."""

      source = self._event_source(
         SourceContext(
            sender=self._sender,
            session=self._session,
            behavior=self._behavior,
            user_agent=self._user_agent,
            since=since,
         )
      )

      await self._watch_for_checkpoint(
         pump_events(
            source,
            emit,
            pacer=self._sender.pacer,
            interval_seconds=self._behavior.poll_interval_seconds,
            since=since,
         )
      )

   def _cookie_sync_if_on(self) -> CookieSync | None:
      return self._cookie_sync if self._behavior.cookie_sync else None

   async def _watch_for_checkpoint[T](self, operation: Awaitable[T]) -> T:
      """Drop a pending cookie sync tail the moment the account turns out to be in a checkpoint,
      since nothing may be sent on its behalf until the user clears it."""

      try:
         return await operation
      except CheckpointRequired:
         self._cookie_sync.drop()
         raise

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
         try:
            await self._cookie_sync.aclose()
         finally:
            try:
               await self._sender.aclose()
            finally:
               await self._facebook.aclose()

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


def write_policy_for(behavior: Behavior) -> WritePolicy:
   return WritePolicy(
      spacing=PacingPolicy(
         floor_seconds=behavior.write_spacing.floor_seconds,
         mean_jitter_seconds=behavior.write_spacing.mean_jitter_seconds,
      ),
      budget_per_hour=behavior.write_budget_per_hour,
      stop_after_unrecognised_rejection=behavior.stop_writes_after_unrecognised_rejection,
   )
