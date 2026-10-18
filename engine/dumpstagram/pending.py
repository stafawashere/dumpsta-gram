"""Start one call of a :class:`~dumpstagram.client.SyncClient` without blocking on it.

Every blocking method holds its calling thread until the engine answers, and a write waits out
the write spacing first, about 30 s under the default behavior. A host that funnels every call
through one thread or one actor, as an embedding app must when one interpreter serves several
accounts, then stalls every account behind that one write. :func:`submit` hands the call to the
loop thread and returns a :class:`PendingCall` at once, which the host checks with
:meth:`PendingCall.done` and collects with :meth:`PendingCall.result` when it is done.

It changes nothing about how the call is made. The call runs on the same loop, through the same
client, its pacer and its write path, so a write is still spaced, budgeted and sent once, and
calls on one account still depart one at a time in the order the pacer admits them. Measured on
2026-10-18 with canned answers: thirteen calls started together on one client, twelve thread
reads and one send, each got its own answer, never more than one request was in flight, and the
send departed once; twelve threads blocking on one ``SyncClient`` at once behaved the same.
What concurrency costs is a duplicated page load: calls that start together on a session with no
page token, or that meet a stale token together, each load the bootstrap document, where calls
in series would load it once. Make one call and collect it before submitting several at once.

Exceptions follow the blocking surface's rule, ADR-0012: :meth:`PendingCall.result` raises the
object the call raised, with the seam note attached once, and a cancelled call raises
:class:`~dumpstagram.errors.OperationCancelled`.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
from typing import Any

from dumpstagram._core.loop_thread import seam_note
from dumpstagram.client import SyncClient
from dumpstagram.errors import OperationCancelled

__all__ = ["PendingCall", "submit"]


class PendingCall[T]:
   """One call started by :func:`submit`, running on the loop thread."""

   _future: concurrent.futures.Future[T]
   _operation: str

   def __init__(self) -> None:
      raise TypeError(
         "a PendingCall comes from dumpstagram.pending.submit, it is not built directly"
      )

   @classmethod
   def _of(cls, future: concurrent.futures.Future[T], operation: str) -> PendingCall[T]:
      pending: PendingCall[T] = object.__new__(cls)
      pending._future = future
      pending._operation = operation

      return pending

   @property
   def operation(self) -> str:
      """The dotted name the call was submitted under, such as ``direct.send``."""

      return self._operation

   def done(self) -> bool:
      """Whether the call has finished, by answering, raising or being cancelled. Never blocks."""

      return self._future.done()

   def result(self, timeout: float | None = None) -> T:
      """The call's answer, waiting up to ``timeout`` seconds for it, or forever with ``None``.

      Raises what the call raised, and :class:`TimeoutError` when ``timeout`` passes first, which
      leaves the call running. Called once :meth:`done` is true, it returns without waiting.
      """

      try:
         return self._future.result(timeout)
      except (asyncio.CancelledError, concurrent.futures.CancelledError) as cancelled:
         raise OperationCancelled(f"{self._operation} was cancelled") from cancelled
      except TimeoutError:
         raise
      except BaseException as failure:
         note = seam_note(self._operation)

         if note not in getattr(failure, "__notes__", ()):
            failure.add_note(note)

         raise

   def cancel(self) -> bool:
      """Cancel the call if it has not finished. A write already sent is not taken back, and its
      outcome stays unknown. Returns whether the call was cancelled."""

      return self._future.cancel()


def submit(client: SyncClient, operation: str, /, *args: Any, **kwargs: Any) -> PendingCall[Any]:
   """Start ``operation`` on ``client`` with ``args`` and ``kwargs`` and return without waiting.

   ``operation`` names a method of the client by its dotted path on the awaitable surface, the
   same path the blocking surface uses: ``"direct.send"``, ``"profiles.by_username"``,
   ``"thread_messages"``. Only a method that answers once can be submitted. A private name, an
   unknown name, a property, an ``iter_`` walk and the listener raise :class:`ValueError` here,
   before anything starts, and so does an argument the method's signature cannot take, as
   :class:`TypeError`. Everything the call itself checks raises from :meth:`PendingCall.result`.
   """

   target: Any = client._impl

   for segment in operation.split("."):
      is_private = not segment or segment.startswith("_")

      if is_private:
         raise ValueError(f"{operation!r} is not a public method of the client")

      try:
         target = getattr(target, segment)
      except AttributeError:
         raise ValueError(f"{operation!r} is not a method of the client") from None

   answers_once = inspect.iscoroutinefunction(target)

   if not answers_once:
      raise ValueError(f"{operation!r} does not answer once, so it cannot be submitted")

   return PendingCall._of(client._loop.start(target(*args, **kwargs)), operation)
