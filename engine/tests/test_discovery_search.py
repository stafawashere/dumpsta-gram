"""Gates on E2 batch 11b: the reels feed, the search box's personalised typeahead, and the
keyword grid that is also a hashtag's page.

Four defect classes live here.

A reel can be read into the wrong fields. The feed's reel is the timeline's post with keys left
out and two in another shape, so a mapper that fills them with anything but what W101 rules
invents a fact: a paid partnership, a collaborator, a track's mute flag.

The reels cursor can lose its state. The next page names the reels already shown, so a cursor that
drops them, names another page's reels, or is accepted from another read asks the upstream a
question the browser never asks.

A search can be sent on the wrong route or read out of order. The personalised typeahead is the
default and the non-profiled one the departure, the blended rows are ordered by the upstream's
own position, and each search is a fresh session with an empty rank token.

The keyword grid can lose posts. Its posts are nested in rows among rows that carry nothing, so a
row of another kind skipped silently would drop posts nobody sees go.

The payloads are the recorded answers of 2026-09-27, pseudonymised by
``scripts/build_discovery_search_fixtures.py``. Nothing in this file touches the network.
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import pytest

from dumpstagram._cli.main import main
from dumpstagram._core.discovery import read_reels_feed_page
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.search import read_keyword_results, read_personalised_typeahead
from dumpstagram._private.web.parse.discovery import parse_reels_feed_page
from dumpstagram._private.web.parse.search import (
   parse_keyword_results,
   parse_non_personalised_typeahead,
   parse_personalised_typeahead,
)
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY, Behavior, TypeaheadRoute
from dumpstagram.client import SyncClient
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import (
   KeywordResults,
   Page,
   Post,
   ProfileSummary,
   SearchPost,
   SearchResultKind,
   SearchResults,
)
from dumpstagram.session import Session
from tests.test_direct import (
   FakeClock,
   ScriptedTransport,
   a_bootstrapped_session,
   json_response,
   make_paced,
   sent_variables,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "discovery_search"
SEARCH_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "search"

GRAPHQL_QUERY = "https://www.instagram.com/graphql/query"
API_GRAPHQL = "https://www.instagram.com/api/graphql"
SITE_ROOT = "https://www.instagram.com/"
REELS_PAGE = "https://www.instagram.com/reels/"
REELS_ROOT = "xdt_api__v1__clips__home__connection_v2"
TYPEAHEAD_ROOT = "xdt_api__v1__fbsearch__topsearch_connection"
KEYWORD_ROOT = "xdt_fbsearch__top_serp_graphql"
REELS_FIRST_DOC_ID = "38583065568003775"
REELS_NEXT_DOC_ID = "28230813126620480"
TYPEAHEAD_DOC_ID = "27706427925724183"
KEYWORD_DOC_ID = "37324993597144881"
RECO_DEBUG = "__relay_internal__pv__PolarisReelsRecoDebugOverlayEnabledrelayprovider"
SHORT_DRAMA = "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider"
UUID4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
A_QUERY = "a query"
A_TAG_QUERY = "#some_tag"

SCRIPTED_BEHAVIOR = replace(PARITY, cookie_sync=False)
NON_PERSONALISED = replace(SCRIPTED_BEHAVIOR, typeahead_route=TypeaheadRoute.NON_PERSONALISED)


def recorded(name: str) -> Any:
   return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def recorded_non_personalised() -> Any:
   return json.loads(
      (SEARCH_FIXTURES / "non_personalised_typeahead.json").read_text(encoding="utf-8")
   )


def reel_media(answer: Any) -> list[dict[str, Any]]:
   return [edge["node"]["media"] for edge in answer["data"][REELS_ROOT]["edges"]]


def upstream_cursor(answer: Any) -> str:
   cursor: str = answer["data"][REELS_ROOT]["page_info"]["end_cursor"]

   return cursor


def grid_items(answer: Any) -> list[dict[str, Any]]:
   return [
      item
      for edge in answer["data"][KEYWORD_ROOT]["edges"]
      for item in edge["node"].get("items") or []
   ]


def sent_field(request: Any, name: str) -> str:
   return parse_qs(request.content.decode("utf-8"))[name][0]


def friendly_names(requests: list[Any]) -> list[str]:
   return [sent_field(request, "fb_api_req_friendly_name") for request in requests]


def paced(transport: ScriptedTransport, client: AsyncClient) -> PacedSender:
   clock = FakeClock()
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)

   return PacedSender(transport, pacer, client._sender.pacing, client._sender.writes)


async def scripted_client(transport: ScriptedTransport, behavior: Behavior) -> AsyncClient:
   client = AsyncClient(a_bootstrapped_session(), behavior=behavior)
   await client._sender.aclose()
   client._sender = paced(transport, client)

   return client


def test_a_reels_page_maps_every_reel_with_what_the_feed_leaves_out_read_as_ruled() -> None:
   """Catches a reel read from the edge rather than its ``media``, a reel dropped or reordered, an
   absent partnership flag or seen flag read as anything but False, a partnership flag the reel
   does send overwritten, the id-only collaborators read as accounts, and the upstream's own
   cursor and flag lost."""

   answer = recorded("reels_first_page.json")
   media = reel_media(answer)
   media[1]["is_paid_partnership"] = True

   page = parse_reels_feed_page(answer)
   first, second = page.items

   assert all(isinstance(reel, Post) for reel in page.items)
   assert [reel.pk for reel in page.items] == [node["pk"] for node in media]
   assert [reel.code for reel in page.items] == [node["code"] for node in media]
   assert [reel.author.username for reel in page.items] == [
      node["user"]["username"] for node in media
   ]
   assert [reel.product_type for reel in page.items] == ["clips", "clips"]
   assert (first.is_seen, second.is_seen) == (False, False)
   assert (first.is_paid_partnership, second.is_paid_partnership) == (False, True)
   assert media[0]["coauthor_producers"]
   assert first.collaborators is None
   assert first.user_tags is not None
   assert len(first.user_tags) == 1
   assert first.author.hd_profile_pic_url is None
   assert all(reel.video_duration is not None for reel in page.items)
   assert page.has_next_page is True
   assert page.end_cursor == upstream_cursor(answer)


def test_an_original_sound_without_its_mute_flag_is_no_audio_and_a_song_is_read() -> None:
   """Catches an original sound read with a guessed mute flag, a sound that does carry the flag
   dropped anyway, and a song dropped with them."""

   first_page = recorded("reels_first_page.json")
   next_page = parse_reels_feed_page(recorded("reels_next_page.json"))
   sound = reel_media(first_page)[0]["clips_metadata"]["original_sound_info"]

   assert "should_mute_audio" not in sound
   assert parse_reels_feed_page(first_page).items[0].audio is None

   sound["should_mute_audio"] = True
   audio = parse_reels_feed_page(first_page).items[0].audio

   assert audio is not None
   assert audio.kind.value == "original_sound_info"
   assert audio.should_mute is True
   assert next_page.items[-1].audio is not None
   assert next_page.items[-1].audio.kind.value == "music_info"


@pytest.mark.asyncio
async def test_the_first_reels_page_is_the_tabs_query_with_its_constants() -> None:
   """The parity gate for the first page. Catches another query or path, another page size, a
   provider flag dropped, the variables out of the browser's order, and another referer."""

   transport = ScriptedTransport([json_response(recorded("reels_first_page.json"))])

   await read_reels_feed_page(make_paced(transport), a_bootstrapped_session())
   request = transport.sent[0]
   variables = sent_variables(request)

   assert request.url == GRAPHQL_QUERY
   assert sent_field(request, "doc_id") == REELS_FIRST_DOC_ID
   assert sent_field(request, "fb_api_req_friendly_name") == "PolarisClipsTabDesktopContainerQuery"
   assert request.headers["x-root-field-name"] == REELS_ROOT
   assert request.headers["referer"] == REELS_PAGE
   assert variables == {
      "data": {"container_module": "clips_tab_desktop_page"},
      "first": 2,
      "useChannelsPagination": False,
      RECO_DEBUG: False,
      SHORT_DRAMA: False,
   }
   assert list(variables) == ["data", "first", "useChannelsPagination", RECO_DEBUG, SHORT_DRAMA]


