"""Gates on the listener behind ``events()``: the buffer, the pump and both surfaces.

Step 22 of ``docs/build-plan.md`` fixed the surface before the polling transport existed, so
every gate here drives the listener with a scripted source injected where the client keeps its
source factory, which is the inbox poller of Step 23 by default and is gated in
``test_poller.py``. Nothing here spends a request. The async gates run the pacer on a fake
clock, and the blocking gates run on the real shared loop thread, because the thread seam is
what they are about.

Each gate names the defect it catches, and ``scripts/verify_events_gates.py`` breaks the source
once per gate and watches it go red.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from collections.abc import Callable, Sequence
from contextlib import aclosing
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from dumpstagram._core.loop_thread import THREAD_NAME, _LoopThread, seam_note
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.realtime.buffer import EventBuffer
from dumpstagram._core.realtime.pump import SeenIds, SourceContext
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import Request, Response
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import Behavior, Spacing
from dumpstagram.client import SyncClient
from dumpstagram.errors import (
   AuthenticationFailed,
   CheckpointRequired,
   TransportFailure,
)
from dumpstagram.models import (
   Event,
   EventsDropped,
   ListenerStopped,
   Message,
   MessageSender,
   NewMessage,
)
from dumpstagram.session import Session

EPOCH = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)

UNPACED = Behavior(spacing=Spacing(floor_seconds=0.0, mean_jitter_seconds=0.0))
BACK_TO_BACK = replace(UNPACED, poll_interval_seconds=0.0)


class ScriptFinished(Exception):
   """What a scripted source raises when its script runs out, which ends the listener."""


class FakeClock:
   """A monotonic clock that only advances when something sleeps on it."""

   def __init__(self) -> None:
      self.now = 0.0

   def __call__(self) -> float:
      return self.now

   async def sleep(self, seconds: float) -> None:
      self.now += seconds

      await asyncio.sleep(0)


class CountingTransport:
   """Records the clock at every departure, and whether the account's slot was held for it."""

   def __init__(self, clock: FakeClock) -> None:
      self.clock = clock
      self.pacer: Pacer | None = None
      self.departures: list[float] = []
      self.held_the_slot: list[bool] = []

   async def send(self, request: Request) -> Response:
      self.departures.append(self.clock.now)
      self.held_the_slot.append(self.pacer is not None and self.pacer._lock.locked())

      return Response(status_code=200, headers={}, content=b"{}", final_url=request.url)

   async def aclose(self) -> None:
      return None


class ScriptedSource:
   """A source that answers each poll from a script, then raises :class:`ScriptFinished`.

   A step is a list of messages to return or an exception to raise. ``pause`` is a real sleep
   before every answer, so a blocking listener polling back to back does not spin its loop.
   """

   def __init__(
      self,
      steps: Sequence[Sequence[Message] | Exception],
      *,
      clock: FakeClock | None = None,
      sends: bool = False,
      pause: float = 0.0,
   ) -> None:
      self.steps = list(steps)
      self.clock = clock
      self.sends = sends
      self.pause = pause
      self.polls = 0
      self.polled_at: list[float] = []
      self.context: SourceContext | None = None

   def factory(self, context: SourceContext) -> ScriptedSource:
      self.context = context

      return self

   async def poll(self) -> Sequence[Message]:
      self.polls += 1

      if self.clock is not None:
         self.polled_at.append(self.clock.now)

      if self.pause:
         await asyncio.sleep(self.pause)

      if self.sends:
         assert self.context is not None

         await self.context.sender.send(Request(method="GET", url="https://example.invalid/poll"))

      if not self.steps:
         raise ScriptFinished("the script ran out")

      step = self.steps.pop(0)

      if isinstance(step, Exception):
         raise step

      return list(step)


def a_session() -> Session:
   return Session(sessionid="71234567%3AabcdefGHIJKL%3A17", ds_user_id="71234567", csrftoken="t")


