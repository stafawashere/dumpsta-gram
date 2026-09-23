"""The bounded buffer events wait in until a consumer takes them.

Events are put on the engine's loop thread and taken on whatever thread the consumer runs,
which for the Swift app is its Python serial queue. So every operation holds one lock, and
nothing here ever calls consumer code, per ``docs/bridge/threading-and-gil.md``.

The bound is 1000 events, HYPOTHESIS for the number, ruling 9 in ``engine/docs/build-plan.md``.
When it is reached the oldest waiting event is dropped, and the next take starts with an
:class:`~dumpstagram.models.EventsDropped` carrying how many went, so a consumer can tell a gap
from silence. Dropping the oldest keeps the newest, which a polling listener cannot fetch again
as cheaply as the old ones.

A take is at most once: an event handed out is gone from here.
"""

from __future__ import annotations

import threading
from collections import deque

from dumpstagram.models import Event, EventsDropped

__all__ = ["EVENT_BUFFER_CAPACITY", "EventBuffer"]

EVENT_BUFFER_CAPACITY = 1000


class EventBuffer:
   """Events between the loop and a consumer, bounded, safe from any thread.

   Thread safe, task safe and not loop bound: it holds no asyncio object. :meth:`finish` closes
   it, after which puts are ignored and a take that finds nothing returns at once.
   """

   def __init__(self, capacity: int = EVENT_BUFFER_CAPACITY) -> None:
      if capacity < 1:
         raise ValueError("an event buffer holds at least one event")

      self._capacity = capacity
      self._lock = threading.Lock()
      self._changed = threading.Condition(self._lock)

      self._events: deque[Event] = deque()
      self._dropped = 0
      self._final: Event | None = None
      self._finished = False

   @property
   def finished(self) -> bool:
      with self._lock:
         return self._finished

   def put(self, event: Event) -> None:
      """Add one event, dropping the oldest waiting one when the buffer is full."""

      with self._lock:
         if self._finished:
            return

         is_full = len(self._events) >= self._capacity
         if is_full:
            self._events.popleft()
            self._dropped += 1

         self._events.append(event)
         self._changed.notify_all()

   def finish(self, final: Event | None = None) -> None:
      """Close the buffer, with ``final`` as the last event a take will ever return.

      ``final`` is kept outside the bound, so a full buffer cannot drop it.
      """

      with self._lock:
         if self._finished:
            return

         self._finished = True
         self._final = final
         self._changed.notify_all()

   def drain(self) -> list[Event]:
      """Take every waiting event, without waiting for one."""

      with self._lock:
         return self._take_all()

   def wait(self, timeout: float | None) -> list[Event]:
      """Take every waiting event, first waiting up to ``timeout`` seconds for one to arrive.

      Returns early, and possibly empty, once the buffer is finished.
      """

      with self._lock:
         self._changed.wait_for(self._has_something_or_is_finished, timeout)

         return self._take_all()

   def _has_something_or_is_finished(self) -> bool:
      has_events = bool(self._events) or self._dropped > 0
      has_final = self._final is not None

      return has_events or has_final or self._finished

   def _take_all(self) -> list[Event]:
      taken: list[Event] = []

      if self._dropped:
         taken.append(EventsDropped(count=self._dropped))
         self._dropped = 0

      taken.extend(self._events)
      self._events.clear()

      if self._final is not None:
         taken.append(self._final)
         self._final = None

      return taken
