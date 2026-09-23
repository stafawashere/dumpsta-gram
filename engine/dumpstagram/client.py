"""``SyncClient``, the blocking public surface.

There is one implementation of every capability and it is asynchronous, per ADR-0001. This is
a facade in front of it, not a second implementation, and it adds no behavior of its own
beyond crossing the loop thread.

Two properties of that crossing are load-bearing. The loop thread is the shared refcounted
singleton, so ten clients in a process cost one thread. And work is handed to it with
``asyncio.run_coroutine_threadsafe``, never with ``asyncio.run``, which would build and tear
down a loop per call and discard the connection pool with it.

Exceptions cross back intact, per ADR-0012. The object a coroutine raised is the object a
blocking caller catches, with a note naming the seam, and ``asyncio.CancelledError`` becoming
:class:`~dumpstagram.errors.OperationCancelled` is the only translation.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Coroutine
from types import TracebackType
from typing import Any

from dumpstagram._core.loop_thread import _LoopThread
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY, Behavior
from dumpstagram.listener import EventListener
from dumpstagram.models import (
   Comment,
   Event,
   FeedItem,
   Message,
   Note,
   NoteAudience,
   Page,
   PostDetail,
   Profile,
   SentMessage,
)
from dumpstagram.session import Session

__all__ = ["SyncClient"]


class SyncClient:
   """The blocking surface over one account.

   Holds one reference to the shared loop thread from construction until :meth:`close`. A
   client that is never closed keeps that thread alive for the lifetime of the process, which
   is why both a context manager and an explicit `close` exist.
   """

   def __init__(
      self,
      session: Session,
      *,
      user_agent: str | None = None,
      behavior: Behavior = PARITY,
   ) -> None:
      self._loop = _LoopThread.acquire()

      try:
         self._impl = AsyncClient(session, user_agent=user_agent, behavior=behavior)
      except BaseException:
         self._loop.release()

         raise

      self._closed = False

   @classmethod
   def from_session_file(
      cls,
      path: str | os.PathLike[str],
      *,
      user_agent: str | None = None,
      behavior: Behavior = PARITY,
   ) -> SyncClient:
      """Load a saved session from ``path`` and build a client around it.

      The file is read before the loop thread is acquired, so a refused file leaves no thread
      running and nothing to release.
      """

      return cls(Session.load(path), user_agent=user_agent, behavior=behavior)

   def with_behavior(self, behavior: Behavior) -> SyncClient:
      """Another client over the same account that differs only in ``behavior``.

      The blocking form of :meth:`~dumpstagram.aio.AsyncClient.with_behavior`. It shares this
      client's session, pool and pacer, and holds its own reference to the loop thread until
      it is closed. Closing it does not close the pool, and closing this client stops both.
      """

      scoped_impl = self._impl.with_behavior(behavior)

      scoped = object.__new__(SyncClient)
      scoped._loop = _LoopThread.acquire()
      scoped._impl = scoped_impl
      scoped._closed = False

      return scoped

   @property
   def session(self) -> Session:
      """The session this client was built with, which the caller still owns."""

      return self._impl.session

   @property
   def user_agent(self) -> str:
      """The user-agent string every request from this client carries."""

      return self._impl.user_agent

   @property
   def behavior(self) -> Behavior:
      """The behavior configuration this client's traffic follows."""

      return self._impl.behavior

   @property
   def closed(self) -> bool:
      """Whether :meth:`close` has run, on this client or on the one that owns its pool."""

      return self._closed or self._impl.closed

   def thread_messages(
      self,
      thread_fbid: str,
      *,
      after: str | None = None,
      newer_than_message_id: str | None = None,
   ) -> Page[Message]:
      """Read one page of one direct thread. Blocks until it has one.

      The same call as :meth:`~dumpstagram.aio.AsyncClient.thread_messages`, with the same
      arguments and the same result, run on the shared loop thread. Exceptions cross back as
      themselves, with a note naming this method.
      """

      return self._loop.run(
         self._impl.thread_messages(
            thread_fbid,
            after=after,
            newer_than_message_id=newer_than_message_id,
         ),
         operation="SyncClient.thread_messages",
      )

   def profile(self, username: str) -> Profile:
      """Read one account's profile by username. Blocks until it has one.

      The same call as :meth:`~dumpstagram.aio.AsyncClient.profile`, with the same arguments
      and the same result, run on the shared loop thread. Seven live requests in one action
      under the default behavior, two under :attr:`~dumpstagram.behavior.ProfileRoute.QUERIES`.
      """

      return self._loop.run(
         self._impl.profile(username),
         operation="SyncClient.profile",
      )

   def profile_by_id(self, user_id: str) -> Profile:
      """Read one account's profile by its numeric account id. Blocks until it has one.

      The same call as :meth:`~dumpstagram.aio.AsyncClient.profile_by_id`, run on the shared
      loop thread. One live request.
      """

      return self._loop.run(
         self._impl.profile_by_id(user_id),
         operation="SyncClient.profile_by_id",
      )

   def feed(self, *, after: str | None = None) -> Page[FeedItem]:
      """Read one page of the home timeline. Blocks until it has one.

      The same call as :meth:`~dumpstagram.aio.AsyncClient.feed`, run on the shared loop
      thread. One live request.
      """

      return self._loop.run(
         self._impl.feed(after=after),
         operation="SyncClient.feed",
      )

   def notes(self) -> tuple[Note, ...]:
      """Read the notes tray on the direct inbox. Blocks until it has it.

      The same call as :meth:`~dumpstagram.aio.AsyncClient.notes`, run on the shared loop
      thread. One live request.
      """

      return self._loop.run(
         self._impl.notes(),
         operation="SyncClient.notes",
      )

   def set_note(self, text: str, *, audience: NoteAudience = NoteAudience.CLOSE_FRIENDS) -> Note:
      """Set the viewer's note. Blocks until the write is answered.

      The same call as :meth:`~dumpstagram.aio.AsyncClient.set_note`, with the same audience
      default, run on the shared loop thread. One write, sent once, never retried. It replaces
      any note already up.
      """

      return self._loop.run(
         self._impl.set_note(text, audience=audience),
         operation="SyncClient.set_note",
      )

   def delete_note(self, note_id: str) -> None:
      """Delete the viewer's note. Blocks until the write is answered.

      The same call as :meth:`~dumpstagram.aio.AsyncClient.delete_note`, run on the shared
      loop thread. One write, sent once, never retried.
      """

      return self._loop.run(
         self._impl.delete_note(note_id),
         operation="SyncClient.delete_note",
      )

   def post(self, code: str) -> PostDetail:
      """Read one post by its shortcode. Blocks until it has it.

      The same call as :meth:`~dumpstagram.aio.AsyncClient.post`, run on the shared loop
      thread. One live request.
      """

      return self._loop.run(
         self._impl.post(code),
         operation="SyncClient.post",
      )

   def like(self, post_pk: str) -> None:
      """Like the post whose media ``pk`` is ``post_pk``. Blocks until the write is answered.

      The same call as :meth:`~dumpstagram.aio.AsyncClient.like`, run on the shared loop
      thread. One write, sent once, never retried.
      """

      return self._loop.run(
         self._impl.like(post_pk),
         operation="SyncClient.like",
      )

   def unlike(self, post_pk: str) -> None:
      """Unlike the post whose media ``pk`` is ``post_pk``. Blocks until the write is answered.

      The same call as :meth:`~dumpstagram.aio.AsyncClient.unlike`, run on the shared loop
      thread. One write, sent once, never retried.
      """

      return self._loop.run(
         self._impl.unlike(post_pk),
         operation="SyncClient.unlike",
      )

   def follow(self, user_id: str) -> None:
      """Follow the account whose numeric id is ``user_id``. Blocks until the write is answered.

      The same call as :meth:`~dumpstagram.aio.AsyncClient.follow`, run on the shared loop
      thread. One write, sent once, never retried.
      """

      return self._loop.run(
         self._impl.follow(user_id),
         operation="SyncClient.follow",
      )

   def unfollow(self, user_id: str) -> None:
      """Unfollow the account whose numeric id is ``user_id``. Blocks until the write is
      answered.

      The same call as :meth:`~dumpstagram.aio.AsyncClient.unfollow`, run on the shared loop
      thread. One write, sent once, never retried.
      """

      return self._loop.run(
         self._impl.unfollow(user_id),
         operation="SyncClient.unfollow",
      )

   def comments(self, post_pk: str, *, after: str | None = None) -> Page[Comment]:
      """Read one page of a post's comments. Blocks until it has it.

      The same call as :meth:`~dumpstagram.aio.AsyncClient.comments`, run on the shared loop
      thread. One live request.
      """

      return self._loop.run(
         self._impl.comments(post_pk, after=after),
         operation="SyncClient.comments",
      )

   def send_message(self, thread_fbid: str, text: str) -> SentMessage:
      """Send a text message into a direct thread. Blocks until the write is answered.

      The same call as :meth:`~dumpstagram.aio.AsyncClient.send_message`, run on the shared
      loop thread. One write, sent once, never retried. After
      :class:`~dumpstagram.errors.OutcomeUnknown`, read :meth:`thread_messages` before sending
      again, because a second send is a second message the recipient sees.
      """

      return self._loop.run(
         self._impl.send_message(thread_fbid, text),
         operation="SyncClient.send_message",
      )

   def unsend_message(self, thread_fbid: str, message_id: str) -> None:
      """Unsend the viewer's own message. Blocks until the write is answered.

      The same call as :meth:`~dumpstagram.aio.AsyncClient.unsend_message`, run on the shared
      loop thread. One thread open, then one write, sent once, never retried.
      """

      return self._loop.run(
         self._impl.unsend_message(thread_fbid, message_id),
         operation="SyncClient.unsend_message",
      )

   def comment(self, post_pk: str, text: str) -> Comment:
      """Comment on a post. Blocks until the write is answered.

      The same call as :meth:`~dumpstagram.aio.AsyncClient.comment`, run on the shared loop
      thread. One write, sent once, never retried. After
      :class:`~dumpstagram.errors.OutcomeUnknown`, read :meth:`comments` before sending again,
      because a second send is a second comment.
      """

      return self._loop.run(
         self._impl.comment(post_pk, text),
         operation="SyncClient.comment",
      )

   def delete_comment(self, post_pk: str, comment_id: str) -> None:
      """Delete one comment on a post. Blocks until the write is answered.

      The same call as :meth:`~dumpstagram.aio.AsyncClient.delete_comment`, run on the shared
      loop thread. One write, sent once, never retried.
      """

      return self._loop.run(
         self._impl.delete_comment(post_pk, comment_id),
         operation="SyncClient.delete_comment",
      )

   def events(
      self,
      *,
      since: str | None = None,
      on_event: Callable[[Event], None] | None = None,
   ) -> EventListener:
      """A listener for every new direct message on this account, not yet started.

      The blocking form of :meth:`~dumpstagram.aio.AsyncClient.events`, with the same ``since``
      and the same events, polled on the shared loop thread from :meth:`EventListener.start
      <dumpstagram.listener.EventListener.start>` until :meth:`EventListener.stop
      <dumpstagram.listener.EventListener.stop>`. Without ``on_event`` the consumer takes
      events with :meth:`~dumpstagram.listener.EventListener.drain` or
      :meth:`~dumpstagram.listener.EventListener.wait_for_events`. With it, the listener calls
      ``on_event`` once per event on its own delivery thread, and nothing goes to the buffer.

      A failure that ends the listener arrives as a final
      :class:`~dumpstagram.models.ListenerStopped` carrying the exception the poll raised, with
      a note naming the seam, where the async iterator would raise it.
      """

      if self.closed:
         raise RuntimeError("this client is closed, so its connection pool is gone")

      async_client = self._impl

      def poll_for_events(emit: Callable[[Event], None]) -> Coroutine[Any, Any, None]:
         return async_client._poll_for_events(emit, since=since)

      return EventListener._over(poll_for_events, on_event=on_event)

   def close(self) -> None:
      """Close the connection pool and drop this client's hold on the loop thread.

      Idempotent. The pool is closed on the loop thread that opened it, and the reference is
      released even when that close fails, because leaking a thread on top of a failed close
      turns one problem into two.
      """

      if self._closed:
         return

      self._closed = True

      try:
         self._loop.run(self._impl.aclose(), operation="SyncClient.close")
      finally:
         self._loop.release()

   def __enter__(self) -> SyncClient:
      return self

   def __exit__(
      self,
      exc_type: type[BaseException] | None,
      exc: BaseException | None,
      traceback: TracebackType | None,
   ) -> None:
      self.close()
