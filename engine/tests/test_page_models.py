"""Gates on the direct inbox's page load, which the notes tray, the inbox's first page and the
unread counts are read from under the default behavior, E2 batch 9.

The parity gate compares what the engine sends against the burst a browser sent in a recorded
inbox cold load, group by group, where a group is the requests in flight together. The recorded
burst is written out below rather than read from the capture, which is local to one machine.
What the gate leaves out of the recording is named beside it.

The defect classes: a request of the burst missing, extra, out of the page's order or grouped
unlike it, ``news/inbox_seen`` among them; a query keyed on a device id the document did not
carry; a thread detail prefetch for the wrong threads or in the wrong order; a read taking its
answer from another query of the block; a query nobody reads costing the caller the read, or a
checkpoint on one passing unnoticed; the burst paced as several actions; the cookie sync tail
scheduled for the wrong page or after a failed read; and the behavior setting dropped on the way
down, or the departure sending more than the read's own queries.

The inbox answers are batch 1's pseudonymised fixtures and the document is synthetic. Nothing in
this file touches the network.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import replace
from typing import Any
from urllib.parse import parse_qs

import pytest

from dumpstagram._core.inbox import read_inbox_page, read_unread_counts
from dumpstagram._core.notes import read_notes
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import Request, Response
from dumpstagram._private.web.documents.direct import (
   DIRECT_INBOX,
   DIRECT_INBOX_NEXT_PAGE,
   FOLDER_UNREAD_ROWS,
   THREAD_DETAIL,
)
from dumpstagram._private.web.documents.notes import INBOX_TRAY
from dumpstagram._private.web.documents.page_load import (
   AUTOMATIC_PREVIEWS_SETTING,
   BADGE_COUNT,
   FEATURE_LIMITS,
   INBOX_QP_INTERSTITIAL,
   PRESENCE_SETUP,
   QUICK_PROMOTION,
   STORIES_TRAY,
   THREAD_LIST_ACCOUNT_SWITCHER,
   VIEWER_SETTINGS,
)
from dumpstagram._private.web.parse.direct import (
   parse_folder_unread_rows,
   parse_inbox_page,
)
from dumpstagram._private.web.parse.notes import parse_inbox_tray
from dumpstagram.behavior import PARITY, Behavior, InboxRoute
from dumpstagram.client import SyncClient
from dumpstagram.errors import CheckpointRequired, SchemaChanged
from dumpstagram.session import Session
from tests.test_direct import BOOTSTRAP_PAGE, FakeClock, a_bootstrapped_session, json_response
from tests.test_direct_read import recorded
from tests.test_notes import own_and_other_tray
from tests.test_page_load import DEVICE_ID, client_over, with_device_id

INBOX_URL = "https://www.instagram.com/direct/inbox/"
ORIGIN = "https://www.instagram.com"

DOCUMENT = "GET /direct/inbox/"
INBOX_ROWS = f"{FOLDER_UNREAD_ROWS.friendly_name}: INBOX"
PENDING_ROWS = f"{FOLDER_UNREAD_ROWS.friendly_name}: PENDING"
LOGIN_SURFACE = "quick promotion: login interstitial"
FOLLOW_REQUESTS = "GET /api/v1/friendships/pending/"
ACTIVITY_FEED = "POST /api/v1/news/inbox/"
FIRST_PAGE_ROWS = 15

INBOX_RECORDED_BURST = [
   [DOCUMENT],
   [
      AUTOMATIC_PREVIEWS_SETTING.friendly_name,
      FEATURE_LIMITS.friendly_name,
      INBOX_ROWS,
      DIRECT_INBOX.friendly_name,
      PENDING_ROWS,
      PRESENCE_SETUP.friendly_name,
      INBOX_QP_INTERSTITIAL.friendly_name,
      THREAD_LIST_ACCOUNT_SWITCHER.friendly_name,
      VIEWER_SETTINGS.friendly_name,
      INBOX_TRAY.friendly_name,
   ],
   [BADGE_COUNT.friendly_name],
   [STORIES_TRAY.friendly_name],
   [LOGIN_SURFACE],
   [THREAD_DETAIL.friendly_name] * FIRST_PAGE_ROWS,
   [FOLLOW_REQUESTS, ACTIVITY_FEED],
]
"""The inbox cold load of ``run-2026-09-23-022159``: the document at 0 ms, the direct block at
492 to 496, the badge count at 519, the stories tray at 642, the login interstitial at 849, the
fifteen thread details at 1039 to 1044, and the pending follow requests and the activity feed at
3687, 0.4 ms apart. Left out of it: the feed timeline prefetch at 641, which the profile load
leaves out too, ``fxcal`` at 545, which has no verified finding, ``news/inbox_seen`` at 3685,
an unverified write (W74), and the cookie sync from 3870, which is a later step. The second
cold load, ``run-2026-09-23-045256``, sent the same up to the thread details and no REST read."""


def variables_of(request: Request) -> dict[str, Any]:
   body = parse_qs(request.content.decode("utf-8"))

   return json.loads(body["variables"][0])


def label(request: Request) -> str:
   path = request.url.removeprefix(ORIGIN)
   is_rest = request.method == "GET" or path.startswith("/api/v1/")

   if is_rest:
      return f"{request.method} {path}"

   name = request.headers["x-fb-friendly-name"]

   if name == FOLDER_UNREAD_ROWS.friendly_name:
      return f"{name}: {variables_of(request)['folder']}"

   if name == QUICK_PROMOTION.friendly_name:
      surfaces = variables_of(request)["surface_nux_ids"]
      is_login_surface = surfaces == ["INSTAGRAM_FOR_WEB_LOGIN_INTERSTITIAL_QP"]

      return LOGIN_SURFACE if is_login_surface else "quick promotion: page surfaces"

   return name


def an_inbox_document(*, device_id: bool = True) -> str:
   return with_device_id(BOOTSTRAP_PAGE) if device_id else BOOTSTRAP_PAGE


def html_answer(body: str) -> Response:
   return Response(
      status_code=200,
      headers={"content-type": "text/html; charset=utf-8"},
      content=body.encode("utf-8"),
      final_url=INBOX_URL,
   )


def recorded_answers() -> dict[str, Response]:
   return {
      DIRECT_INBOX.friendly_name: json_response(recorded("inbox_first_page.json")),
      DIRECT_INBOX_NEXT_PAGE.friendly_name: json_response(recorded("inbox_next_page.json")),
      INBOX_ROWS: json_response(recorded("inbox_unread_rows.json")),
      PENDING_ROWS: json_response(recorded("pending_unread_rows.json")),
      INBOX_TRAY.friendly_name: json_response(own_and_other_tray()),
   }


class InboxBurstTransport:
   """Answers by request, and records which requests were in flight together.

   A request that arrives while nothing is in flight opens a new group. Each send yields to the
   loop several times before answering, so requests sent together are all in flight before the
   first of them returns.
   """

   def __init__(self, document: str | None = None, **answers: Response) -> None:
      self.document = html_answer(document if document is not None else an_inbox_document())
      self.answers = {**recorded_answers(), **answers}
      self.sent: list[Request] = []
      self.groups: list[list[str]] = []
      self.in_flight = 0

   async def send(self, request: Request) -> Response:
      self.sent.append(request)
      name = label(request)

      if self.in_flight == 0:
         self.groups.append([])

      self.groups[-1].append(name)
      self.in_flight += 1

      for _ in range(5):
         await asyncio.sleep(0)

      self.in_flight -= 1

      if name == DOCUMENT:
         return self.document

      if name in self.answers:
         return self.answers[name]

      if name.startswith(("GET /api/", "POST /api/")):
         return json_response({"status": "ok"})

      return json_response({"data": {"companion": {}}, "extensions": {"is_final": True}})

   def named(self, name: str) -> list[Request]:
      return [request for request in self.sent if label(request) == name]


def paced(transport: InboxBurstTransport) -> tuple[PacedSender, FakeClock]:
   clock = FakeClock()
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)

   return PacedSender(transport, pacer), clock


async def load_notes(transport: InboxBurstTransport, *, companions: bool = True) -> Any:
   sender, _ = paced(transport)

   return await read_notes(
      sender, a_bootstrapped_session(), route=InboxRoute.PAGE, companions=companions
   )


def first_page_threads() -> list[dict[str, Any]]:
   mailbox = recorded("inbox_first_page.json")["data"]["get_slide_mailbox_for_iris_subscription"]

   return [edge["node"]["as_ig_direct_thread"] for edge in mailbox["threads_by_folder"]["edges"]]


def pinned_threads() -> list[dict[str, Any]]:
   mailbox = recorded("inbox_first_page.json")["data"]["get_slide_mailbox_for_iris_subscription"]

   return [item["as_ig_direct_thread"] for item in mailbox["pinned_threads_v2"]]


class RecordingCookieSync:
   def __init__(self) -> None:
      self.started: list[str] = []

   def start(
      self, session: Session, page_url: str, *, loaded_at: float, user_agent: str = ""
   ) -> None:
      self.started.append(page_url)


@pytest.mark.asyncio
async def test_an_inbox_load_sends_the_recorded_burst_in_its_groups() -> None:
   """Catches a request missing, extra, out of order or grouped unlike the recorded load, and
   ``news/inbox_seen`` or a query no inbox load sent going out with it."""

   transport = InboxBurstTransport()

   await load_notes(transport)

   assert transport.groups == INBOX_RECORDED_BURST


@pytest.mark.asyncio
async def test_the_iris_queries_carry_the_documents_device_id() -> None:
   """Catches a device id generated or stored where the document carried one."""

   transport = InboxBurstTransport()

   await load_notes(transport)

   iris_names = [DIRECT_INBOX.friendly_name, INBOX_ROWS, PENDING_ROWS, BADGE_COUNT.friendly_name]
   iris_requests = [request for name in iris_names for request in transport.named(name)]

   assert len(iris_requests) == 4
   assert {
      variables_of(request)["device_id_for_iris_subscription"] for request in iris_requests
   } == {DEVICE_ID}


@pytest.mark.asyncio
async def test_a_document_without_a_device_id_keys_the_block_on_one_fresh_id() -> None:
   """Catches the read lost with the document's id, the block split across two ids, or the badge
   count sent on an id no document issued."""

   transport = InboxBurstTransport(an_inbox_document(device_id=False))

   notes = await load_notes(transport)

   block_ids = {
      variables_of(request)["device_id_for_iris_subscription"]
      for name in (DIRECT_INBOX.friendly_name, INBOX_ROWS, PENDING_ROWS)
      for request in transport.named(name)
   }
   [fresh_id] = block_ids

   assert notes
   assert fresh_id != DEVICE_ID
   assert uuid.UUID(fresh_id).version == 4
   assert transport.named(BADGE_COUNT.friendly_name) == []


@pytest.mark.asyncio
async def test_the_thread_details_are_the_first_pages_rows_pinned_first() -> None:
   """Catches a prefetch keyed on ``thread_fbid`` instead of ``thread_key``, a row left out or
   sent twice, the pinned threads out of their own order, or a detail claiming its thread's page
   as referer."""

   transport = InboxBurstTransport()

   await load_notes(transport)

   pinned_keys = [thread["thread_key"] for thread in pinned_threads()]
   other_keys = [
      thread["thread_key"]
      for thread in first_page_threads()
      if thread["thread_key"] not in pinned_keys
   ]
   details = transport.named(THREAD_DETAIL.friendly_name)

   assert len(pinned_keys) == 2
   assert pinned_keys != [
      thread["thread_key"] for thread in first_page_threads() if thread["is_pin"]
   ]
   assert [variables_of(request)["thread_fbid"] for request in details] == [
      *pinned_keys,
      *other_keys,
   ]
   assert {request.headers["referer"] for request in details} == {INBOX_URL}


@pytest.mark.asyncio
async def test_every_request_after_the_document_names_the_inbox_as_referer() -> None:
   """Catches a query of the load claiming to come from another page."""

   transport = InboxBurstTransport()

   await load_notes(transport)

   assert {request.headers["referer"] for request in transport.sent[1:]} == {INBOX_URL}


@pytest.mark.asyncio
async def test_each_read_takes_its_own_answers_from_the_block() -> None:
   """Catches a read mapping another query's answer, such as the two folders swapped."""

   sender, _ = paced(InboxBurstTransport())
   session = a_bootstrapped_session()

   notes = await read_notes(sender, session, route=InboxRoute.PAGE, companions=True)
   page = await read_inbox_page(sender, session, route=InboxRoute.PAGE, companions=True)
   counts = await read_unread_counts(sender, session, route=InboxRoute.PAGE, companions=True)

   inbox_rows = parse_folder_unread_rows(recorded("inbox_unread_rows.json"))
   pending_rows = parse_folder_unread_rows(recorded("pending_unread_rows.json"))
   listing = parse_inbox_page(recorded("inbox_first_page.json"))

   assert notes == parse_inbox_tray(own_and_other_tray())
   assert page.items == listing.page.items
   assert page.has_next_page is listing.page.has_next_page
   assert page.end_cursor == f"{listing.mailbox_id}:{listing.page.end_cursor}"
   assert inbox_rows.has_more is not pending_rows.has_more
   assert (counts.inbox, counts.inbox_has_more) == (inbox_rows.unread, inbox_rows.has_more)
   assert (counts.pending, counts.pending_has_more) == (pending_rows.unread, pending_rows.has_more)


