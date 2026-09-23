"""``EventListener``, what :meth:`SyncClient.events <dumpstagram.SyncClient.events>` returns.

The blocking side of ``events()``. Its polling runs on the shared loop thread, like every other
capability, and events wait in a bounded buffer until the consumer takes them, per ADR-0006.
The consumer takes them in one of two ways and never both.

Without a handler the consumer drains: :meth:`EventListener.drain` returns at once and
:meth:`EventListener.wait_for_events` parks until something arrives. Both are safe from any
thread, and this is the form the Swift app uses, from its Python serial queue.

With ``on_event`` the listener calls the handler itself, on a delivery thread of its own that
is neither the loop thread nor the caller's, and nothing reaches the buffer the consumer would
drain. The handler is Python calling Python. It is never a foreign callback across the bridge.

A failure that ends the listener arrives in band, as a final
:class:`~dumpstagram.models.ListenerStopped` carrying the original exception, so a consumer that
only drains still learns why events stopped.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import traceback
from collections.abc import Callable, Coroutine
from types import TracebackType
from typing import Any

from dumpstagram._core.loop_thread import _LoopThread, seam_note
from dumpstagram._core.realtime.buffer import EventBuffer
from dumpstagram._core.redaction import redact
from dumpstagram.models import Event, ListenerStopped

__all__ = ["EventListener"]

DELIVERY_THREAD_NAME = "dumpstagram-events"

type _PumpFactory = Callable[[Callable[[Event], None]], Coroutine[Any, Any, None]]

_logger = logging.getLogger("dumpstagram")


class EventListener:
   """One run of new-message events for one account, started once and stopped once.

   Built by :meth:`SyncClient.events <dumpstagram.SyncClient.events>`, never directly. Nothing is
   sent until :meth:`start`. :meth:`stop` ends the polling, releases the loop thread and joins
   the delivery thread, and it is idempotent. A listener that ended on a failure has stopped
   polling already and still wants :meth:`stop` to let go of the loop thread. Used as a context
   manager it starts on entry and stops on exit.

   Events already buffered stay drainable after :meth:`stop`. A stopped listener cannot be
   started again, and the client's ``events`` builds a fresh one, whose ``since`` is the last
   message id the consumer handled.

   Thread safe: :meth:`drain`, :meth:`wait_for_events`, :meth:`start` and :meth:`stop` may be
   called from any thread except the library's own loop thread.
   """

   _pump: _PumpFactory
   _on_event: Callable[[Event], None] | None
   _buffer: EventBuffer
   _state_lock: threading.Lock
   _started: bool
   _stopped: bool
   _loop: _LoopThread | None
   _task: asyncio.Task[None] | None
   _delivery: threading.Thread | None

   def __init__(self) -> None:
      raise TypeError("an EventListener comes from SyncClient.events, it is not built directly")

   @classmethod
   def _over(
      cls,
      pump: _PumpFactory,
      *,
      on_event: Callable[[Event], None] | None,
   ) -> EventListener:
      listener = object.__new__(cls)
      listener._pump = pump
      listener._on_event = on_event
      listener._buffer = EventBuffer()
      listener._state_lock = threading.Lock()
      listener._started = False
      listener._stopped = False
      listener._loop = None
      listener._task = None
      listener._delivery = None

      return listener

   def start(self) -> None:
      """Start polling on the loop thread, and the delivery thread when there is a handler.

      Returns at once. Raises :class:`RuntimeError` on a listener started before.
      """

      with self._state_lock:
         if self._started:
            raise RuntimeError("an EventListener starts once, build another with events()")

         self._started = True

      self._loop = _LoopThread.acquire()

      try:
         if self._on_event is not None:
            self._delivery = threading.Thread(
               target=self._deliver,
               args=(self._on_event,),
               name=DELIVERY_THREAD_NAME,
               daemon=True,
            )
            self._delivery.start()

         self._loop.run(self._spawn(), operation="EventListener.start")
      except BaseException:
         self._buffer.finish()
         self._loop.release()
         self._loop = None

         raise

   def stop(self) -> None:
      """Stop polling and release what :meth:`start` took. Idempotent, and safe before start."""

      with self._state_lock:
         if self._stopped:
            return

         self._stopped = True
         self._started = True

      loop = self._loop

      try:
         if loop is not None:
            loop.run(self._halt(), operation="EventListener.stop")
      finally:
         self._buffer.finish()

         delivery = self._delivery
         is_the_delivery_thread = delivery is threading.current_thread()

         if delivery is not None and not is_the_delivery_thread:
            delivery.join()

         if loop is not None:
            self._loop = None
            loop.release()

   def drain(self) -> list[Event]:
      """Pop every pending event, oldest first, without waiting. Safe from any thread.

      Raises :class:`RuntimeError` on a listener built with ``on_event``, whose events go to the
      handler instead.
      """

      self._refuse_with_a_handler()

      return self._buffer.drain()

   def wait_for_events(self, timeout: float | None) -> list[Event]:
      """Pop every pending event, first waiting up to ``timeout`` seconds for one to arrive.

      Returns an empty list when the time runs out, or at once when the listener has stopped
      and nothing is left. ``None`` waits for as long as it takes. Safe from any thread, and it
      parks only the calling one. Raises :class:`RuntimeError` on a listener built with
      ``on_event``.
      """

      self._refuse_with_a_handler()

      return self._buffer.wait(timeout)

   def __enter__(self) -> EventListener:
      self.start()

      return self

   def __exit__(
      self,
      exc_type: type[BaseException] | None,
      exc: BaseException | None,
      traceback: TracebackType | None,
   ) -> None:
      self.stop()

   def _refuse_with_a_handler(self) -> None:
      if self._on_event is not None:
         raise RuntimeError("this listener hands its events to on_event, there is nothing to drain")

   async def _spawn(self) -> None:
      self._task = asyncio.get_running_loop().create_task(self._run())

   async def _halt(self) -> None:
      task = self._task

      if task is None:
         return

      task.cancel()
      await asyncio.wait([task])

   async def _run(self) -> None:
      try:
         await self._pump(self._buffer.put)
      except Exception as failure:
         failure.add_note(seam_note("EventListener"))
         self._buffer.finish(ListenerStopped(error=failure))

   def _deliver(self, handler: Callable[[Event], None]) -> None:
      while True:
         batch = self._buffer.wait(None)

         if not batch and self._buffer.finished:
            return

         for event in batch:
            call_handler(handler, event)


def call_handler(handler: Callable[[Event], None], event: Event) -> None:
   """Run the consumer's handler, logging what it raises and carrying on with the next event.

   The handler is the consumer's code, so its failure is the consumer's to fix, and stopping
   the listener for it would lose every event after it. It is logged rather than swallowed,
   redacted like every traceback this library writes.
   """

   try:
      handler(event)
   except Exception as failure:
      formatted = "".join(traceback.format_exception(type(failure), failure, failure.__traceback__))

      _logger.error("an on_event handler raised, delivery carries on\n%s", redact(formatted))
