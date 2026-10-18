"""Gates on the mark read a thread open is followed by, release phase 2 item 3.

A browser with a thread open in a visible tab marks it read with
``useIGDMarkThreadAsReadMutation`` and, 2 ms later, ``useIGDMarkThreadAsReadValidationMutation``
(findings ``mark-a-direct-thread-read`` and ``mark-a-direct-thread-read-validation``, replayed by
the engine on 2026-10-18, log ``engine/logs/viewer-identity-mark-read-2026-10-18-043558.json``).

Six defects live here. A thread already read can be marked again, a write nobody needed that
other people see. A scroll or a top-up can mark, which a browser's scroll does not. The setting
can be ignored. The mark can skip the write path, so it escapes the budget and the stop. The
mark can name the wrong message, the first on the page rather than the newest. And a failed mark
can resend the read or itself.

The two doc_ids are written out rather than read from the registry, so a registry edit cannot
move the expectation with it. Every response is canned. Nothing in this file touches the network.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from dumpstagram._private.web.parse.direct import parse_thread_read_state
from dumpstagram._private.web.requests.direct import (
   build_mark_thread_read_request,
   build_mark_thread_read_validation_request,
)
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import Behavior, ThreadFirstPage
from dumpstagram.client import SyncClient
from dumpstagram.errors import RateLimited, UpstreamRejected
from dumpstagram.models import Message
from tests.test_direct import ScriptedTransport, a_bootstrapped_session, json_response, make_paced
from tests.test_parse import THREAD_FBID, node, payload
from tests.test_thread_route import (
   THREAD_ID,
   VIEWER_MESSAGING_FBID,
   detail_payload,
   sent_body,
   sent_variables,
)

MARK_DOC_ID = "27399783383056109"
VALIDATION_DOC_ID = "35211594988486314"

DETAIL = "IGDThreadDetailQuery"
MARK = "useIGDMarkThreadAsReadMutation"
VALIDATION = "useIGDMarkThreadAsReadValidationMutation"
SCROLLING = "IGDMessageListOffMsysQuery"

OLDER_MS = 1_758_412_300_000
NEWEST_MS = 1_758_412_345_678

NO_SPACING = Behavior(write_spacing=replace(Behavior().write_spacing, floor_seconds=0.0))


def unread_open(**overrides: Any) -> dict[str, Any]:
   """A thread open whose newest message is listed second and is past the viewer's receipt."""

   nodes = [
      node(id="mid.$older", message_id="mid.$older", timestamp_ms=str(OLDER_MS)),
      node(id="mid.$newest", message_id="mid.$newest", timestamp_ms=str(NEWEST_MS)),
   ]

   return detail_payload(nodes, read_to_ms=OLDER_MS, **overrides)


def receipt() -> dict[str, Any]:
   return {
      "data": {
         "xig_direct_item_seen_mutation_with_slide_messaging_response": {
            "__typename": "XFBSlideReadReceipt",
            "participant_eimu_id": VIEWER_MESSAGING_FBID,
            "watermark_timestamp_ms": str(NEWEST_MS),
         }
      },
      "extensions": {"is_final": True},
   }


def validated(answer: bool = True) -> dict[str, Any]:
   return {"data": {"xig_direct_mark_read_id_validation": answer}, "extensions": {"is_final": True}}


def names(transport: ScriptedTransport) -> list[str]:
   return [request.headers.get("x-fb-friendly-name", "document") for request in transport.sent]


async def read(
   responses: list[dict[str, Any]],
   behavior: Behavior = NO_SPACING,
   **arguments: Any,
) -> tuple[ScriptedTransport, list[Message], AsyncClient]:
   transport = ScriptedTransport([json_response(answer) for answer in responses])
   client = AsyncClient(a_bootstrapped_session(), behavior=behavior)
   await client._sender.aclose()
   paced = make_paced(transport)
   client._sender = type(paced)(
      transport, paced.pacer, client._sender.pacing, client._sender.writes
   )

   try:
      page = await client.direct.messages(THREAD_FBID, **arguments)
   finally:
      await client.aclose()

   return transport, list(page.items), client


@pytest.mark.asyncio
async def test_an_unread_thread_open_is_marked_read_at_its_newest_message() -> None:
   """Catches the mark naming the first message on the page, or the wrong thread id."""

   transport, messages, _ = await read([unread_open(), receipt(), validated()])

   assert names(transport) == [DETAIL, MARK, VALIDATION]
   assert [message.id for message in messages] == ["mid.$older", "mid.$newest"]

   mark, validation = transport.sent[1], transport.sent[2]

   assert sent_body(mark)["doc_id"] == MARK_DOC_ID
   assert sent_variables(mark) == {
      "metadata": {"ig_thread_igid": THREAD_ID},
      "data": {"item_id": "", "message_id": "mid.$newest"},
   }
   assert sent_body(validation)["doc_id"] == VALIDATION_DOC_ID
   assert sent_variables(validation) == {
      "metadata": {"ig_thread_igid": THREAD_ID},
      "data": {"message_id": "mid.$newest", "message_timestamp_ms": str(NEWEST_MS)},
   }
   assert mark.headers["referer"] == f"https://www.instagram.com/direct/t/{THREAD_FBID}/"


