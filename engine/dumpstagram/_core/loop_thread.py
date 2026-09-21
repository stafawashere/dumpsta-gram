"""The shared asyncio loop thread the sync facade blocks on.

One implementation of every capability is async, per ADR-0001, and the blocking surface is a
facade in front of it. That facade needs a loop which outlives a single call, because
``asyncio.run`` per call would build and tear down the connection pool every time and discard
loop-bound state with it. ``asyncio.run`` therefore appears nowhere in this library.

The thread is a refcounted shared singleton rather than one thread per client, per ADR-0004.
One loop thread per account is acceptable at one account and wasteful at ten, and retrofitting
the sharing later means changing every lifecycle in the library at once. Holding that refcount
is the one piece of class-level mutable state the engine keeps, and it is deliberate.

Exceptions cross the seam intact, per ADR-0012. :meth:`_LoopThread.run` re-raises the object
the coroutine raised, attaches a note naming the facade method and the operation so the joined
traceback shows where the two stacks meet, and translates ``asyncio.CancelledError`` into
:class:`~dumpstagram.errors.OperationCancelled` because a ``BaseException`` escaping a blocking
call would slip past a caller's ``except Exception``. That is the only translation performed.

Nothing that fails on this loop is silent. Unhandled task errors and unretrieved exceptions go
through :func:`log_loop_exception` into ``logging.getLogger("dumpstagram")``, formatted and
redacted here rather than handed to the host as ``exc_info``, because the host's formatter is
not this library's to choose.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import traceback
from collections.abc import Coroutine
from typing import Any, ClassVar

from dumpstagram._core.redaction import redact
from dumpstagram.errors import OperationCancelled

__all__ = [
   "LOGGER_NAME",
   "THREAD_NAME",
   "log_loop_exception",
]

LOGGER_NAME = "dumpstagram"
THREAD_NAME = "dumpstagram-loop"

_logger = logging.getLogger(LOGGER_NAME)


def log_loop_exception(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
   """Route an unhandled loop error into the library's logger, redacted.

   The traceback is formatted and redacted here instead of being passed as ``exc_info``. A
   host that attached a plain formatter would otherwise render the untouched traceback, and a
   traceback is the one place a cookie reaches a log with nobody having written a log
   statement.
   """

   message = context.get("message", "unhandled error on the dumpstagram loop")
   failure = context.get("exception")

   if failure is None:
      _logger.error("%s", redact(str(message)))

      return

   formatted = "".join(traceback.format_exception(type(failure), failure, failure.__traceback__))

   _logger.error("%s\n%s", redact(str(message)), redact(formatted))


class _LoopThread:
   """A daemon thread running one asyncio loop, shared by every client in the process.

   Acquire and release are paired. The thread starts on the first acquire and stops on the
   release that drops the count to zero, which is also the only point at which pending tasks
   are cancelled. A leaked reference keeps the thread alive for the lifetime of the process.
   """

   _shared: ClassVar[_LoopThread | None] = None
   _guard: ClassVar[threading.Lock] = threading.Lock()

   def __init__(self) -> None:
      self._loop: asyncio.AbstractEventLoop | None = None
      self._thread: threading.Thread | None = None
      self._references = 0

   @classmethod
   def acquire(cls) -> _LoopThread:
      """Return the shared loop thread, starting it if this is the first caller."""

      with cls._guard:
         shared = cls._shared

         if shared is None:
            shared = cls()
            shared._start()
            cls._shared = shared

         shared._references += 1

         return shared

   def release(self) -> None:
      """Drop one reference, stopping the thread when the last one goes.

      Releasing more times than acquired is a defect in the caller's lifecycle rather than a
      condition to absorb, so it raises.
      """

      with type(self)._guard:
         if self._references == 0:
            raise RuntimeError("the loop thread was released more times than it was acquired")

         self._references -= 1

         if self._references > 0:
            return

         type(self)._shared = None
         thread = self._thread
         loop = self._loop
         self._thread = None
         self._loop = None

      if loop is None or thread is None:
         return

      loop.call_soon_threadsafe(loop.stop)
      thread.join()

   @property
   def references(self) -> int:
      """How many clients currently hold this thread."""

      return self._references

   @property
   def running(self) -> bool:
      """Whether the thread is alive and its loop is accepting work."""

      return self._thread is not None and self._thread.is_alive()

   def run[T](self, coroutine: Coroutine[Any, Any, T], *, operation: str) -> T:
      """Run ``coroutine`` on the loop thread and block until it finishes.

      ``operation`` names the facade method for the seam note. The returned exception is the
      object the coroutine raised, with the note attached, and never a wrapper around it.
      """

      loop = self._loop

      if loop is None:
         coroutine.close()

         raise RuntimeError("the loop thread is not running, so it cannot accept work")

      future = asyncio.run_coroutine_threadsafe(coroutine, loop)

      try:
         return future.result()
      except (asyncio.CancelledError, concurrent.futures.CancelledError) as cancelled:
         raise OperationCancelled(f"{operation} was cancelled") from cancelled
      except BaseException as failure:
         failure.add_note(seam_note(operation))

         raise

   def _start(self) -> None:
      ready = threading.Event()

      self._thread = threading.Thread(
         target=self._serve,
         args=(ready,),
         name=THREAD_NAME,
         daemon=True,
      )
      self._thread.start()

      ready.wait()

   def _serve(self, ready: threading.Event) -> None:
      loop = asyncio.new_event_loop()
      asyncio.set_event_loop(loop)
      loop.set_exception_handler(log_loop_exception)

      self._loop = loop
      ready.set()

      try:
         loop.run_forever()
      finally:
         _drain(loop)
         asyncio.set_event_loop(None)
         loop.close()


def seam_note(operation: str) -> str:
   """The note attached to every exception that crosses back out of the loop thread."""

   return (
      f"raised on the dumpstagram loop thread and re-raised by the calling thread, "
      f"operation: {operation}"
   )


def _drain(loop: asyncio.AbstractEventLoop) -> None:
   pending = [task for task in asyncio.all_tasks(loop) if not task.done()]

   for task in pending:
      task.cancel()

   if pending:
      loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))

   loop.run_until_complete(loop.shutdown_asyncgens())