@pytest.mark.asyncio
async def test_the_next_reels_page_names_the_reels_the_page_before_it_showed() -> None:
   """The W101 gate. Catches a next page sent without the previous page's reels, with another
   page's reels, with ``seen_reels`` as an object rather than a JSON string, on the cursor the
   engine hands out rather than the upstream's, and a cursor that does not carry its own page's
   reels forward."""

   first_answer = recorded("reels_first_page.json")
   next_answer = recorded("reels_next_page.json")
   transport = ScriptedTransport([json_response(first_answer), json_response(next_answer)])
   sender = make_paced(transport)
   session = a_bootstrapped_session()

   first = await read_reels_feed_page(sender, session)
   second = await read_reels_feed_page(sender, session, after=first.end_cursor)
   request = transport.sent[1]
   variables = sent_variables(request)
   shown = [reel.pk for reel in first.items]

   assert sent_field(request, "doc_id") == REELS_NEXT_DOC_ID
   assert request.url == GRAPHQL_QUERY
   assert request.headers["referer"] == REELS_PAGE
   assert variables == {
      "after": upstream_cursor(first_answer),
      "before": None,
      "data": {
         "container_module": "clips_tab_desktop_page",
         "seen_reels": json.dumps([{"id": pk} for pk in shown], separators=(",", ":")),
      },
      "first": 10,
      "last": None,
      RECO_DEBUG: False,
      SHORT_DRAMA: False,
   }
   assert list(variables) == ["after", "before", "data", "first", "last", RECO_DEBUG, SHORT_DRAMA]
   assert second.end_cursor is not None
   assert second.end_cursor.endswith(upstream_cursor(next_answer))
   assert all(reel.pk in second.end_cursor for reel in second.items)
   assert not any(pk in second.end_cursor for pk in shown)