@pytest.mark.asyncio
async def test_a_thread_already_read_sends_nothing_more() -> None:
   """Catches a mark on every open, a visible write nobody needed."""

   transport, _, _ = await read([detail_payload([node()])])

   assert names(transport) == [DETAIL]


@pytest.mark.asyncio
async def test_a_thread_marked_unread_by_hand_is_marked_read() -> None:
   """Catches the marked unread flag ignored when the receipt is already at the newest."""

   marked_unread = detail_payload([node()])
   marked_unread["data"]["get_slide_thread_nullable"]["as_ig_direct_thread"]["marked_as_unread"] = (
      True
   )

   transport, _, _ = await read([marked_unread, receipt(), validated()])

   assert names(transport) == [DETAIL, MARK, VALIDATION]


@pytest.mark.asyncio
async def test_the_setting_off_reads_an_unread_thread_without_marking() -> None:
   transport, _, _ = await read([unread_open()], replace(NO_SPACING, mark_threads_read=False))

   assert names(transport) == [DETAIL]


@pytest.mark.asyncio
async def test_an_older_page_never_marks() -> None:
   """Catches a scroll marking, which a browser's scroll does not."""

   transport, _, _ = await read([payload([node()])], after="cursor")

   assert names(transport) == [SCROLLING]


@pytest.mark.asyncio
async def test_the_scrolling_route_for_the_newest_page_never_marks() -> None:
   """Catches the QUERY route marking, though it opens nothing."""

   behavior = replace(NO_SPACING, thread_first_page=ThreadFirstPage.QUERY)

   transport, _, _ = await read([payload([node()])], behavior)

   assert names(transport) == [SCROLLING]


@pytest.mark.asyncio
async def test_the_mark_is_a_write_and_the_budget_refuses_it() -> None:
   """Catches the mark sent around the write path, past the budget and the stop."""

   with pytest.raises(RateLimited):
      await read([unread_open()], replace(NO_SPACING, write_budget_per_hour=0))


@pytest.mark.asyncio
async def test_the_mark_departs_once_through_the_write_slot() -> None:
   _, _, client = await read([unread_open(), receipt(), validated()])

   assert len(client._sender.pacer._departed_write_tokens) == 1


@pytest.mark.asyncio
async def test_a_mark_answered_without_a_receipt_raises_and_sends_nothing_after_it() -> None:
   """Catches an answer with no receipt taken as marked, and the read or mark sent again."""

   empty = {"data": {"xig_direct_item_seen_mutation_with_slide_messaging_response": None}}
   transport = ScriptedTransport([json_response(unread_open()), json_response(empty)])
   client = AsyncClient(a_bootstrapped_session(), behavior=NO_SPACING)
   await client._sender.aclose()
   paced = make_paced(transport)
   client._sender = type(paced)(
      transport, paced.pacer, client._sender.pacing, client._sender.writes
   )

   try:
      with pytest.raises(UpstreamRejected) as raised:
         await client.direct.messages(THREAD_FBID)
   finally:
      await client.aclose()

   assert raised.value.code == "thread_not_marked_read"
   assert names(transport) == [DETAIL, MARK]


def test_the_sync_surface_marks_as_the_async_one_does() -> None:
   transport = ScriptedTransport(
      [json_response(answer) for answer in (unread_open(), receipt(), validated())]
   )

   with SyncClient(a_bootstrapped_session(), behavior=NO_SPACING) as client:
      paced = make_paced(transport)
      inner = client._impl
      inner._sender = type(paced)(
         transport, paced.pacer, inner._sender.pacing, inner._sender.writes
      )
      client.direct.messages(THREAD_FBID)

   assert names(transport) == [DETAIL, MARK, VALIDATION]


def test_the_read_state_takes_the_newest_message_by_time_not_position() -> None:
   state = parse_thread_read_state(unread_open())

   assert state.thread_id == THREAD_ID
   assert state.is_unread is True
   assert state.newest_message_id == "mid.$newest"
   assert state.newest_sent_ms == NEWEST_MS


def test_both_requests_carry_the_variables_the_browser_sent_in_its_order() -> None:
   session = a_bootstrapped_session()

   mark = build_mark_thread_read_request(session, THREAD_FBID, THREAD_ID, "mid.$m")
   validation = build_mark_thread_read_validation_request(
      session, THREAD_FBID, THREAD_ID, "mid.$m", NEWEST_MS
   )

   assert list(sent_variables(mark)) == ["metadata", "data"]
   assert list(sent_variables(mark)["data"]) == ["item_id", "message_id"]
   assert list(sent_variables(validation)["data"]) == ["message_id", "message_timestamp_ms"]
   assert sent_body(mark)["fb_api_req_friendly_name"] == MARK
   assert sent_body(validation)["fb_api_req_friendly_name"] == VALIDATION
