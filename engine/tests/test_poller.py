"""Gates on the polling transport behind ``events()``, the inbox poller of Step 23.

Four defect classes live here.

The poller can deliver what is not new: the baseline a first poll reads, a quiet inbox read
again, or the known message itself when a thread is read back. Each is an event for nothing,
every minute, for as long as a listener runs.

It can lose what is new without saying so: a thread read back too short, a cursor dropped, a
``since`` it could not place, a thread past the inbox's first page. The listener's promise is a
marker for every gap it knows of, so each of these must leave one.

It can spend what it should not: a thread read on a row that did not move, a page read twice, a
retry inside the pump's own retry, or a request that skips the account's pacer. Since ruling W10
of the web parity plan a thread is read back with its known message as
``newer_than_message_id`` on every page, and only in its own thread.

And it can send what a listener must not: a thread open, or anything else that could mark a
thread seen. Polling reads the listing and the scrolling query and nothing else.

Every payload is canned and synthetic, shaped after the recorded listing of 2026-09-23 with
pseudonymous ids and no real text. Nothing in this file touches the network.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

import pytest

from dumpstagram._core.pacer import Pacer
from dumpstagram._core.realtime.poller import (
   SINCE_SEARCH_THREADS,
   THREAD_PAGES_PER_GAP,
   InboxPoller,
   inbox_poller,
)
from dumpstagram._core.realtime.pump import Found, SourceContext
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import Request, Response
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT
from dumpstagram._private.web.documents import API_GRAPHQL_URL
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY, Behavior, Spacing
from dumpstagram.client import SyncClient
from dumpstagram.errors import CheckpointRequired, TransportFailure
from dumpstagram.models import EventsDropped, Message
from dumpstagram.session import Session
from tests.test_direct import (
   APP_SHELL,
   BOOTSTRAP_PAGE,
   FB_DTSG,
   FakeClock,
   ScriptedTransport,
   a_bootstrapped_session,
   html_response,
   json_response,
   make_paced,
   sent_variables,
)
from tests.test_events import ScriptedSource, a_message, client_on_a_fake_clock, take
from tests.test_inbox_listing import listing_payload, listing_row, message_edge
from tests.test_parse import node, payload

BASE_MS = 1_790_150_000_000
DEVICE_ID = "0b6f2c1e-8d7a-4c55-9e3f-2a1b0c9d8e7f"

LISTING = "PolarisDirectInboxQuery"
SCROLLING = "IGDMessageListOffMsysQuery"

THREAD_A = "17800000000000011"
THREAD_B = "17800000000000012"
THREAD_C = "17800000000000013"
THREAD_D = "17800000000000014"
THREAD_E = "17800000000000015"

BACK_TO_BACK = Behavior(
   spacing=Spacing(floor_seconds=0.0, mean_jitter_seconds=0.0), poll_interval_seconds=0.0
)

type Carried = list[tuple[str, int]]


def at(second: int) -> str:
   return str(BASE_MS + second * 1000)


def row(thread_fbid: str, carried: Carried) -> dict[str, Any]:
   """One listing row whose activity marker is its newest carried message, as measured."""

   return listing_row(
      thread_fbid=thread_fbid,
      thread_key=thread_fbid[:-2] + "99",
      activity_ms=at(carried[0][1]),
      message_edges=[message_edge(message_id, at(second)) for message_id, second in carried],
   )


def listing(*rows: dict[str, Any], has_next_page: bool = False) -> Response:
   return json_response(listing_payload(list(rows), has_next_page=has_next_page))


def thread_page(
   thread_fbid: str,
   messages: Carried,
   *,
   has_next_page: bool = False,
   end_cursor: str | None = None,
) -> Response:
   nodes = [
      node(
         id=message_id,
         message_id=message_id,
         thread_fbid=thread_fbid,
         timestamp_ms=at(second),
         text_body="synthetic",
      )
      for message_id, second in messages
   ]

   return json_response(payload(nodes, has_next_page=has_next_page, end_cursor=end_cursor))


def a_poller(transport: Any, *, since: str | None = None, session: Session | None = None) -> Any:
   sender = transport if isinstance(transport, PacedSender) else make_paced(transport)
   context = SourceContext(
      sender=sender,
      session=session or a_bootstrapped_session(),
      behavior=PARITY,
      user_agent=DEFAULT_USER_AGENT,
      since=since,
   )

   return InboxPoller(context, device_id=DEVICE_ID)


def names(sent: Sequence[Request]) -> list[str]:
   return [request.headers.get("x-fb-friendly-name", "document") for request in sent]


def message_ids(found: Sequence[Found]) -> list[str]:
   return sorted(item.id for item in found if isinstance(item, Message))


def gaps(found: Sequence[Found]) -> list[EventsDropped]:
   return [item for item in found if isinstance(item, EventsDropped)]


QUIET_ROWS = (
   row(THREAD_A, [("mid.$a2", 20), ("mid.$a1", 10)]),
   row(THREAD_B, [("mid.$b1", 5)]),
)


@pytest.mark.asyncio
async def test_the_first_poll_reads_the_inbox_once_and_delivers_nothing() -> None:
   """Catches a first poll that treats the whole inbox as new, which reads every thread and
   delivers old messages as if they had just arrived."""

   transport = ScriptedTransport([listing(*QUIET_ROWS)])

   found = await a_poller(transport).poll()

   assert found == []
   assert names(transport.sent) == [LISTING]


@pytest.mark.asyncio
async def test_a_quiet_inbox_costs_one_request_a_poll_and_delivers_nothing() -> None:
   """Catches a poll that reads a thread whose newest message did not move."""

   transport = ScriptedTransport([listing(*QUIET_ROWS), listing(*QUIET_ROWS)])
   poller = a_poller(transport)

   first = await poller.poll()
   second = await poller.poll()

   assert first == []
   assert second == []
   assert names(transport.sent) == [LISTING, LISTING]


@pytest.mark.asyncio
async def test_a_thread_that_gained_messages_delivers_exactly_those() -> None:
   """Catches the known message delivered again, an older one delivered as new, and a row that
   did not move being read. The page lists its messages out of order on purpose."""

   moved_b = row(THREAD_B, [("mid.$b3", 40), ("mid.$b2", 30), ("mid.$b1", 5)])
   transport = ScriptedTransport(
      [
         listing(*QUIET_ROWS),
         listing(moved_b, QUIET_ROWS[0]),
         thread_page(THREAD_B, [("mid.$b1", 5), ("mid.$b3", 40), ("mid.$b0", 1), ("mid.$b2", 30)]),
      ]
   )
   poller = a_poller(transport)

   await poller.poll()
   found = await poller.poll()

   assert message_ids(found) == ["mid.$b2", "mid.$b3"]
   assert gaps(found) == []
   assert names(transport.sent) == [LISTING, LISTING, SCROLLING]
   assert sent_variables(transport.sent[2])["id"] == THREAD_B
   assert sent_variables(transport.sent[2])["after"] is None


@pytest.mark.asyncio
async def test_paging_back_follows_the_cursor_to_the_known_message() -> None:
   """Catches a read back that drops the cursor, which rereads the newest page or gives up with
   a gap where one more page would have closed it."""

   first_page = [(f"mid.$n{index}", 100 + index) for index in range(25, 5, -1)]
   second_page = [(f"mid.$n{index}", 100 + index) for index in range(5, 0, -1)]
   transport = ScriptedTransport(
      [
         listing(*QUIET_ROWS),
         listing(row(THREAD_B, first_page[:5]), QUIET_ROWS[0]),
         thread_page(THREAD_B, first_page, has_next_page=True, end_cursor="cursor-one"),
         thread_page(THREAD_B, [*second_page, ("mid.$b1", 5)], has_next_page=True),
      ]
   )
   poller = a_poller(transport)

   await poller.poll()
   found = await poller.poll()

   assert len(message_ids(found)) == 25
   assert "mid.$b1" not in message_ids(found)
   assert gaps(found) == []
   assert sent_variables(transport.sent[3])["after"] == "cursor-one"


@pytest.mark.asyncio
async def test_a_thread_past_the_page_bound_leaves_a_marker_for_that_thread() -> None:
   """Catches a read back that stops at its bound and says nothing, which is silent loss."""

   pages = [
      thread_page(
         THREAD_B,
         [(f"mid.$p{page}m{index}", 1000 - page * 20 - index) for index in range(20)],
         has_next_page=True,
         end_cursor=f"cursor-{page}",
      )
      for page in range(THREAD_PAGES_PER_GAP)
   ]
   transport = ScriptedTransport(
      [
         listing(*QUIET_ROWS),
         listing(row(THREAD_B, [("mid.$p0m0", 1000)]), QUIET_ROWS[0]),
         *pages,
      ]
   )
   poller = a_poller(transport)

   await poller.poll()
   found = await poller.poll()

   assert gaps(found) == [EventsDropped(count=None, thread_fbid=THREAD_B)]
   assert found[0] == EventsDropped(count=None, thread_fbid=THREAD_B)
   assert len(message_ids(found)) == 20 * THREAD_PAGES_PER_GAP
   assert names(transport.sent).count(SCROLLING) == THREAD_PAGES_PER_GAP


@pytest.mark.asyncio
async def test_a_known_message_that_was_removed_still_closes_the_gap() -> None:
   """Catches a read back that pages on for a message that no longer exists, which spends a
   request per page and ends in a false gap marker."""

   transport = ScriptedTransport(
      [
         listing(*QUIET_ROWS),
         listing(row(THREAD_B, [("mid.$b2", 30), ("mid.$b0", 1)]), QUIET_ROWS[0]),
         thread_page(
            THREAD_B, [("mid.$b2", 30), ("mid.$b0", 1)], has_next_page=True, end_cursor="more"
         ),
      ]
   )
   poller = a_poller(transport)

   await poller.poll()
   found = await poller.poll()

   assert message_ids(found) == ["mid.$b2"]
   assert gaps(found) == []


@pytest.mark.asyncio
async def test_a_known_thread_is_read_back_with_its_last_known_message_as_the_base() -> None:
   """Catches the read back going out without ``newer_than_message_id``, which has the upstream
   answer the newest page whatever the listener already holds."""

   moved_b = row(THREAD_B, [("mid.$b3", 40), ("mid.$b2", 30), ("mid.$b1", 5)])
   transport = ScriptedTransport(
      [
         listing(*QUIET_ROWS),
         listing(moved_b, QUIET_ROWS[0]),
         thread_page(THREAD_B, [("mid.$b3", 40), ("mid.$b2", 30)]),
      ]
   )
   poller = a_poller(transport)

   await poller.poll()
   found = await poller.poll()

   assert message_ids(found) == ["mid.$b2", "mid.$b3"]
   assert names(transport.sent) == [LISTING, LISTING, SCROLLING]
   assert sent_variables(transport.sent[2])["newer_than_message_id"] == "mid.$b1"
   assert sent_variables(transport.sent[2])["after"] is None


@pytest.mark.asyncio
async def test_a_filtered_read_back_holds_the_base_on_every_page_and_ends_on_has_next_page() -> (
   None
):
   """Catches the base dropped from the pages after the first, and a filtered read that pages on
   past ``has_next_page`` false because the known message never appears in it.

   Shaped after ``logs/newer-than-pages-2026-09-23-185050.json``: 24 messages newer than the
   base came back as the newest 20 with ``has_next_page`` true, then, after that cursor with the
   same base, the other 4 with ``has_next_page`` false and a cursor still present. The base
   itself was on neither page.
   """

   newer = [(f"mid.$n{index}", 100 + index) for index in range(24, 0, -1)]
   transport = ScriptedTransport(
      [
         listing(*QUIET_ROWS),
         listing(row(THREAD_B, newer[:5]), QUIET_ROWS[0]),
         thread_page(THREAD_B, newer[:20], has_next_page=True, end_cursor="cursor-one"),
         thread_page(THREAD_B, newer[20:], has_next_page=False, end_cursor="cursor-two"),
      ]
   )
   poller = a_poller(transport)

   await poller.poll()
   found = await poller.poll()

   thread_reads = transport.sent[2:]

   assert len(message_ids(found)) == 24
   assert gaps(found) == []
   assert names(thread_reads) == [SCROLLING, SCROLLING]
   assert [sent_variables(request)["newer_than_message_id"] for request in thread_reads] == [
      "mid.$b1",
      "mid.$b1",
   ]
   assert [sent_variables(request)["after"] for request in thread_reads] == [None, "cursor-one"]


@pytest.mark.asyncio
async def test_a_thread_new_to_the_first_page_delivers_only_what_is_newer_than_the_last_poll() -> (
   None
):
   """Catches a thread the listener never listed before taken as new from its first message."""

   transport = ScriptedTransport(
      [
         listing(row(THREAD_A, [("mid.$a1", 20)])),
         listing(
            row(THREAD_C, [("mid.$c2", 30), ("mid.$c1", 3)]), row(THREAD_A, [("mid.$a1", 20)])
         ),
         thread_page(THREAD_C, [("mid.$c2", 30), ("mid.$c1", 3)]),
      ]
   )
   poller = a_poller(transport)

   await poller.poll()
   found = await poller.poll()

   assert message_ids(found) == ["mid.$c2"]


@pytest.mark.asyncio
async def test_since_carried_by_a_row_is_caught_up_from_without_a_search() -> None:
   """Catches a ``since`` the rows already place in time being searched for thread by thread,
   which spends reads and, past the search bound, reports a gap that is not there."""

   transport = ScriptedTransport(
      [
         listing(
            row(THREAD_A, [("mid.$a2", 40)]),
            row(THREAD_B, [("mid.$b1", 35)]),
            row(THREAD_C, [("mid.$c1", 30)]),
            row(THREAD_D, [("mid.$d2", 25), ("mid.$d1", 20)]),
            row(THREAD_E, [("mid.$e1", 15)]),
         ),
         thread_page(THREAD_A, [("mid.$a2", 40), ("mid.$a1", 5)]),
         thread_page(THREAD_B, [("mid.$b1", 35), ("mid.$b0", 4)]),
         thread_page(THREAD_C, [("mid.$c1", 30), ("mid.$c0", 3)]),
         thread_page(THREAD_D, [("mid.$d2", 25), ("mid.$d1", 20), ("mid.$d0", 2)]),
      ]
   )

   found = await a_poller(transport, since="mid.$d1").poll()

   assert message_ids(found) == ["mid.$a2", "mid.$b1", "mid.$c1", "mid.$d2"]
   assert gaps(found) == []
   assert [sent_variables(request)["id"] for request in transport.sent[1:]] == [
      THREAD_A,
      THREAD_B,
      THREAD_C,
      THREAD_D,
   ]


@pytest.mark.asyncio
async def test_since_found_on_a_thread_page_is_caught_up_from_that_same_page() -> None:
   """Catches the page the search already read being read again for the catch up."""

   carried = [(f"mid.$a{index}", index * 10) for index in range(7, 2, -1)]
   transport = ScriptedTransport(
      [
         listing(row(THREAD_A, carried), row(THREAD_B, [("mid.$b1", 5)])),
         thread_page(THREAD_A, [(f"mid.$a{index}", index * 10) for index in range(7, -1, -1)]),
      ]
   )

   found = await a_poller(transport, since="mid.$a1").poll()

   assert message_ids(found) == [f"mid.$a{index}" for index in range(2, 8)]
   assert names(transport.sent) == [LISTING, SCROLLING]


@pytest.mark.asyncio
async def test_a_since_catch_up_sends_no_base_to_a_thread_it_did_not_come_from() -> None:
   """Catches the watermark sent as ``newer_than_message_id`` to every thread being caught up.
   A base from another thread has never been sent, and an answer to it may be empty."""

   transport = ScriptedTransport(
      [
         listing(
            row(THREAD_A, [("mid.$a2", 40)]),
            row(THREAD_D, [("mid.$d2", 25), ("mid.$d1", 20)]),
         ),
         thread_page(THREAD_A, [("mid.$a2", 40), ("mid.$a1", 5)]),
         thread_page(THREAD_D, [("mid.$d2", 25), ("mid.$d1", 20)]),
      ]
   )

   found = await a_poller(transport, since="mid.$d1").poll()

   assert message_ids(found) == ["mid.$a2", "mid.$d2"]
   assert [sent_variables(request)["newer_than_message_id"] for request in transport.sent[1:]] == [
      None,
      None,
   ]


@pytest.mark.asyncio
async def test_a_since_nowhere_to_be_found_is_reported_and_the_listener_carries_on() -> None:
   """Catches an unplaceable ``since`` skipped in silence, which hides that the catch up did not
   happen, and a search that is not bounded."""

   rows = [
      row(thread, [(f"mid.$x{index}", 50 - index)])
      for index, thread in enumerate([THREAD_A, THREAD_B, THREAD_C, THREAD_D, THREAD_E])
   ]
   searched = [
      thread_page(thread, [(f"mid.$x{index}", 50 - index)])
      for index, thread in enumerate([THREAD_A, THREAD_B, THREAD_C])
   ]
   transport = ScriptedTransport([listing(*rows), *searched, listing(*rows)])
   poller = a_poller(transport, since="mid.$gone")

   found = await poller.poll()
   after = await poller.poll()

   assert found == [EventsDropped(count=None)]
   assert names(transport.sent).count(SCROLLING) == SINCE_SEARCH_THREADS
   assert after == []


@pytest.mark.asyncio
async def test_a_first_page_ending_newer_than_the_last_poll_is_reported() -> None:
   """Catches changes past the inbox's first page being taken as none. When the last listed row
   is itself newer than the last poll, a row below it can be too."""

   transport = ScriptedTransport(
      [
         listing(row(THREAD_A, [("mid.$a1", 10)]), has_next_page=True),
         listing(
            row(THREAD_B, [("mid.$b1", 50)]),
            row(THREAD_C, [("mid.$c1", 40)]),
            has_next_page=True,
         ),
         thread_page(THREAD_B, [("mid.$b1", 50)]),
         thread_page(THREAD_C, [("mid.$c1", 40)]),
      ]
   )
   poller = a_poller(transport)

   await poller.poll()
   found = await poller.poll()

   assert message_ids(found) == ["mid.$b1", "mid.$c1"]
   assert gaps(found) == [EventsDropped(count=None)]


@pytest.mark.asyncio
async def test_a_poll_sends_only_the_listing_and_the_scrolling_query() -> None:
   """Catches a poll that opens a thread the way a browser does before it marks it seen. A
   listener reads, it never leaves a trace a sender can see."""

   moved_b = row(THREAD_B, [("mid.$b2", 30), ("mid.$b1", 5)])
   transport = ScriptedTransport(
      [
         listing(*QUIET_ROWS),
         listing(moved_b, QUIET_ROWS[0]),
         thread_page(THREAD_B, [("mid.$b2", 30), ("mid.$b1", 5)]),
      ]
   )
   poller = a_poller(transport)

   await poller.poll()
   await poller.poll()

   assert len(transport.sent) == 3
   assert set(names(transport.sent)) == {LISTING, SCROLLING}


@pytest.mark.asyncio
async def test_a_stale_token_is_fetched_once_within_the_poll() -> None:
   """Catches a poll that gives up on a token the upstream stopped accepting, which ends the
   listener on what one bootstrap fixes."""

   transport = ScriptedTransport(
      [
         html_response(APP_SHELL, final_url=API_GRAPHQL_URL),
         html_response(BOOTSTRAP_PAGE),
         listing(*QUIET_ROWS),
      ]
   )
   session = a_bootstrapped_session()

   found = await a_poller(transport, session=session).poll()

   assert found == []
   assert names(transport.sent) == [LISTING, "document", LISTING]
   assert session.fb_dtsg == FB_DTSG


class FailingTransport:
   def __init__(self) -> None:
      self.sent: list[Request] = []

   async def send(self, request: Request) -> Response:
      self.sent.append(request)

      raise TransportFailure("connection reset")


@pytest.mark.asyncio
async def test_a_poll_makes_one_attempt_and_leaves_the_retry_to_the_pump() -> None:
   """Catches a poll with a retry policy of its own inside the pump's, which multiplies the
   requests one failure costs the account."""

   transport = FailingTransport()

   with pytest.raises(TransportFailure):
      await a_poller(transport).poll()

   assert len(transport.sent) == 1


class SlotWatchingTransport(ScriptedTransport):
   def __init__(self, responses: list[Response], clock: FakeClock) -> None:
      super().__init__(responses)
      self.clock = clock
      self.pacer: Pacer | None = None
      self.departures: list[float] = []
      self.held_the_slot: list[bool] = []

   async def send(self, request: Request) -> Response:
      self.departures.append(self.clock.now)
      self.held_the_slot.append(self.pacer is not None and self.pacer._lock.locked())

      return await super().send(request)


@pytest.mark.asyncio
async def test_every_request_a_poll_sends_passes_the_accounts_pacer() -> None:
   """Catches a poller that reaches past the paced sender it was handed, measured where
   requests leave rather than at the pacer."""

   clock = FakeClock()
   moved_b = row(THREAD_B, [("mid.$b2", 30), ("mid.$b1", 5)])
   transport = SlotWatchingTransport(
      [
         listing(*QUIET_ROWS),
         listing(moved_b, QUIET_ROWS[0]),
         thread_page(THREAD_B, [("mid.$b2", 30), ("mid.$b1", 5)]),
      ],
      clock,
   )
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)
   transport.pacer = pacer
   sender = PacedSender(
      transport, pacer, replace(pacer.pacing, floor_seconds=2.5, mean_jitter_seconds=0.0)
   )
   poller = a_poller(sender)

   await poller.poll()
   await poller.poll()

   gaps_between = [
      later - earlier
      for earlier, later in zip(transport.departures[:-1], transport.departures[1:], strict=True)
   ]

   assert len(transport.departures) == 3
   assert gaps_between == [2.5, 2.5]
   assert all(transport.held_the_slot)


class CheckpointAfterScript(ScriptedTransport):
   async def send(self, request: Request) -> Response:
      if not self.responses:
         self.sent.append(request)

         raise CheckpointRequired("a checkpoint")

      return await super().send(request)


@pytest.mark.asyncio
async def test_a_client_polls_the_inbox_by_default() -> None:
   """Catches a client left with a source that never reads the inbox, which a caller would take
   for an inbox where nothing happens. Replaces the Step 22 gate on the placeholder."""

   client = AsyncClient(a_bootstrapped_session(), behavior=BACK_TO_BACK)
   await client._sender.aclose()

   transport = CheckpointAfterScript([listing(*QUIET_ROWS)])
   client._sender = make_paced(transport)

   try:
      with pytest.raises(CheckpointRequired):
         await asyncio.wait_for(take(client, 1), timeout=5.0)
   finally:
      await client.aclose()

   assert names(transport.sent) == [LISTING, LISTING]

   with SyncClient(a_bootstrapped_session()) as blocking:
      assert blocking._impl._event_source is inbox_poller


@pytest.mark.asyncio
async def test_a_gap_a_source_reports_reaches_the_consumer_ahead_of_that_polls_messages() -> None:
   """Catches the pump dropping a source's gap marker, which turns every loss the poller
   reported back into silence."""

   marker = EventsDropped(count=None, thread_fbid=THREAD_B)
   source = ScriptedSource([[a_message("mid.$b9"), marker]])  # type: ignore[list-item]
   client, _, _ = await client_on_a_fake_clock(BACK_TO_BACK, source)

   taken = await take(client, 2)

   assert taken[0] == marker
   assert [type(event).__name__ for event in taken] == ["EventsDropped", "NewMessage"]