@pytest.mark.asyncio
async def test_a_rejected_query_nobody_reads_does_not_cost_the_read() -> None:
   """Catches a block query or companion the caller does not read failing the read, and a
   refused listing still keying thread details on nothing."""

   rejected = json_response({"errors": [{"code": 1675004, "message": "rejected"}]})
   transport = InboxBurstTransport(
      **{
         VIEWER_SETTINGS.friendly_name: rejected,
         DIRECT_INBOX.friendly_name: rejected,
         BADGE_COUNT.friendly_name: rejected,
      }
   )

   notes = await load_notes(transport)

   assert notes == parse_inbox_tray(own_and_other_tray())
   assert transport.named(THREAD_DETAIL.friendly_name) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("where", [PRESENCE_SETUP.friendly_name, ACTIVITY_FEED])
async def test_a_checkpoint_anywhere_in_the_load_is_raised(where: str) -> None:
   """Catches a checkpoint hidden because it arrived on a request whose answer is not read."""

   transport = InboxBurstTransport(**{where: json_response({"error": "challenge_required"})})

   with pytest.raises(CheckpointRequired):
      await load_notes(transport)


@pytest.mark.asyncio
async def test_the_load_is_paced_as_one_action() -> None:
   """Catches the block or a companion group waiting out its own gap, seconds where the page
   takes milliseconds."""

   transport = InboxBurstTransport()
   sender, clock = paced(transport)

   await read_notes(sender, a_bootstrapped_session(), route=InboxRoute.PAGE, companions=True)

   assert len(transport.sent) == 31
   assert clock.now == 0.0