def a_message(message_id: str, *, thread: str = "340282366841710300", second: int = 0) -> Message:
   return Message(
      id=message_id,
      thread_fbid=thread,
      sender=MessageSender(fbid="17841400000000001"),
      sent_at=EPOCH + timedelta(seconds=second),
      text=None,
      content_type="TEXT",
   )


def ids_of(events: Sequence[Event]) -> list[str]:
   return [event.message.id for event in events if isinstance(event, NewMessage)]


async def client_on_a_fake_clock(
   behavior: Behavior,
   source: ScriptedSource,
   *,
   floor_seconds: float = 0.0,
) -> tuple[AsyncClient, FakeClock, CountingTransport]:
   client = AsyncClient(a_session(), behavior=behavior)
   await client._sender.aclose()

   clock = source.clock or FakeClock()
   source.clock = clock
   transport = CountingTransport(clock)
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)
   transport.pacer = pacer
   client._sender = PacedSender(
      transport,
      pacer,
      replace(pacer.pacing, floor_seconds=floor_seconds, mean_jitter_seconds=0.0),
   )
   client._event_source = source.factory

   return client, clock, transport


async def take(client: AsyncClient, count: int, *, since: str | None = None) -> list[Event]:
   taken: list[Event] = []

   async with aclosing(client.events(since=since)) as stream:  # type: ignore[type-var]
      async for event in stream:
         taken.append(event)

         if len(taken) == count:
            break

   return taken


def blocking_client(source: ScriptedSource, behavior: Behavior = BACK_TO_BACK) -> SyncClient:
   client = SyncClient(a_session(), behavior=behavior)
   client._impl._event_source = source.factory

   return client


def wait_until_stopped(listener_wait: Callable[[float], list[Event]]) -> list[Event]:
   """Everything a blocking listener delivers up to and including its final event."""

   delivered: list[Event] = []
   deadline = time.monotonic() + 20.0

   while time.monotonic() < deadline:
      delivered.extend(listener_wait(1.0))

      if delivered and isinstance(delivered[-1], ListenerStopped):
         return delivered

   raise AssertionError("the listener never delivered its final event")


def test_drain_from_another_thread_returns_every_event_exactly_once() -> None:
   """Catches a drain that does not hold the lock the loop thread puts under, which loses an
   event put between the drain copying the buffer and clearing it."""

   polls = 300
   per_poll = 60
   steps: list[Sequence[Message] | Exception] = [
      [a_message(f"mid.{poll}.{index}", second=index) for index in range(per_poll)]
      for poll in range(polls)
   ]
   source = ScriptedSource(steps)
   previous_interval = sys.getswitchinterval()
   sys.setswitchinterval(1e-6)

   try:
      with blocking_client(source) as client:
         listener = client.events()
         listener.start()

         try:
            delivered: list[Event] = []

            while not (delivered and isinstance(delivered[-1], ListenerStopped)):
               delivered.extend(listener.drain())
         finally:
            listener.stop()
   finally:
      sys.setswitchinterval(previous_interval)

   delivered_ids = ids_of(delivered)
   dropped = sum(event.count for event in delivered if isinstance(event, EventsDropped))

   assert len(delivered_ids) == len(set(delivered_ids))
   assert len(delivered_ids) + dropped == polls * per_poll


def test_overflow_drops_the_oldest_and_leaves_a_marker_carrying_the_count() -> None:
   """Catches a full buffer dropping the newest event, or dropping without saying so.

   The bound is written out rather than read off the module, so turning it down cannot also
   turn this assertion down.
   """

   buffer = EventBuffer()

   for index in range(1005):
      buffer.put(NewMessage(message=a_message(f"mid.{index}")))

   taken = buffer.drain()

   assert taken[0] == EventsDropped(count=5)
   assert ids_of(taken) == [f"mid.{index}" for index in range(5, 1005)]
   assert buffer.drain() == []