@pytest.mark.asyncio
@pytest.mark.parametrize("cursor", ["", "abc", ":", "123:", "12a:abc", "1,,2:abc", "a-cursor"])
async def test_a_cursor_no_reels_page_handed_out_is_refused_before_anything_is_sent(
   cursor: str,
) -> None:
   """Catches another read's cursor, or a broken one, reaching the next page query, where the
   upstream would be asked about reels nobody was shown."""

   transport = ScriptedTransport([])

   with pytest.raises(ValueError, match="reels cursor"):
      await read_reels_feed_page(make_paced(transport), a_bootstrapped_session(), after=cursor)

   assert transport.sent == []


@pytest.mark.asyncio
async def test_the_async_reels_walk_reads_the_next_page_query_after_the_first() -> None:
   """Catches ``iter_reels`` walking the first page query twice, or stopping after the first
   page while the upstream says more exist."""

   last_page = recorded("reels_next_page.json")
   last_page["data"][REELS_ROOT]["page_info"]["has_next_page"] = False
   transport = ScriptedTransport(
      [json_response(recorded("reels_first_page.json")), json_response(last_page)]
   )
   client = await scripted_client(transport, SCRIPTED_BEHAVIOR)

   try:
      reels = [reel async for reel in client.feeds.iter_reels(limit=None)]
   finally:
      await client.aclose()

   assert len(reels) == 6
   assert friendly_names(transport.sent) == [
      "PolarisClipsTabDesktopContainerQuery",
      "PolarisClipsTabDesktopPaginationQuery",
   ]


def test_the_blocking_reels_walk_answers_as_its_async_twin() -> None:
   """The same walk on the blocking surface, each page read on the loop thread."""

   transport = ScriptedTransport(
      [
         json_response(recorded("reels_first_page.json")),
         json_response(recorded("reels_next_page.json")),
      ]
   )

   with SyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR) as client:
      client._loop.run(client._impl._sender.aclose(), operation="the scripted sender swap")
      client._impl._sender = paced(transport, client._impl)
      reels = list(client.feeds.iter_reels(limit=4))

   assert len(reels) == 4
   assert sent_variables(transport.sent[1])["after"] == upstream_cursor(
      recorded("reels_first_page.json")
   )


def test_the_personalised_typeahead_orders_its_rows_by_the_upstreams_position() -> None:
   """Catches rows kept in list order rather than by ``position``, an account or a keyword read
   from another key, and a hashtag or place row dropped or given a payload it was never seen
   to carry."""

   answer = recorded("personalised_typeahead.json")
   root = answer["data"][TYPEAHEAD_ROOT]
   users = root["users"]
   keyword_row = root["see_more"]["list"][0]
   keyword_row["position"] = 3
   positions = [0, 1, 2, 4, 5]

   for user, position in zip(users, positions, strict=True):
      user["position"] = position

   root["hashtags"] = [{"position": 6, "hashtag": {"name": "unread"}}]
   root["places"] = [{"position": 7, "place": {"title": "unread"}}]

   results = parse_personalised_typeahead(answer)
   kinds = [result.kind for result in results.results]

   assert isinstance(results, SearchResults)
   assert kinds == [
      SearchResultKind.ACCOUNT,
      SearchResultKind.ACCOUNT,
      SearchResultKind.ACCOUNT,
      SearchResultKind.KEYWORD,
      SearchResultKind.ACCOUNT,
      SearchResultKind.ACCOUNT,
      SearchResultKind.HASHTAG,
      SearchResultKind.PLACE,
   ]
   assert [result.position for result in results.results] == [0, 1, 2, 3, 4, 5, None, None]
   assert results.results[3].keyword == keyword_row["keyword"]["name"]
   assert [result.account.id for result in results.results if result.account is not None] == [
      user["user"]["pk"] for user in users
   ]
   assert results.results[-1].account is None
   assert results.results[-1].keyword is None