@pytest.mark.asyncio
async def test_the_cookie_sync_starts_for_the_inbox_only_after_a_read_that_succeeded() -> None:
   """Catches the tail scheduled for another page, or scheduled after the read raised."""

   succeeded = RecordingCookieSync()
   failed = RecordingCookieSync()
   broken_tray = json_response({"data": {"response": None}, "extensions": {"is_final": True}})

   sender, _ = paced(InboxBurstTransport())
   await read_notes(
      sender,
      a_bootstrapped_session(),
      route=InboxRoute.PAGE,
      cookie_sync=succeeded,
   )

   sender, _ = paced(InboxBurstTransport(**{INBOX_TRAY.friendly_name: broken_tray}))

   with pytest.raises(SchemaChanged):
      await read_notes(
         sender,
         a_bootstrapped_session(),
         route=InboxRoute.PAGE,
         cookie_sync=failed,
      )

   assert succeeded.started == [INBOX_URL]
   assert failed.started == []


@pytest.mark.asyncio
async def test_the_core_keeps_each_reads_own_queries_unless_told_otherwise() -> None:
   """Catches the page load becoming the default below the client, where callers such as the
   probes expect the requests they had."""

   sender, _ = paced(InboxBurstTransport())
   session = a_bootstrapped_session()
   transport = sender._sender
   assert isinstance(transport, InboxBurstTransport)

   await read_notes(sender, session)
   await read_inbox_page(sender, session)
   await read_unread_counts(sender, session)

   assert transport.groups == [
      [INBOX_TRAY.friendly_name],
      [DIRECT_INBOX.friendly_name],
      [INBOX_ROWS],
      [PENDING_ROWS],
   ]