def test_a_final_event_survives_a_full_buffer() -> None:
   """Catches the event that says why the listener stopped being dropped by the bound."""

   buffer = EventBuffer(capacity=2)
   failure = CheckpointRequired("checkpoint")

   for index in range(3):
      buffer.put(NewMessage(message=a_message(f"mid.{index}")))

   buffer.finish(ListenerStopped(error=failure))
   buffer.put(NewMessage(message=a_message("mid.late")))

   taken = buffer.drain()

   assert taken[-1] == ListenerStopped(error=failure)
   assert ids_of(taken) == ["mid.1", "mid.2"]


def test_wait_for_events_wakes_when_an_event_arrives() -> None:
   """Catches a put that does not wake a parked consumer, which then sleeps out its timeout."""

   buffer = EventBuffer()

   def put_soon() -> None:
      time.sleep(0.05)
      buffer.put(NewMessage(message=a_message("mid.1")))

   producer = threading.Thread(target=put_soon)
   started_at = time.monotonic()
   producer.start()

   taken = buffer.wait(10.0)
   producer.join()

   assert ids_of(taken) == ["mid.1"]
   assert time.monotonic() - started_at < 5.0


@pytest.mark.asyncio
async def test_a_message_id_seen_twice_is_one_event() -> None:
   """Catches the listener emitting every message a poll returns, which a poll does again for
   a thread it reads twice."""

   first = a_message("mid.1", second=1)
   second = a_message("mid.2", second=2)
   source = ScriptedSource([[first], [first, second], [second]])
   client, _, _ = await client_on_a_fake_clock(BACK_TO_BACK, source)

   taken = await take_until_the_script_ends(client)

   assert ids_of(taken) == ["mid.1", "mid.2"]


async def take_until_the_script_ends(client: AsyncClient) -> list[Event]:
   taken: list[Event] = []

   with pytest.raises(ScriptFinished):
      async with aclosing(client.events()) as stream:  # type: ignore[type-var]
         async for event in stream:
            taken.append(event)

   return taken


@pytest.mark.asyncio
async def test_events_within_a_thread_arrive_in_ascending_sent_at() -> None:
   """Catches events emitted in the order a poll reads them, which is newest thread first and
   newest message first."""

   inbox_order = [
      a_message("mid.a3", thread="1", second=30),
      a_message("mid.a2", thread="1", second=20),
      a_message("mid.a1", thread="1", second=10),
      a_message("mid.b2", thread="2", second=25),
      a_message("mid.b1", thread="2", second=5),
   ]
   source = ScriptedSource([inbox_order])
   client, _, _ = await client_on_a_fake_clock(BACK_TO_BACK, source)

   taken = await take_until_the_script_ends(client)
   delivered = [event.message for event in taken if isinstance(event, NewMessage)]

   for thread in ("1", "2"):
      sent = [message.sent_at for message in delivered if message.thread_fbid == thread]

      assert sent == sorted(sent)

   assert ids_of(taken) == ["mid.b1", "mid.a1", "mid.a2", "mid.b2", "mid.a3"]


@pytest.mark.parametrize(
   "failure_type",
   [CheckpointRequired, AuthenticationFailed],
   ids=["checkpoint", "authentication"],
)
def test_a_terminal_failure_stops_the_listener_and_the_sync_side_sees_it_in_band(
   failure_type: type[Exception],
) -> None:
   """Catches a listener that swallows a checkpoint and keeps polling, and one that stops
   without telling a consumer who only drains why the events stopped."""

   failure = failure_type("the account needs its owner")
   source = ScriptedSource(
      [[a_message("mid.1")], failure, [a_message("mid.2")]],
      pause=0.001,
   )

   with blocking_client(source) as client, client.events() as listener:
      delivered = wait_until_stopped(listener.wait_for_events)
      time.sleep(0.1)
      polls_after_the_failure = source.polls

   assert ids_of(delivered) == ["mid.1"]
   assert isinstance(delivered[-1], ListenerStopped)
   assert delivered[-1].error is failure
   assert seam_note("EventListener") in getattr(failure, "__notes__", [])
   assert polls_after_the_failure == 2


