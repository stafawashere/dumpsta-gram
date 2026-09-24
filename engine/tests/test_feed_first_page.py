"""Gates on reading the first feed page out of the home document, the way a browser does.

Four defect classes live here. The preload reader can take the wrong preloaded query, because
the home document carries five of them and only one is the feed. It can accept a result the
upstream has not finished streaming, which is a truncated page that looks complete. The router
can send the wrong request for a page, in either direction: a pagination query where parity
wants the document, or a document load for a page that needs a cursor. And the client can drop
the behavior setting on the way down, so that parity is the documented default and not the
sent one.

The documents are synthetic. They keep the nesting observed in two cold loads on 2026-09-23,
a ``ScheduledServerJS`` bootstrap array holding a ``RelayPrefetchedStreamCache`` ``next`` call,
and carry no real content. Nothing in this file touches the network.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from dumpstagram._core.feed import read_feed_page
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.web.documents.common import API_GRAPHQL_URL, GRAPHQL_QUERY_URL
from dumpstagram._private.web.preload import (
   FEED_TIMELINE_PRELOADER,
   HOME_DOCUMENT_URL,
   read_preloaded_result,
)
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY, Behavior, FeedFirstPage
from dumpstagram.errors import AuthenticationFailed, SchemaChanged, UpstreamRejected
from dumpstagram.models import FeedItemKind
from tests.test_direct import (
   APP_SHELL,
   BOOTSTRAP_PAGE,
   FB_DTSG,
   ScriptedTransport,
   a_bootstrapped_session,
   html_response,
   json_response,
   make_paced,
   sent_variables,
)
from tests.test_feed import CURSOR, item, payload

FEED_PRELOADER_ID = FEED_TIMELINE_PRELOADER + "6ab357b501e727048562648"
STORIES_PRELOADER_ID = "adp_PolarisStoriesV3TrayContainerQueryRelayPreloader_6ab357b501e7"


def stream_call(preloader_id: str, result: dict[str, Any], *, complete: bool = True) -> list[Any]:
   return [
      "RelayPrefetchedStreamCache",
      "next",
      [],
      [preloader_id, {"__bbox": {"complete": complete, "result": result, "sequence_number": 0}}],
   ]


def data_script(*calls: list[Any]) -> str:
   wrapped = {"require": [["ScheduledServerJS", "handle", None, [{"__bbox": {"require": calls}}]]]}

   return (
      '<script type="application/json" data-content-len="1" data-sjs>'
      + json.dumps(wrapped)
      + "</script>"
   )


def home_document(*scripts: str) -> str:
   return BOOTSTRAP_PAGE.replace("</html>", "".join(scripts) + "</html>")


def a_feed_document(*, end_cursor: str = CURSOR) -> str:
   stories = {"data": {"xdt_api__v1__feed__reels_tray": {"tray": []}}}
   feed = payload([item(), item("ad")], has_next_page=True, end_cursor=end_cursor)

   return home_document(
      data_script(stream_call(STORIES_PRELOADER_ID, stories)),
      data_script(stream_call(FEED_PRELOADER_ID, feed)),
   )


def test_the_reader_takes_the_feed_preload_and_not_the_one_before_it() -> None:
   """Catches a reader that returns the first stream call in the document, the stories tray."""

   result = read_preloaded_result(a_feed_document(), FEED_TIMELINE_PRELOADER)

   assert "xdt_api__v1__feed__timeline__connection" in result["data"]


def test_a_preload_the_upstream_has_not_finished_raises() -> None:
   """Catches a partly streamed page accepted as whole, which truncates the feed silently."""

   document = home_document(data_script(stream_call(FEED_PRELOADER_ID, payload(), complete=False)))

   with pytest.raises(SchemaChanged, match="complete"):
      read_preloaded_result(document, FEED_TIMELINE_PRELOADER)


def test_two_preloaded_chunks_raise_rather_than_one_being_picked() -> None:
   """Catches a reader that keeps one chunk of a streamed result and drops the rest."""

   document = home_document(
      data_script(stream_call(FEED_PRELOADER_ID, payload())),
      data_script(stream_call(FEED_PRELOADER_ID, payload())),
   )

   with pytest.raises(SchemaChanged, match="2 preloaded chunks"):
      read_preloaded_result(document, FEED_TIMELINE_PRELOADER)


def test_a_document_without_the_feed_preload_raises() -> None:
   """Catches a missing preload reported as an empty feed instead of as a changed page."""

   with pytest.raises(SchemaChanged, match="no preloaded result"):
      read_preloaded_result(home_document(), FEED_TIMELINE_PRELOADER)


@pytest.mark.asyncio
async def test_the_document_route_spends_one_navigation_and_no_query() -> None:
   """Catches parity sending the pagination query, or a bootstrap, for the first page."""

   transport = ScriptedTransport([html_response(a_feed_document(), final_url=HOME_DOCUMENT_URL)])

   page = await read_feed_page(
      make_paced(transport), a_bootstrapped_session(), first_page=FeedFirstPage.DOCUMENT
   )

   assert [(request.method, request.url) for request in transport.sent] == [
      ("GET", HOME_DOCUMENT_URL)
   ]
   assert transport.sent[0].headers["sec-fetch-mode"] == "navigate"
   assert [entry.kind for entry in page.items] == [FeedItemKind.POST, FeedItemKind.AD]
   assert page.has_next_page is True
   assert page.end_cursor == CURSOR


@pytest.mark.asyncio
async def test_the_document_route_writes_the_fresh_tokens_onto_the_session() -> None:
   """Catches a page load whose tokens are thrown away, leaving the session on older ones."""

   session = a_bootstrapped_session()
   transport = ScriptedTransport([html_response(a_feed_document(), final_url=HOME_DOCUMENT_URL)])

   await read_feed_page(make_paced(transport), session, first_page=FeedFirstPage.DOCUMENT)

   assert session.fb_dtsg == FB_DTSG


@pytest.mark.asyncio
async def test_a_logged_out_document_is_an_authentication_failure() -> None:
   """Catches a dead session reported as a changed page, which sends the user the wrong way."""

   transport = ScriptedTransport([html_response(APP_SHELL, final_url=HOME_DOCUMENT_URL)])

   with pytest.raises(AuthenticationFailed):
      await read_feed_page(
         make_paced(transport), a_bootstrapped_session(), first_page=FeedFirstPage.DOCUMENT
      )


@pytest.mark.asyncio
async def test_an_envelope_inside_the_preload_is_a_rejection() -> None:
   """Catches a preloaded error envelope read as a feed, which the mapper would then refuse."""

   rejected = {"errors": [{"code": 1675012, "message": "a server error"}], "data": None}
   document = home_document(data_script(stream_call(FEED_PRELOADER_ID, rejected)))
   transport = ScriptedTransport([html_response(document, final_url=HOME_DOCUMENT_URL)])

   with pytest.raises(UpstreamRejected) as raised:
      await read_feed_page(
         make_paced(transport), a_bootstrapped_session(), first_page=FeedFirstPage.DOCUMENT
      )

   assert raised.value.code == "1675012"


@pytest.mark.asyncio
async def test_a_page_with_a_cursor_goes_through_the_query_even_under_parity() -> None:
   """Catches a document load for page two, which would return page one again forever."""

   transport = ScriptedTransport([json_response(payload())])

   await read_feed_page(
      make_paced(transport),
      a_bootstrapped_session(),
      after=CURSOR,
      first_page=FeedFirstPage.DOCUMENT,
   )

   assert [request.url for request in transport.sent] == [GRAPHQL_QUERY_URL]
   assert sent_variables(transport.sent[0])["after"] == CURSOR


def test_parity_reads_the_first_page_from_the_document() -> None:
   """Catches the parity preset defaulting to the departure."""

   assert PARITY.feed_first_page is FeedFirstPage.DOCUMENT
   assert Behavior().feed_first_page is FeedFirstPage.DOCUMENT


async def client_over(transport: ScriptedTransport, behavior: Behavior) -> AsyncClient:
   client = AsyncClient(a_bootstrapped_session(), behavior=behavior)
   await client._sender.aclose()

   scripted: PacedSender = make_paced(transport)
   client._sender = scripted

   return client


@pytest.mark.asyncio
async def test_the_client_sends_the_document_under_the_default_behavior() -> None:
   """Catches a client that drops the behavior setting and falls back to the query."""

   page_load_companions = 3
   companion_answer = json_response({"data": {"companion": {}}})
   transport = ScriptedTransport(
      [html_response(a_feed_document(), final_url=HOME_DOCUMENT_URL)]
      + [companion_answer] * page_load_companions
   )
   client = await client_over(transport, PARITY)

   await client.feed()

   assert [request.url for request in transport.sent] == [HOME_DOCUMENT_URL] + [
      API_GRAPHQL_URL
   ] * page_load_companions


@pytest.mark.asyncio
async def test_the_client_sends_the_query_when_the_behavior_names_the_departure() -> None:
   """Catches a departure the configuration names and the client does not honour."""

   transport = ScriptedTransport([json_response(payload())])
   client = await client_over(transport, Behavior(feed_first_page=FeedFirstPage.QUERY))

   await client.feed()

   assert [request.url for request in transport.sent] == [GRAPHQL_QUERY_URL]