def test_parity_reads_the_inbox_from_its_page() -> None:
   """Catches the parity preset defaulting to the departure."""

   assert PARITY.inbox_route is InboxRoute.PAGE
   assert Behavior().inbox_route is InboxRoute.PAGE


SCRIPTED = replace(PARITY, cookie_sync=False)


@pytest.mark.asyncio
async def test_the_client_loads_the_inbox_for_each_of_the_three_reads() -> None:
   """Catches a namespace method that drops the setting on the way down."""

   notes = InboxBurstTransport()
   inbox = InboxBurstTransport()
   unread = InboxBurstTransport()

   await (await client_over(notes, SCRIPTED)).direct.notes()
   await (await client_over(inbox, SCRIPTED)).direct.inbox()
   await (await client_over(unread, SCRIPTED)).direct.unread_counts()

   assert notes.groups == INBOX_RECORDED_BURST
   assert inbox.groups == INBOX_RECORDED_BURST
   assert unread.groups == INBOX_RECORDED_BURST


@pytest.mark.asyncio
async def test_the_departures_send_what_they_name_and_nothing_else() -> None:
   """Catches a departure the configuration names and the client does not honour, or one that
   also drops the page's own block."""

   queries = replace(SCRIPTED, inbox_route=InboxRoute.QUERIES)
   no_companions = replace(SCRIPTED, page_load_companions=False)
   notes_alone = InboxBurstTransport()
   unread_alone = InboxBurstTransport()
   block_only = InboxBurstTransport()

   await (await client_over(notes_alone, queries)).direct.notes()
   await (await client_over(unread_alone, queries)).direct.unread_counts()
   await (await client_over(block_only, no_companions)).direct.notes()

   assert notes_alone.groups == [[INBOX_TRAY.friendly_name]]
   assert unread_alone.groups == [[INBOX_ROWS], [PENDING_ROWS]]
   assert block_only.groups == INBOX_RECORDED_BURST[:2]


def test_the_blocking_walk_reads_the_first_page_from_the_load_then_the_next_page_query() -> None:
   """Catches a walk that asks the page load again for page two, or that loses the mailbox the
   next page is keyed on when the first page came from the load."""

   transport = InboxBurstTransport()
   clock = FakeClock()

   with SyncClient(a_bootstrapped_session(), behavior=SCRIPTED) as client:
      client._loop.run(client._impl._sender.aclose(), operation="the scripted sender swap")
      client._impl._sender = PacedSender(
         transport, Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)
      )
      threads = list(client.direct.iter_inbox(limit=FIRST_PAGE_ROWS + 1))

   [next_page] = transport.named(DIRECT_INBOX_NEXT_PAGE.friendly_name)
   listing = parse_inbox_page(recorded("inbox_first_page.json"))

   assert len(threads) == FIRST_PAGE_ROWS + 1
   assert transport.groups[: len(INBOX_RECORDED_BURST)] == INBOX_RECORDED_BURST
   assert transport.groups[len(INBOX_RECORDED_BURST) :] == [[DIRECT_INBOX_NEXT_PAGE.friendly_name]]
   assert variables_of(next_page)["id"] == listing.mailbox_id