@pytest.mark.asyncio
async def test_the_personalised_typeahead_is_the_first_query_of_a_fresh_search_session() -> None:
   """The parity gate for the personalised typeahead. Catches another query or path, a constant
   renamed or retyped, ``include_reel`` sent as a boolean, a rank token sent, one session id
   reused across searches, a session id not a lowercase uuid4, and another referer."""

   answer = recorded("personalised_typeahead.json")
   transport = ScriptedTransport([json_response(answer), json_response(answer)])
   sender = make_paced(transport)
   session = a_bootstrapped_session()

   await read_personalised_typeahead(sender, session, A_QUERY)
   await read_personalised_typeahead(sender, session, A_QUERY)
   first, second = (sent_variables(request) for request in transport.sent)
   session_id = first["data"]["search_session_id"]

   assert [request.url for request in transport.sent] == [API_GRAPHQL, API_GRAPHQL]
   assert sent_field(transport.sent[0], "doc_id") == TYPEAHEAD_DOC_ID
   assert transport.sent[0].headers["referer"] == SITE_ROOT
   assert "x-root-field-name" not in transport.sent[0].headers
   assert first == {
      "data": {
         "context": "blended",
         "include_reel": "true",
         "query": A_QUERY,
         "rank_token": "",
         "search_session_id": session_id,
         "search_surface": "web_top_search",
      },
      "hasQuery": True,
   }
   assert list(first["data"]) == [
      "context",
      "include_reel",
      "query",
      "rank_token",
      "search_session_id",
      "search_surface",
   ]
   assert UUID4.fullmatch(session_id)
   assert second["data"]["search_session_id"] != session_id


@pytest.mark.asyncio
async def test_accounts_and_top_send_the_personalised_query_unless_the_route_departs() -> None:
   """The W102 gate. Catches the default left on the non-profiled query, the setting ignored by
   either method, ``accounts`` returning the keyword row or the rows out of the box's order, and
   the departure's accounts given a position its answer does not carry."""

   personalised = recorded("personalised_typeahead.json")
   transport = ScriptedTransport([json_response(personalised), json_response(personalised)])
   client = await scripted_client(transport, SCRIPTED_BEHAVIOR)

   try:
      accounts = await client.search.accounts(A_QUERY)
      top = await client.search.top(A_QUERY)
   finally:
      await client.aclose()

   departing = ScriptedTransport(
      [json_response(recorded_non_personalised()), json_response(recorded_non_personalised())]
   )
   departed = await scripted_client(departing, NON_PERSONALISED)

   try:
      departed_accounts = await departed.search.accounts(A_QUERY)
      departed_top = await departed.search.top(A_QUERY)
   finally:
      await departed.aclose()

   users = personalised["data"][TYPEAHEAD_ROOT]["users"]

   assert PARITY.typeahead_route is TypeaheadRoute.PERSONALISED
   assert friendly_names(transport.sent) == ["PolarisSearchBoxRefetchableQuery"] * 2
   assert [account.id for account in accounts] == [user["user"]["pk"] for user in users]
   assert [result.kind for result in top.results][0] is SearchResultKind.KEYWORD
   assert len(top.results) == 6
   assert friendly_names(departing.sent) == ["PolarisSearchBoxNonProfiledRefetchableQuery"] * 2
   assert len(departed_accounts) == 18
   assert [result.account for result in departed_top.results] == list(departed_accounts)
   assert {result.position for result in departed_top.results} == {None}