@pytest.mark.asyncio
async def test_the_async_iterator_reraises_the_original_failure() -> None:
   """Catches the iterator wrapping the failure, which breaks a caller's ``except
   CheckpointRequired`` exactly when it matters most."""

   failure = CheckpointRequired("the account needs its owner")
   source = ScriptedSource([[a_message("mid.1")], failure])
   client, _, _ = await client_on_a_fake_clock(BACK_TO_BACK, source)
   taken: list[Event] = []

   with pytest.raises(CheckpointRequired) as caught:
      async with aclosing(client.events()) as stream:  # type: ignore[type-var]
         async for event in stream:
            taken.append(event)

   assert caught.value is failure
   assert ids_of(taken) == ["mid.1"]


@pytest.mark.asyncio
async def test_a_checkpoint_during_a_poll_is_never_retried() -> None:
   """Catches the listener polling through a checkpoint, which turns a soft block into a
   locked account. One poll, no backoff held, and the checkpoint is what the caller gets."""

   failure = CheckpointRequired("the account needs its owner")
   source = ScriptedSource([failure, [a_message("mid.1")]])
   client, clock, _ = await client_on_a_fake_clock(BACK_TO_BACK, source)

   with pytest.raises(CheckpointRequired):
      await take(client, 1)

   assert source.polls == 1
   assert clock.now == 0.0


@pytest.mark.asyncio
async def test_the_listener_polls_through_a_transport_failure_that_outlasts_its_retries() -> None:
   """Catches a listener that dies on a network failure, and one that retries a poll without
   holding the account for the backoff. Five attempts fail, the backoff waits out 4, 8, 16 and
   32 seconds, and the next poll's message still arrives."""

   outage = [TransportFailure(f"reset {attempt}") for attempt in range(5)]
   source = ScriptedSource([*outage, [a_message("mid.1")]])
   client, clock, _ = await client_on_a_fake_clock(BACK_TO_BACK, source)

   taken = await take(client, 1)

   assert ids_of(taken) == ["mid.1"]
   assert source.polls == 6
   assert clock.now >= 60.0


@pytest.mark.asyncio
async def test_every_poll_passes_the_pacer() -> None:
   """Catches a listener handed a sender of its own that skips the account's pacer, measured
   where requests leave rather than at the pacer. The interval is zero, so only the pacer can
   space these departures."""

   steps: list[Sequence[Message] | Exception] = [[a_message(f"mid.{index}")] for index in range(4)]
   source = ScriptedSource(steps, sends=True)
   client, _, transport = await client_on_a_fake_clock(BACK_TO_BACK, source, floor_seconds=2.5)

   await take(client, 4)

   gaps = [
      later - earlier
      for earlier, later in zip(transport.departures[:-1], transport.departures[1:], strict=True)
   ]

   assert len(transport.departures) == 4
   assert gaps == [2.5, 2.5, 2.5]
   assert all(transport.held_the_slot)


@pytest.mark.asyncio
async def test_the_listener_waits_the_behaviors_poll_interval() -> None:
   """Catches an interval that ignores the behavior setting a caller chose."""

   steps: list[Sequence[Message] | Exception] = [[a_message(f"mid.{index}")] for index in range(3)]
   source = ScriptedSource(steps)
   client, _, _ = await client_on_a_fake_clock(replace(UNPACED, poll_interval_seconds=7.0), source)

   await take(client, 3)

   assert source.polled_at == [0.0, 7.0, 14.0]


def test_the_poll_interval_defaults_to_a_minute_and_refuses_a_negative() -> None:
   """Catches the ruled default drifting, and a sign error reaching the listener."""

   assert Behavior().poll_interval_seconds == 60.0

   with pytest.raises(ValueError):
      Behavior(poll_interval_seconds=-1.0)


