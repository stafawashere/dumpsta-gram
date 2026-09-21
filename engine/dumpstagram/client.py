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
from types import TracebackType

from dumpstagram._core.loop_thread import _LoopThread
from dumpstagram.aio import AsyncClient
from dumpstagram.models import FeedItem, Message, Page, Profile
from dumpstagram.session import Session

__all__ = ["SyncClient"]


class SyncClient:
   """The blocking surface over one account.

   Holds one reference to the shared loop thread from construction until :meth:`close`. A
   client that is never closed keeps that thread alive for the lifetime of the process, which
   is why both a context manager and an explicit `close` exist.
   """

   def __init__(self, session: Session, *, user_agent: str | None = None) -> None:
      self._loop = _LoopThread.acquire()

      try:
         self._impl = AsyncClient(session, user_agent=user_agent)
      except BaseException:
         self._loop.release()

         raise

      self._closed = False

   @classmethod
   def from_session_file(
      cls, path: str | os.PathLike[str], *, user_agent: str | None = None
   ) -> SyncClient:
      """Load a saved session from ``path`` and build a client around it.

      The file is read before the loop thread is acquired, so a refused file leaves no thread
      running and nothing to release.
      """

      return cls(Session.load(path), user_agent=user_agent)

   @property
   def session(self) -> Session:
      """The session this client was built with, which the caller still owns."""

      return self._impl.session

   @property
   def user_agent(self) -> str:
      """The user-agent string every request from this client carries."""

      return self._impl.user_agent

   @property
   def closed(self) -> bool:
      """Whether :meth:`close` has run."""

      return self._closed

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
      and the same result, run on the shared loop thread. Two live requests, because the
      upstream's profile query takes an account id rather than a username.
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
