"""Gates on how a thread is read: the query that opens it and the query that scrolls it.

A browser opens a thread with ``IGDThreadDetailQuery`` and reads every older page with
``IGDMessageListOffMsysQuery``. Four defects live here. The client can ignore its behavior and
open every thread with the scrolling query. An older page can stay on the retired
``useIGDMessageListPaginationQuery``, which answered on 2026-09-23 and so fails nowhere. A
top-up since a known message can be sent as a thread open, which has no marker variable and
turns every poll into a re-read of the newest page. And the detail mapper can read the
pagination query's root field, which the detail payload does not have.

The two doc_ids below are written out rather than read from the registry, so a registry edit
cannot move the expectation with it. They come from the findings ``open-a-direct-thread`` and
``direct-thread-older-page-offmsys``.

Every response is canned. Nothing in this file touches the network.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs

import pytest

from dumpstagram._core.direct import read_thread_messages
from dumpstagram._private.transport import Request
from dumpstagram._private.web.parse.direct import parse_thread_detail
from dumpstagram._private.web.requests.direct import build_thread_detail_request
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import Behavior, ThreadFirstPage
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import Message
from tests.test_direct import (
   ScriptedTransport,
   a_bootstrapped_session,
   json_response,
   make_paced,
)
from tests.test_parse import CURSOR, MESSAGE_ID, THREAD_FBID, node, payload

DETAIL_DOC_ID = "28730473946590056"
OLDER_PAGE_DOC_ID = "28079551424999855"
RETIRED_DOC_ID = "27502152406082940"


def detail_payload(nodes: list[dict[str, Any]], *, end_cursor: str | None = None) -> dict[str, Any]:
   connection = {
      "edges": [{"cursor": CURSOR, "node": entry} for entry in nodes],
      "page_info": {
         "has_next_page": True,
         "has_previous_page": False,
         "start_cursor": CURSOR,
         "end_cursor": end_cursor,
      },
   }
   thread = {"id": THREAD_FBID, "thread_fbid": THREAD_FBID, "slide_messages": connection}

   return {
      "data": {"get_slide_thread_nullable": {"as_ig_direct_thread": thread, "id": THREAD_FBID}},
      "extensions": {"is_final": True},
   }


def sent_body(request: Request) -> dict[str, str]:
   assert request.content is not None

   parsed = parse_qs(request.content.decode("utf-8"))

   return {key: values[0] for key, values in parsed.items()}


def sent_variables(request: Request) -> dict[str, Any]:
   variables: dict[str, Any] = json.loads(sent_body(request)["variables"])

   return variables


async def read_through_a_client(
   transport: ScriptedTransport,
   behavior: Behavior,
   *,
   after: str | None = None,
   newer_than_message_id: str | None = None,
) -> list[Message]:
   client = AsyncClient(a_bootstrapped_session(), behavior=behavior)
   client._sender = make_paced(transport)

   try:
      page = await client.thread_messages(
         THREAD_FBID, after=after, newer_than_message_id=newer_than_message_id
      )
   finally:
      await client.aclose()

   return list(page.items)


@pytest.mark.asyncio
async def test_a_default_client_opens_a_thread_with_the_detail_query() -> None:
   """Catches the client dropping its behavior and opening threads with the scrolling query."""

   transport = ScriptedTransport([json_response(detail_payload([node()], end_cursor=CURSOR))])

   messages = await read_through_a_client(transport, Behavior())

   request = transport.sent[0]
   body = sent_body(request)

   assert len(transport.sent) == 1
   assert body["doc_id"] == DETAIL_DOC_ID
   assert body["fb_api_req_friendly_name"] == "IGDThreadDetailQuery"
   assert request.headers["x-fb-friendly-name"] == "IGDThreadDetailQuery"
   assert request.headers["referer"] == f"https://www.instagram.com/direct/t/{THREAD_FBID}/"
   assert [message.id for message in messages] == [MESSAGE_ID]


def test_the_detail_query_carries_the_variables_a_browser_sent() -> None:
   """Catches the chat themes flag drifting to the replay template's true, which no browser sent.

   All 63 detail queries in the four 2026-09-23 captures carried these four keys in this order,
   with the flag false and ``min_uq_seq_id`` null.
   """

   request = build_thread_detail_request(a_bootstrapped_session(), THREAD_FBID)

   assert list(sent_variables(request).items()) == [
      ("min_uq_seq_id", None),
      ("thread_fbid", THREAD_FBID),
      ("__relay_internal__pv__IGDEnableOffMsysChatThemesQErelayprovider", False),
      ("__relay_internal__pv__IGDInitialMessagePageCountrelayprovider", 20),
   ]


@pytest.mark.asyncio
async def test_an_older_page_goes_through_the_query_a_browser_scrolls_with() -> None:
   """Catches an older page staying on the retired pagination doc_id, which still answers."""

   transport = ScriptedTransport([json_response(payload([node()]))])

   await read_through_a_client(transport, Behavior(), after=CURSOR)

   body = sent_body(transport.sent[0])

   assert body["doc_id"] == OLDER_PAGE_DOC_ID
   assert body["doc_id"] != RETIRED_DOC_ID
   assert body["fb_api_req_friendly_name"] == "IGDMessageListOffMsysQuery"
   assert sent_variables(transport.sent[0])["after"] == CURSOR
   assert sent_variables(transport.sent[0])["id"] == THREAD_FBID


@pytest.mark.asyncio
async def test_a_top_up_is_not_sent_as_a_thread_open() -> None:
   """Catches a newer-than read going to the detail query, which has no marker to carry."""

   transport = ScriptedTransport([json_response(payload([node()]))])

   await read_through_a_client(transport, Behavior(), newer_than_message_id=MESSAGE_ID)

   body = sent_body(transport.sent[0])

   assert body["doc_id"] == OLDER_PAGE_DOC_ID
   assert sent_variables(transport.sent[0])["newer_than_message_id"] == MESSAGE_ID


@pytest.mark.asyncio
async def test_the_query_departure_reads_the_newest_page_with_the_scrolling_query() -> None:
   """Catches ThreadFirstPage.QUERY being ignored, so the departure changes nothing."""

   transport = ScriptedTransport([json_response(payload([node()]))])

   await read_through_a_client(transport, Behavior(thread_first_page=ThreadFirstPage.QUERY))

   body = sent_body(transport.sent[0])

   assert body["doc_id"] == OLDER_PAGE_DOC_ID
   assert sent_variables(transport.sent[0])["after"] is None


@pytest.mark.asyncio
async def test_the_capability_keeps_the_scrolling_query_as_its_own_default() -> None:
   """Catches the core default flipping, which silently reroutes every caller below the client."""

   transport = ScriptedTransport([json_response(payload([node()]))])

   await read_thread_messages(make_paced(transport), a_bootstrapped_session(), THREAD_FBID)

   assert sent_body(transport.sent[0])["doc_id"] == OLDER_PAGE_DOC_ID


def test_the_detail_mapper_reads_the_detail_root_and_keeps_the_cursor() -> None:
   """Catches the detail mapper reading fetch__SlideThread, which a detail payload lacks."""

   page = parse_thread_detail(detail_payload([node()], end_cursor=CURSOR))

   assert [message.id for message in page.items] == [MESSAGE_ID]
   assert page.has_next_page is True
   assert page.end_cursor == CURSOR


def test_a_null_thread_raises_rather_than_reading_as_an_empty_thread() -> None:
   """Catches a null detail root mapped to an empty page, a silent answer for an unseen shape."""

   with pytest.raises(SchemaChanged) as raised:
      parse_thread_detail({"data": {"get_slide_thread_nullable": None}})

   assert raised.value.path == "data.get_slide_thread_nullable.as_ig_direct_thread"