@pytest.mark.asyncio
async def test_since_is_never_delivered_again() -> None:
   """Catches a restarted listener delivering the message its consumer last handled."""

   source = ScriptedSource([[a_message("mid.1", second=1), a_message("mid.2", second=2)]])
   client, _, _ = await client_on_a_fake_clock(BACK_TO_BACK, source)

   taken: list[Event] = []

   with pytest.raises(ScriptFinished):
      async with aclosing(client.events(since="mid.1")) as stream:  # type: ignore[type-var]
         async for event in stream:
            taken.append(event)

   assert ids_of(taken) == ["mid.2"]
   assert source.context is not None
   assert source.context.since == "mid.1"


def test_the_blocking_listener_hands_since_to_its_source() -> None:
   """Catches the blocking facade dropping ``since`` on the way to the source it builds."""

   source = ScriptedSource([], pause=0.001)

   with blocking_client(source) as client, client.events(since="mid.7") as listener:
      wait_until_stopped(listener.wait_for_events)

   assert source.context is not None
   assert source.context.since == "mid.7"


def test_the_seen_id_memory_is_bounded() -> None:
   """Catches a listener that remembers every id for its whole life, which grows without bound
   over a listener that runs for days."""

   seen = SeenIds()

   for index in range(10_050):
      seen.add(f"mid.{index}")

   assert len(seen) == 10_000
   assert seen.add("mid.10049") is False
   assert seen.add("mid.0") is True


def test_stop_releases_the_loop_thread_reference_and_the_task() -> None:
   """Catches a stop that returns while the poll task is still running, which keeps polling
   the account after the consumer said to stop, and one that leaks its loop thread hold."""

   source = ScriptedSource([[a_message(f"mid.{index}")] for index in range(10_000)], pause=0.001)

   with blocking_client(source) as client:
      loop_thread = _LoopThread.acquire()
      loop_thread.release()
      references_before = loop_thread.references

      listener = client.events()
      listener.start()

      assert listener.wait_for_events(10.0)
      assert loop_thread.references == references_before + 1

      listener.stop()

      polls_at_stop = source.polls
      time.sleep(0.2)

      assert listener._task is not None
      assert listener._task.done()
      assert source.polls == polls_at_stop
      assert loop_thread.references == references_before


def test_with_a_handler_events_go_to_it_on_its_own_thread_and_not_the_buffer() -> None:
   """Catches the handler being run on the loop thread, where consumer code would stall every
   poll, and events reaching a buffer nobody drains."""

   received: list[tuple[Event, str]] = []
   finished = threading.Event()

   def handler(event: Event) -> None:
      received.append((event, threading.current_thread().name))

      if isinstance(event, ListenerStopped):
         finished.set()

   source = ScriptedSource([[a_message("mid.1"), a_message("mid.2", second=1)]], pause=0.001)

   with blocking_client(source) as client, client.events(on_event=handler) as listener:
      assert finished.wait(20.0)

      with pytest.raises(RuntimeError):
         listener.drain()

   events = [event for event, _ in received]
   threads = {thread for _, thread in received}

   assert ids_of(events) == ["mid.1", "mid.2"]
   assert isinstance(events[-1], ListenerStopped)
   assert threads == {"dumpstagram-events"}
   assert THREAD_NAME not in threads


@pytest.mark.asyncio
async def test_no_blocking_call_runs_on_the_loop_thread() -> None:
   """Catches a poll that blocks the loop, which stalls every other request on the account.

   The pacer runs on a fake clock so the polls cost no real time, and a watchdog task on the
   same loop measures the longest real gap between its turns.
   """

   steps: list[Sequence[Message] | Exception] = [[a_message(f"mid.{index}")] for index in range(20)]
   source = ScriptedSource(steps)
   client, _, _ = await client_on_a_fake_clock(BACK_TO_BACK, source)
   longest_stall = 0.0
   watching = True

   async def watchdog() -> None:
      nonlocal longest_stall

      while watching:
         before = time.perf_counter()
         await asyncio.sleep(0)
         longest_stall = max(longest_stall, time.perf_counter() - before)

   watcher = asyncio.create_task(watchdog())

   try:
      await take(client, 20)
   finally:
      watching = False
      await watcher

   assert longest_stall < 0.1