def test_the_keyword_grid_maps_every_post_of_its_grid_rows_in_order() -> None:
   """Catches a post dropped or reordered, a grid row read as a header row, a field read from
   another key, a video's length or view count lost, and the grid's own flag dropped."""

   answer = recorded("keyword_results.json")
   items = grid_items(answer)
   items[0].update(like_count=11, comment_count=7)
   answer["data"][KEYWORD_ROOT]["page_info"]["has_next_page"] = False

   grid = parse_keyword_results(answer)
   first = grid.posts[0]

   assert isinstance(grid, KeywordResults)
   assert all(isinstance(post, SearchPost) for post in grid.posts)
   assert [post.pk for post in grid.posts] == [item["pk"] for item in items]
   assert [post.author.username for post in grid.posts] == [
      item["user"]["username"] for item in items
   ]
   assert [post.media_type for post in grid.posts] == [2, 8, 1, 8, 2, 2, 8, 8, 8]
   assert [post.carousel_media_count for post in grid.posts] == [
      item["carousel_media_count"] for item in items
   ]
   assert (first.like_count, first.comment_count) == (11, 7)
   assert first.video_duration is not None
   assert grid.posts[2].video_duration is None
   assert [post.view_count for post in grid.posts][4:6] == [0, 0]
   assert grid.posts[0].view_count is None
   assert grid.has_more is False
   assert parse_keyword_results(recorded("keyword_results.json")).has_more is True


@pytest.mark.parametrize(
   "unit",
   [
      {"__typename": "XDTTopSerpUnseenUnit", "items": []},
      {"__typename": "XDTTopSerpHeaderUnit", "title": "a header with text"},
   ],
)
def test_a_keyword_row_of_another_kind_or_a_filled_empty_row_raises(unit: dict[str, Any]) -> None:
   """Catches a row this version cannot read skipped silently, which would drop any post it
   held."""

   answer = recorded("keyword_results.json")
   answer["data"][KEYWORD_ROOT]["edges"].insert(0, {"node": unit, "cursor": None})

   with pytest.raises(SchemaChanged, match="row this version does not read"):
      parse_keyword_results(answer)


@pytest.mark.asyncio
async def test_the_keyword_grid_is_the_pages_query_with_one_session_id_sent_twice() -> None:
   """The parity gate for the keyword grid. Catches another query or path, two different
   session ids, a ``first`` or ``after`` the browser did not send, a ``#`` unescaped in the
   referer, and a blank query sent."""

   transport = ScriptedTransport([json_response(recorded("keyword_results.json"))])
   sender = make_paced(transport)
   session = a_bootstrapped_session()

   await read_keyword_results(sender, session, A_TAG_QUERY)
   request = transport.sent[0]
   variables = sent_variables(request)

   assert request.url == API_GRAPHQL
   assert sent_field(request, "doc_id") == KEYWORD_DOC_ID
   assert variables == {
      "query": A_TAG_QUERY,
      "search_session_id": variables["search_session_id"],
      "serp_session_id": variables["search_session_id"],
   }
   assert list(variables) == ["query", "search_session_id", "serp_session_id"]
   assert UUID4.fullmatch(variables["search_session_id"])
   assert request.headers["referer"] == (
      "https://www.instagram.com/explore/search/keyword/?q=%23some_tag"
   )

   for blank in ("", "   "):
      with pytest.raises(ValueError, match="query text"):
         await read_keyword_results(sender, session, blank)

      with pytest.raises(ValueError, match="query text"):
         await read_personalised_typeahead(sender, session, blank)

   assert len(transport.sent) == 1


def test_the_blocking_search_reads_answer_as_their_async_twins() -> None:
   """The two new search reads on the blocking surface, each on the loop thread."""

   transport = ScriptedTransport(
      [
         json_response(recorded("personalised_typeahead.json")),
         json_response(recorded("keyword_results.json")),
      ]
   )

   with SyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR) as client:
      client._loop.run(client._impl._sender.aclose(), operation="the scripted sender swap")
      client._impl._sender = paced(transport, client._impl)
      top = client.search.top(A_QUERY)
      grid = client.search.keyword(A_QUERY)

   assert len(top.results) == 6
   assert len(grid.posts) == 9
   assert friendly_names(transport.sent) == [
      "PolarisSearchBoxRefetchableQuery",
      "PolarisKeywordSearchExplorePageRelayQuery",
   ]


class FakeFeeds:
   def __init__(self, pages: list[Page[Post]]) -> None:
      self.pages = pages
      self.cursors: list[str | None] = []

   def reels(self, *, after: str | None = None) -> Page[Post]:
      self.cursors.append(after)

      return self.pages[len(self.cursors) - 1]


class FakeSearch:
   def __init__(self, route: TypeaheadRoute) -> None:
      self.route = route
      self.asked: list[tuple[str, str, TypeaheadRoute]] = []

   def accounts(self, query: str) -> tuple[ProfileSummary, ...]:
      self.asked.append(("accounts", query, self.route))

      return parse_non_personalised_typeahead(recorded_non_personalised())

   def top(self, query: str) -> SearchResults:
      self.asked.append(("top", query, self.route))

      return parse_personalised_typeahead(recorded("personalised_typeahead.json"))

   def keyword(self, query: str) -> KeywordResults:
      self.asked.append(("keyword", query, self.route))

      return parse_keyword_results(recorded("keyword_results.json"))


