"""``AsyncClient``, the awaitable public surface.

One account, one client, per ADR-0004. The caller builds a :class:`~dumpstagram.session.Session`
and passes it in, and the client never creates one of its own. That is the whole reason login
can arrive later as another way to populate a `Session` without touching this signature.

This module is thin by rule. It owns the connection pool and the pacer for one account, and
it delegates everything else. It knows nothing about endpoints, headers, cursors, or GraphQL,
and `engine/docs/architecture.md` forbids it from learning any of them.

Capabilities live on the domain namespaces in `dumpstagram.namespaces`, reached as
``client.direct``, ``client.feeds`` and the rest, and hold no logic of their own. Every one of
them delegates to `_core`, which is where pacing, retries, pagination and the token recovery
live. The flat methods here are the names `1.0.0` shipped, kept for good, and each one answers
through its namespace alias.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from types import TracebackType

from dumpstagram._core.cookie_sync import CookieSync
from dumpstagram._core.doctor import DEFAULT_BUNDLE_LIMIT, DoctorPlan, RotationDoctor, doctor_plan
from dumpstagram._core.ledger import FileLedger, ledger_path_for
from dumpstagram._core.pacer import Pacer, PacingPolicy, WritePolicy
from dumpstagram._core.realtime.buffer import EventBuffer
from dumpstagram._core.realtime.poller import inbox_poller
from dumpstagram._core.realtime.pump import SourceContext, SourceFactory, pump_events
from dumpstagram._core.requesting import BackgroundSender, PacedSender
from dumpstagram._private.transport import HttpxTransport, cookies_for
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, FACEBOOK_HOST, INSTAGRAM_HOST
from dumpstagram._private.web.bundles import STATIC_BUNDLE_HOST
from dumpstagram._private.web.cdn import CDN_HOST_FAMILY, CDN_MAX_CONNECTIONS
from dumpstagram._private.web.requests.posting import UPLOAD_HOST
from dumpstagram.behavior import PARITY, Behavior
from dumpstagram.errors import CheckpointRequired
from dumpstagram.models import (
   Comment,
   Event,
   FeedItem,
   ListenerStopped,
   Message,
   Note,
   NoteAudience,
   Page,
   PostDetail,
   Profile,
   SentMessage,
)
from dumpstagram.namespaces.direct import AsyncDirect
from dumpstagram.namespaces.feeds import AsyncFeeds
from dumpstagram.namespaces.media import AsyncMedia
from dumpstagram.namespaces.profiles import AsyncProfiles
from dumpstagram.namespaces.social import AsyncSocial
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
      self._cdn = cdn_transport_for(session)

      self._sender = PacedSender(
         transport, Pacer(), pacing_for(behavior), write_policy_for(behavior)
      )
      self._uploads = PacedSender(
         upload_transport_for(session),
         self._sender.pacer,
         pacing_for(behavior),
         write_policy_for(behavior),
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

      The account's write budget and write stop are kept in a pacing ledger beside the file,
      ``<path>.ledger``, so every client built from the same file, in this process or another,
      spends one budget and honours one stop. A client built over a bare `Session` keeps them
      in memory for its own lifetime instead.
      """

      client = cls(Session.load(path), user_agent=user_agent, behavior=behavior)
      client._keep_write_record_beside(path)

      return client

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
      scoped._cdn = self._cdn
      scoped._sender = self._sender.with_pacing(pacing_for(behavior), write_policy_for(behavior))
      scoped._uploads = self._uploads.with_pacing(pacing_for(behavior), write_policy_for(behavior))
      scoped._cookie_sync = self._cookie_sync
      scoped._event_source = self._event_source

      return scoped

   def _keep_write_record_beside(self, session_path: str | os.PathLike[str]) -> None:
      self._sender.pacer.ledger = FileLedger(ledger_path_for(session_path))

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

   @property
   def direct(self) -> AsyncDirect:
      """Direct threads and the notes on the direct inbox, ``client.direct``."""

      return AsyncDirect._of(self)

   @property
   def feeds(self) -> AsyncFeeds:
      """The timelines, ``client.feeds``."""

      return AsyncFeeds._of(self)

   @property
   def media(self) -> AsyncMedia:
      """Posts, their likes, their comments and their downloads, ``client.media``."""

      return AsyncMedia._of(self)

   @property
   def profiles(self) -> AsyncProfiles:
      """Profiles, ``client.profiles``."""

      return AsyncProfiles._of(self)

   @property
   def social(self) -> AsyncSocial:
      """The viewer's relationships to other accounts, ``client.social``."""

      return AsyncSocial._of(self)

   async def thread_messages(
      self,
      thread_fbid: str,
      *,
      after: str | None = None,
      newer_than_message_id: str | None = None,
   ) -> Page[Message]:
      """Read one page of one direct thread. The same call as :meth:`AsyncDirect.messages
      <dumpstagram.namespaces.direct.AsyncDirect.messages>`."""

      return await self.direct.messages(
         thread_fbid,
         after=after,
         newer_than_message_id=newer_than_message_id,
      )

   async def profile(self, username: str) -> Profile:
      """Read one account's profile by username. The same call as
      :meth:`AsyncProfiles.by_username <dumpstagram.namespaces.profiles.AsyncProfiles.by_username>`.
      """

      return await self.profiles.by_username(username)

   async def profile_by_id(self, user_id: str) -> Profile:
      """Read one account's profile by its numeric account id. The same call as
      :meth:`AsyncProfiles.by_id <dumpstagram.namespaces.profiles.AsyncProfiles.by_id>`."""

      return await self.profiles.by_id(user_id)

   async def feed(self, *, after: str | None = None) -> Page[FeedItem]:
      """Read one page of the home timeline. The same call as :meth:`AsyncFeeds.home
      <dumpstagram.namespaces.feeds.AsyncFeeds.home>`."""

      return await self.feeds.home(after=after)

   async def notes(self) -> tuple[Note, ...]:
      """Read the notes tray on the direct inbox. The same call as :meth:`AsyncDirect.notes
      <dumpstagram.namespaces.direct.AsyncDirect.notes>`."""

      return await self.direct.notes()

   async def set_note(
      self, text: str, *, audience: NoteAudience = NoteAudience.CLOSE_FRIENDS
   ) -> Note:
      """Set the viewer's note on the direct inbox to ``text``. The same call as
      :meth:`AsyncDirect.set_note <dumpstagram.namespaces.direct.AsyncDirect.set_note>`.

      A set replaces any note already up. After :class:`~dumpstagram.errors.OutcomeUnknown`,
      read :meth:`notes` and look for the viewer's own note before deciding anything.
      """

      return await self.direct.set_note(text, audience=audience)

   async def delete_note(self, note_id: str) -> None:
      """Delete the viewer's note. The same call as :meth:`AsyncDirect.delete_note
      <dumpstagram.namespaces.direct.AsyncDirect.delete_note>`."""

      await self.direct.delete_note(note_id)

   async def post(self, code: str) -> PostDetail:
      """Read one post by its shortcode. The same call as :meth:`AsyncMedia.by_code
      <dumpstagram.namespaces.media.AsyncMedia.by_code>`."""

      return await self.media.by_code(code)

   async def like(self, post_pk: str) -> None:
      """Like a post. The same call as :meth:`AsyncMedia.like
      <dumpstagram.namespaces.media.AsyncMedia.like>`."""

      await self.media.like(post_pk)

   async def unlike(self, post_pk: str) -> None:
      """Unlike a post. The same call as :meth:`AsyncMedia.unlike
      <dumpstagram.namespaces.media.AsyncMedia.unlike>`."""

      await self.media.unlike(post_pk)

   async def follow(self, user_id: str) -> None:
      """Follow an account. The same call as :meth:`AsyncSocial.follow
      <dumpstagram.namespaces.social.AsyncSocial.follow>`."""

      await self.social.follow(user_id)

   async def unfollow(self, user_id: str) -> None:
      """Unfollow an account. The same call as :meth:`AsyncSocial.unfollow
      <dumpstagram.namespaces.social.AsyncSocial.unfollow>`."""

      await self.social.unfollow(user_id)

   async def send_message(self, thread_fbid: str, text: str) -> SentMessage:
      """Send a text message into a direct thread. The same call as :meth:`AsyncDirect.send
      <dumpstagram.namespaces.direct.AsyncDirect.send>`."""

      return await self.direct.send(thread_fbid, text)

   async def unsend_message(self, thread_fbid: str, message_id: str) -> None:
      """Unsend the viewer's own message. The same call as :meth:`AsyncDirect.unsend
      <dumpstagram.namespaces.direct.AsyncDirect.unsend>`."""

      await self.direct.unsend(thread_fbid, message_id)

   async def comments(self, post_pk: str, *, after: str | None = None) -> Page[Comment]:
      """Read one page of a post's comments. The same call as :meth:`AsyncMedia.comments
      <dumpstagram.namespaces.media.AsyncMedia.comments>`."""

      return await self.media.comments(post_pk, after=after)

   async def comment(self, post_pk: str, text: str) -> Comment:
      """Comment ``text`` on a post. The same call as :meth:`AsyncMedia.comment
      <dumpstagram.namespaces.media.AsyncMedia.comment>`.

      A comment appends, so it is never sent again. After
      :class:`~dumpstagram.errors.OutcomeUnknown`, read the post's comments with
      :meth:`comments` and look for the viewer's own comment before sending again.
      """

      return await self.media.comment(post_pk, text)

   async def delete_comment(self, post_pk: str, comment_id: str) -> None:
      """Delete one comment on a post. The same call as :meth:`AsyncMedia.delete_comment
      <dumpstagram.namespaces.media.AsyncMedia.delete_comment>`."""

      await self.media.delete_comment(post_pk, comment_id)

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
               try:
                  await self._facebook.aclose()
               finally:
                  try:
                     await self._cdn.aclose()
                  finally:
                     await self._uploads.aclose()

   async def __aenter__(self) -> AsyncClient:
      return self

   async def __aexit__(
      self,
      exc_type: type[BaseException] | None,
      exc: BaseException | None,
      traceback: TracebackType | None,
   ) -> None:
      await self.aclose()


