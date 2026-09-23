"""Turns polls into events: order, deduplication, pacing and what ends a listener.

Both public surfaces run the same pump. It asks an :class:`EventSource` for the messages it can
see, emits each one it has not emitted before as a :class:`~dumpstagram.models.NewMessage`,
waits the behavior's poll interval, and asks again. What the source reads and how is its own
business, so the polling transport of Step 23 and a push transport later plug in here without
the pump or the surface changing.

A poll is a read, so it runs under ``run_with_retries`` and its backoff holds the whole account.
A source makes one attempt per poll and never retries on its own, because retry lives in one
layer. A failure in :data:`SURVIVABLE` that outlasts its retries costs that poll and nothing
more. Everything else ends the pump by propagating, and
:class:`~dumpstagram.errors.CheckpointRequired` is never polled through, since polling through a
challenge escalates it.

Every request a source sends goes through the client's paced sender, which is handed to it in
:class:`SourceContext`. There is no other sender for it to reach.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import NoReturn, Protocol

from dumpstagram._core.pacer import Pacer, run_with_retries
from dumpstagram._core.requesting import PacedSender
from dumpstagram.behavior import Behavior
from dumpstagram.errors import RateLimited, TransportFailure
from dumpstagram.models import Event, Message, NewMessage
from dumpstagram.session import Session

__all__ = [
   "SEEN_ID_MEMORY",
   "SURVIVABLE",
   "EventSource",
   "NoTransportYet",
   "SeenIds",
   "SourceContext",
   "SourceFactory",
   "in_delivery_order",
   "no_transport_yet",
   "pump_events",
]

SURVIVABLE: tuple[type[Exception], ...] = (TransportFailure, RateLimited)
"""What a listener polls through once the retries of one poll are spent."""

SEEN_ID_MEMORY = 10_000
"""How many message ids a listener remembers having emitted. A source returns only recent
messages, so an id old enough to be forgotten is not returned again."""

_logger = logging.getLogger("dumpstagram")


class EventSource(Protocol):
   """Whatever tells the pump which messages exist now.

   ``poll`` returns the messages the source can see, in any order, and may return one it
   returned before. It makes one attempt, sends only through the sender in its
   :class:`SourceContext`, and raises the library's own errors.
   """

   async def poll(self) -> Sequence[Message]: ...


@dataclass(frozen=True)
class SourceContext:
   """Everything a source is built from, all of it the client's own.

   ``since`` is the message id the caller passed to ``events``, or None.
   """

   sender: PacedSender
   session: Session
   behavior: Behavior
   user_agent: str
   since: str | None


type SourceFactory = Callable[[SourceContext], EventSource]


class NoTransportYet:
   """The source a client has until the polling transport exists."""

   async def poll(self) -> Sequence[Message]:
      raise NotImplementedError("events() has no transport yet, polling arrives in Step 23")


def no_transport_yet(context: SourceContext) -> EventSource:
   return NoTransportYet()


class SeenIds:
   """The ids already emitted, forgetting the oldest beyond ``capacity``."""

   def __init__(self, capacity: int = SEEN_ID_MEMORY) -> None:
      self._capacity = capacity
      self._order: deque[str] = deque()
      self._members: set[str] = set()

   def __len__(self) -> int:
      return len(self._members)

   def add(self, message_id: str) -> bool:
      """Remember ``message_id`` and say whether it was new."""

      if message_id in self._members:
         return False

      self._order.append(message_id)
      self._members.add(message_id)

      while len(self._order) > self._capacity:
         self._members.discard(self._order.popleft())

      return True


def in_delivery_order(messages: Sequence[Message]) -> list[Message]:
   """Oldest first by ``sent_at``, so every thread's messages ascend.

   A source reads the way the upstream lists things, newest thread first and newest message
   first, which is the order a consumer must not see.
   """

   return sorted(messages, key=lambda message: message.sent_at)


async def pump_events(
   source: EventSource,
   emit: Callable[[Event], None],
   *,
   pacer: Pacer,
   interval_seconds: float,
   since: str | None = None,
) -> NoReturn:
   """Poll ``source`` for as long as it answers, emitting every message once.

   ``emit`` is called on the loop thread and must not block. ``since`` counts as emitted
   already, so the message a restarted consumer last saw is not delivered again. Returns only
   by raising, and cancellation is how it is stopped.
   """

   seen = SeenIds()

   if since is not None:
      seen.add(since)

   while True:
      messages = await poll_once(source, pacer)

      for message in in_delivery_order(messages):
         is_new = seen.add(message.id)

         if is_new:
            emit(NewMessage(message=message))

      await pacer.sleep(interval_seconds)


async def poll_once(source: EventSource, pacer: Pacer) -> Sequence[Message]:
   try:
      return await run_with_retries(source.poll, pacer=pacer)
   except SURVIVABLE as failure:
      _logger.warning(
         "a listener poll failed after its retries and the listener carries on: %s",
         type(failure).__name__,
      )

      return ()