class FakeClient:
   def __init__(
      self, pages: list[Page[Post]] | None = None, behavior: Behavior = SCRIPTED_BEHAVIOR
   ) -> None:
      self.session = Session(sessionid="s", ds_user_id="1234567890", csrftoken="c")
      self.behavior = behavior
      self.feeds = FakeFeeds(pages or [])
      self.search = FakeSearch(behavior.typeahead_route)
      self.closed = False
      self.derived: list[FakeClient] = []

   def with_behavior(self, behavior: Behavior) -> FakeClient:
      twin = FakeClient(behavior=behavior)
      twin.search.asked = self.search.asked
      self.derived.append(twin)

      return twin

   def close(self) -> None:
      self.closed = True


def run_command(argv: list[str], client: FakeClient) -> tuple[int, str]:
   out = io.StringIO()

   def factory(path: Path, *, user_agent: str | None = None) -> Any:
      return client

   try:
      code = main(
         ["--session", "unused.json", *argv],
         environment={},
         client_factory=factory,
         stdout=out,
         stderr=io.StringIO(),
      )
   except SystemExit as exited:
      code = int(exited.code or 0)

   return code, out.getvalue()


def recorded_reels_pages() -> list[Page[Post]]:
   first = parse_reels_feed_page(recorded("reels_first_page.json"))
   second = parse_reels_feed_page(recorded("reels_next_page.json"))

   return [replace(first, end_cursor="1:first"), replace(second, has_next_page=False)]


def test_dumpsta_reels_reads_pages_until_the_terminator_passing_each_cursor() -> None:
   """Catches the command passing its first cursor again, reading past a last page when
   ``--pages`` allows more, and a reel or the terminator left out of either form."""

   client = FakeClient(recorded_reels_pages())
   code, out = run_command(["--json", "reels", "--pages", "5"], client)
   _, text = run_command(["reels", "--pages", "5"], FakeClient(recorded_reels_pages()))
   payload = json.loads(out)

   assert code == 0
   assert client.feeds.cursors == [None, "1:first"]
   assert payload["command"] == "reels"
   assert (payload["pages_read"], payload["reel_count"], payload["more_available"]) == (
      2,
      6,
      False,
   )
   assert payload["reels"][0]["product_type"] == "clips"
   assert text.strip().splitlines()[-1] == "pages: 2  reels: 6  more_available: False"
   assert client.closed


def test_dumpsta_search_top_and_keyword_print_everything_read_on_the_chosen_route() -> None:
   """Catches ``search-top`` or ``keyword`` reading another method, a row or a post left out, the
   query not passed through, and ``--non-personalised`` ignored by ``search`` or ``search-top``."""

   top_client = FakeClient()
   _, top_out = run_command(["--json", "search-top", A_QUERY], top_client)
   _, top_text = run_command(["search-top", A_QUERY], FakeClient())
   keyword_client = FakeClient()
   _, keyword_out = run_command(["--json", "keyword", A_TAG_QUERY], keyword_client)
   departing = FakeClient()
   run_command(["search-top", "--non-personalised", A_QUERY], departing)
   run_command(["search", "--non-personalised", A_QUERY], departing)

   top = json.loads(top_out)
   keyword = json.loads(keyword_out)

   assert top_client.search.asked == [("top", A_QUERY, TypeaheadRoute.PERSONALISED)]
   assert (top["command"], top["query"], top["result_count"]) == ("search-top", A_QUERY, 6)
   assert top["kinds"] == {"keyword": 1, "user": 5}
   assert [row["position"] for row in top["results"]] == [0, 1, 2, 3, 4, 5]
   assert top_text.strip().splitlines()[0].startswith("keyword  ")
   assert top_text.strip().splitlines()[-1] == "results: 6"
   assert keyword_client.search.asked == [("keyword", A_TAG_QUERY, TypeaheadRoute.PERSONALISED)]
   assert (keyword["command"], keyword["post_count"], keyword["more_available"]) == (
      "keyword",
      9,
      True,
   )
   assert departing.search.asked == [
      ("top", A_QUERY, TypeaheadRoute.NON_PERSONALISED),
      ("accounts", A_QUERY, TypeaheadRoute.NON_PERSONALISED),
   ]