def cdn_transport_for(session: Session) -> HttpxTransport:
   """The pool media downloads go through: no cookie jar, and only https hosts of the CDN."""

   return HttpxTransport(
      proxy=session.proxy,
      allowed_host_family=CDN_HOST_FAMILY,
      max_connections=CDN_MAX_CONNECTIONS,
      cookieless=True,
   )


def upload_transport_for(session: Session) -> HttpxTransport:
   """The pool photo uploads go through: the account's cookies, and only the upload host.

   A separate pool because the cookie jar has no domain, so a transport pinned to one host is
   what keeps the account's cookies from reaching any other. Its sender shares the account's
   pacer, so an upload is spaced and budgeted with every other write.
   """

   return HttpxTransport(
      cookies=cookies_for(session),
      proxy=session.proxy,
      allowed_host=UPLOAD_HOST,
   )


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


def _rotation_doctor(
   client: AsyncClient, *, bundle_limit: int = DEFAULT_BUNDLE_LIMIT
) -> RotationDoctor:
   """The rotation canary over ``client``'s account, for the ``dumpsta doctor`` command.

   Not a capability, so not on the client: it reads the private query registry, which ADR-0007
   keeps off the public surface. It is assembled here because this is the one module outside
   ``_core`` that may build a transport. The canary shares the client's pacer and session and
   gets a cookieless transport of its own, pinned to the static bundle host, which it closes.
   """

   client._refuse_when_closed()

   bundles = HttpxTransport(
      proxy=client._session.proxy,
      allowed_host=STATIC_BUNDLE_HOST,
      cookieless=True,
   )

   return RotationDoctor(
      client._sender,
      bundles,
      client._session,
      user_agent=client._user_agent,
      bundle_limit=bundle_limit,
      owns_bundle_sender=True,
   )


def _rotation_doctor_plan(bundle_limit: int = DEFAULT_BUNDLE_LIMIT) -> DoctorPlan:
   """What a canary run would send, known without a session and without sending anything."""

   return doctor_plan(bundle_limit)
