"""Gates on E2 batch 2, the profile tabs: the posts grid, the highlights tray and the two lists
of suggested accounts.

Five defect classes live here.

A grid page can be read from the wrong place or refused outright. The owner's grid answered
whole beside one field error per post with a location, and the shipped classifier refused it,
so a grid gate has to go through the classifier and not only the mapper. A grid node is the
home timeline's node with ``is_seen`` null, so a mapper can either refuse every grid or start
reading a null the home timeline never sends.

The next page can be asked for with the wrong query, the wrong variables or a cursor other than
the one the page before handed out.

A list row can be mapped from the wrong key: ``pk`` and ``id`` agree, but ``following`` and
``followed_by`` are two booleans side by side, and the reason a suggestion is shown sits on the
item, beside a ``social_context`` on the user that is null.

A tray can hide that it is partial, since only its first page can be read.

And a command can stop on the wrong terminator or take a username where an id is meant.

The payloads are the recorded answers of 2026-09-27, pseudonymised by
``scripts/build_profile_tabs_fixtures.py``. Nothing in this file touches the network.
"""

from __future__ import annotations

import copy
import io
import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import pytest

from dumpstagram._cli.main import main
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.profiles import (
   read_highlight_tray,
   read_profile_posts_page,
   read_suggested_accounts,
   read_suggested_beside_profile,
)
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.web.parse.feed import parse_feed_page
from dumpstagram._private.web.parse.profiles import (
   parse_highlight_tray,
   parse_profile_posts_page,
   parse_suggested_accounts,
   parse_suggested_beside_profile,
)
from dumpstagram._private.web.requests.profiles import build_profile_posts_request
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY
from dumpstagram.client import SyncClient
from dumpstagram.errors import NotFound, SchemaChanged
from dumpstagram.models import (
   HighlightTray,
   Page,
   Post,
   ProfileSummary,
   SuggestedAccount,
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

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "profile_tabs"

GRAPHQL_QUERY = "https://www.instagram.com/graphql/query"
API_GRAPHQL = "https://www.instagram.com/api/graphql"
SITE_ROOT = "https://www.instagram.com/"
GRID_ROOT = "xdt_api__v1__feed__user_timeline_graphql_connection"
FIRST_PAGE_DOC_ID = "28379418928391013"
NEXT_PAGE_DOC_ID = "38620137654299531"
HIGHLIGHTS_DOC_ID = "26970053832668570"
BESIDE_PROFILE_DOC_ID = "28011006998510477"
SUGGESTED_LIST_DOC_ID = "28042919442028999"
USERNAME = "an.account_1"
USER_ID = "1234567890"

SCRIPTED_BEHAVIOR = replace(PARITY, cookie_sync=False)


def recorded(name: str) -> Any:
   return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def grid_nodes(name: str) -> list[dict[str, Any]]:
   return [edge["node"] for edge in recorded(name)["data"][GRID_ROOT]["edges"]]


def grid_page_info(name: str) -> dict[str, Any]:
   page_info: dict[str, Any] = recorded(name)["data"][GRID_ROOT]["page_info"]

   return page_info


def sent_field(request: Any, name: str) -> str:
   return parse_qs(request.content.decode("utf-8"))[name][0]


def test_a_grid_page_maps_every_post_in_the_upstream_order_with_its_own_terminator() -> None:
   """Catches posts dropped or reordered, and a page's cursor or flag read from anywhere but its
   ``page_info``. The recorded first page has twelve posts and a next page."""

   nodes = grid_nodes("author_grid_first_page.json")
   page = parse_profile_posts_page(recorded("author_grid_first_page.json"))
   page_info = grid_page_info("author_grid_first_page.json")

   assert len(nodes) == 12
   assert [post.pk for post in page.items] == [node["pk"] for node in nodes]
   assert [post.id for post in page.items] == [node["id"] for node in nodes]
   assert page.has_next_page is True
   assert page.end_cursor == page_info["end_cursor"]
   assert page.end_cursor is not None


def test_a_grid_post_carries_a_null_is_seen_and_reads_as_unseen() -> None:
   """Catches the grid refused whole because ``is_seen`` is null on every grid node, and a null
   read as seen. Every recorded grid node carries it null."""

   nodes = grid_nodes("author_grid_first_page.json") + grid_nodes("author_grid_next_page.json")
   posts = parse_profile_posts_page(recorded("author_grid_first_page.json")).items

   assert {node["is_seen"] for node in nodes} == {None}
   assert {post.is_seen for post in posts} == {False}


def test_the_home_timeline_still_refuses_a_null_is_seen() -> None:
   """Catches the grid's reading of a null leaking into the home timeline mapper, which has
   only ever been sent a boolean there. The planted node is a recorded grid node."""

   node = grid_nodes("author_grid_first_page.json")[0]
   empty_slots = {
      slot: None
      for slot in (
         "ad",
         "explore_story",
         "end_of_feed_demarcator",
         "stories_netego",
         "suggested_users",
         "bloks_netego",
         "abra_icebreakers_in_feed_unit",
         "ad4ad_in_webfeed",
      )
   }
   feed = {
      "data": {
         "xdt_api__v1__feed__timeline__connection": {
            "edges": [{"node": {"media": node, **empty_slots}}],
            "page_info": {"has_next_page": False, "end_cursor": None},
         }
      }
   }
   seen_node = copy.deepcopy(feed)
   seen_node["data"]["xdt_api__v1__feed__timeline__connection"]["edges"][0]["node"]["media"][
      "is_seen"
   ] = True

   assert parse_feed_page(seen_node).items[0].post is not None

   with pytest.raises(SchemaChanged, match="is_seen"):
      parse_feed_page(feed)


def test_a_grid_is_seen_that_is_neither_null_nor_a_boolean_is_refused() -> None:
   """Catches the grid mapper reading anything at all as unseen rather than only a null."""

   payload = copy.deepcopy(recorded("author_grid_first_page.json"))
   payload["data"][GRID_ROOT]["edges"][0]["node"]["is_seen"] = "no"

   with pytest.raises(SchemaChanged, match="is_seen"):
      parse_profile_posts_page(payload)


@pytest.mark.asyncio
async def test_the_owners_grid_answered_beside_field_errors_is_read_whole() -> None:
   """Catches the grid refused for the field errors the upstream sent beside it on 2026-09-27,
   one per post whose location picture failed, which is how the first two discovery runs
   stopped."""

   answer = recorded("owner_grid_partial.json")
   errored_edges = sorted({error["path"][2] for error in answer["errors"]})
   transport = ScriptedTransport([json_response(answer)])

   page = await read_profile_posts_page(make_paced(transport), a_bootstrapped_session(), USERNAME)

   assert len(answer["errors"]) == 3
   assert errored_edges == [1, 2, 3]
   assert [post.pk for post in page.items] == [
      node["pk"] for node in grid_nodes("owner_grid_partial.json")
   ]
   assert len(page.items) == 8
   assert page.has_next_page is False


def test_the_first_grid_page_is_the_profile_pages_own_timeline_query() -> None:
   """The parity gate for the first page. Catches another query, another path, the resolution's
   count of one, or a referer other than the profile page."""

   request = build_profile_posts_request(a_bootstrapped_session(), USERNAME)

   assert request.url == GRAPHQL_QUERY
   assert sent_field(request, "doc_id") == FIRST_PAGE_DOC_ID
   assert sent_field(request, "fb_api_req_friendly_name") == "PolarisProfilePostsQuery"
   assert request.headers["x-root-field-name"] == GRID_ROOT
   assert request.headers["referer"] == f"{SITE_ROOT}{USERNAME}/"
   assert sent_variables(request) == {
      "data": {
         "count": 12,
         "include_reel_media_seen_timestamp": True,
         "include_relationship_info": True,
         "latest_besties_reel_media": True,
         "latest_reel_media": True,
      },
      "username": USERNAME,
      "__relay_internal__pv__PolarisMultiCaptionCarouselEnabledrelayprovider": True,
      "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": False,
      "__relay_internal__pv__PolarisReelsRecoDebugOverlayEnabledrelayprovider": False,
   }


def test_a_later_grid_page_is_the_tab_connection_query_replayed_live() -> None:
   """The parity gate for the next page. Catches the first page's query sent again with a
   cursor, and any variable other than the ones replayed twice on 2026-09-27."""

   request = build_profile_posts_request(a_bootstrapped_session(), USERNAME, after="C000001ccc")

   assert request.url == GRAPHQL_QUERY
   assert sent_field(request, "doc_id") == NEXT_PAGE_DOC_ID
   assert (
      sent_field(request, "fb_api_req_friendly_name")
      == "PolarisProfilePostsTabContentQuery_connection"
   )
   assert request.headers["x-root-field-name"] == GRID_ROOT
   assert request.headers["referer"] == f"{SITE_ROOT}{USERNAME}/"
   assert sent_variables(request) == {
      "after": "C000001ccc",
      "before": None,
      "data": {
         "count": 12,
         "include_reel_media_seen_timestamp": True,
         "include_relationship_info": True,
         "latest_besties_reel_media": True,
         "latest_reel_media": True,
      },
      "first": 12,
      "include_multi_captions": True,
      "last": None,
      "username": USERNAME,
      "__relay_internal__pv__PolarisMultiCaptionCarouselEnabledrelayprovider": True,
      "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": False,
      "__relay_internal__pv__PolarisReelsRecoDebugOverlayEnabledrelayprovider": False,
   }


@pytest.mark.asyncio
async def test_a_name_that_cannot_be_a_username_is_refused_before_anything_is_sent() -> None:
   """Catches a username put into the referer's path unchecked."""

   transport = ScriptedTransport([])

   with pytest.raises(NotFound):
      await read_profile_posts_page(make_paced(transport), a_bootstrapped_session(), "a/b")

   assert transport.sent == []


def paced(transport: ScriptedTransport, client: AsyncClient) -> PacedSender:
   clock = FakeClock()
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)

   return PacedSender(transport, pacer, client._sender.pacing, client._sender.writes)


def two_grid_pages() -> ScriptedTransport:
   return ScriptedTransport(
      [
         json_response(recorded("author_grid_first_page.json")),
         json_response(recorded("author_grid_next_page.json")),
      ]
   )


def friendly_names(transport: ScriptedTransport) -> list[str]:
   return [sent_field(request, "fb_api_req_friendly_name") for request in transport.sent]


@pytest.mark.asyncio
async def test_the_async_grid_walk_crosses_to_the_next_page_query_on_the_first_pages_cursor() -> (
   None
):
   """Catches a walk that asks the first page query again for page two, passes another cursor,
   or stops at the first page's end."""

   transport = two_grid_pages()
   client = AsyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR)
   await client._sender.aclose()
   client._sender = paced(transport, client)

   try:
      posts = [post async for post in client.profiles.iter_posts(USERNAME, limit=20)]
   finally:
      await client.aclose()

   assert len(posts) == 20
   assert friendly_names(transport) == [
      "PolarisProfilePostsQuery",
      "PolarisProfilePostsTabContentQuery_connection",
   ]
   assert (
      sent_variables(transport.sent[1])["after"]
      == grid_page_info("author_grid_first_page.json")["end_cursor"]
   )


def test_the_blocking_grid_walk_crosses_to_the_next_page_query() -> None:
   """The same walk on the blocking surface, each page read on the loop thread."""

   transport = two_grid_pages()

   with SyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR) as client:
      client._loop.run(client._impl._sender.aclose(), operation="the scripted sender swap")
      client._impl._sender = paced(transport, client._impl)
      posts = list(client.profiles.iter_posts(USERNAME, limit=13))

   assert len(posts) == 13
   assert friendly_names(transport)[1] == "PolarisProfilePostsTabContentQuery_connection"
   assert sent_variables(transport.sent[1])["username"] == USERNAME


def test_a_highlight_is_read_from_its_own_keys_and_the_tray_says_when_it_is_partial() -> None:
   """Catches the title read from the id or the cover from another picture, the owner read from
   anywhere but the node's user, and ``has_more`` not following the upstream's flag."""

   recorded_tray = recorded("highlight_tray.json")
   node = recorded_tray["data"]["highlights"]["edges"][0]["node"]
   planted = copy.deepcopy(recorded_tray)
   planted["data"]["highlights"]["page_info"]["has_next_page"] = True
   tray = parse_highlight_tray(recorded_tray)
   highlight = tray.highlights[0]

   assert len(tray.highlights) == 1
   assert highlight.id == node["id"]
   assert highlight.id.startswith("highlight:")
   assert highlight.title == node["title"]
   assert highlight.cover_url == node["cover_media"]["cropped_image_version"]["url"]
   assert (highlight.owner_id, highlight.owner_username) == (
      node["user"]["id"],
      node["user"]["username"],
   )
   assert tray.has_more is False
   assert parse_highlight_tray(planted).has_more is True


@pytest.mark.asyncio
async def test_the_tray_is_the_profile_pages_query_keyed_on_the_account_id() -> None:
   """The parity gate for the tray. Catches another query or variable, and a username sent where
   the account id is meant, which is refused before anything is sent."""

   transport = ScriptedTransport([json_response(recorded("highlight_tray.json"))])
   session = a_bootstrapped_session()

   tray = await read_highlight_tray(make_paced(transport), session, USER_ID)
   request = transport.sent[0]

   assert isinstance(tray, HighlightTray)
   assert request.url == API_GRAPHQL
   assert sent_field(request, "doc_id") == HIGHLIGHTS_DOC_ID
   assert sent_variables(request) == {"user_id": USER_ID}
   assert request.headers["referer"] == SITE_ROOT

   with pytest.raises(ValueError, match="numeric account id"):
      await read_highlight_tray(make_paced(transport), session, USERNAME)

   assert len(transport.sent) == 1


def beside_profile_rows() -> list[dict[str, Any]]:
   rows: list[dict[str, Any]] = recorded("suggested_beside_profile.json")["data"][
      "xdt_api__v1__discover__chaining"
   ]["users"]

   return rows


def test_every_suggested_row_is_read_by_its_pk_with_its_privacy_and_picture() -> None:
   """Catches rows dropped or reordered, the id read from another key, and ``is_private`` or the
   high resolution picture dropped where the row carries them."""

   rows = beside_profile_rows()
   accounts = parse_suggested_beside_profile(recorded("suggested_beside_profile.json"))

   assert len(rows) == 18
   assert [account.id for account in accounts] == [row["pk"] for row in rows]
   assert [account.username for account in accounts] == [row["username"] for row in rows]
   assert [account.is_private for account in accounts] == [row["is_private"] for row in rows]
   assert [account.hd_profile_pic_url for account in accounts] == [
      row["hd_profile_pic_url_info"]["url"] for row in rows
   ]


def with_first_row(change: Any) -> dict[str, Any]:
   payload = copy.deepcopy(recorded("suggested_beside_profile.json"))
   change(payload["data"]["xdt_api__v1__discover__chaining"]["users"][0])

   return payload


def test_a_rows_friendship_flags_are_each_read_from_their_own_key() -> None:
   """Catches ``following`` read from ``followed_by`` or the request flags swapped. Every
   recorded flag is false, so each flag in turn is planted true on the first row and must come
   out alone."""

   flags = (
      "following",
      "followed_by",
      "outgoing_request",
      "incoming_request",
      "blocking",
      "is_restricted",
      "is_bestie",
      "is_feed_favorite",
   )

   for flag in flags:
      payload = with_first_row(lambda row, flag=flag: row["friendship_status"].update({flag: True}))
      status = parse_suggested_beside_profile(payload)[0].friendship_status

      assert status is not None
      assert [getattr(status, name) for name in flags] == [name == flag for name in flags]


def test_a_row_without_the_two_list_only_flags_reads_them_as_none_and_a_required_one_raises() -> (
   None
):
   """Catches ``followed_by`` and ``blocking`` made required, which the followers' statuses do
   not carry, and a missing required flag read as false."""

   def without_list_only_flags(row: dict[str, Any]) -> None:
      del row["friendship_status"]["followed_by"]
      del row["friendship_status"]["blocking"]

   def without_following(row: dict[str, Any]) -> None:
      del row["friendship_status"]["following"]

   status = parse_suggested_beside_profile(with_first_row(without_list_only_flags))[
      0
   ].friendship_status

   assert status is not None
   assert (status.followed_by, status.blocking) == (None, None)

   with pytest.raises(SchemaChanged, match="following"):
      parse_suggested_beside_profile(with_first_row(without_following))


def test_a_suggestion_carries_the_items_reason_and_no_privacy_it_was_not_sent() -> None:
   """Catches the reason read from the user's own ``social_context``, which is null, and
   ``is_private`` read as false on rows that do not carry it."""

   items = recorded("suggested_accounts.json")["data"]["ayml"]["groups"][0]["items"]
   suggestions = parse_suggested_accounts(recorded("suggested_accounts.json"))

   assert len(items) == 5
   assert all("is_private" not in item["user"] for item in items)
   assert [suggestion.reason for suggestion in suggestions] == [
      item["social_context"] for item in items
   ]
   assert [suggestion.account.id for suggestion in suggestions] == [
      item["user"]["pk"] for item in items
   ]
   assert {suggestion.account.is_private for suggestion in suggestions} == {None}


@pytest.mark.asyncio
async def test_both_suggested_lists_send_the_variables_replayed_live() -> None:
   """The parity gate for the two lists. Catches another module, target or page size, and a
   username sent as the target."""

   transport = ScriptedTransport(
      [
         json_response(recorded("suggested_beside_profile.json")),
         json_response(recorded("suggested_accounts.json")),
      ]
   )
   sender = make_paced(transport)
   session = a_bootstrapped_session()

   beside = await read_suggested_beside_profile(sender, session, USER_ID)
   for_you = await read_suggested_accounts(sender, session)

   assert all(isinstance(account, ProfileSummary) for account in beside)
   assert all(isinstance(suggestion, SuggestedAccount) for suggestion in for_you)
   assert [sent_field(request, "doc_id") for request in transport.sent] == [
      BESIDE_PROFILE_DOC_ID,
      SUGGESTED_LIST_DOC_ID,
   ]
   assert sent_variables(transport.sent[0]) == {"module": "profile", "target_id": USER_ID}
   assert sent_variables(transport.sent[1]) == {
      "data": {
         "max_id": "",
         "max_number_to_display": 5,
         "module": "discover_people",
         "paginate": True,
      }
   }

   with pytest.raises(ValueError, match="numeric account id"):
      await read_suggested_beside_profile(sender, session, USERNAME)

   assert len(transport.sent) == 2


class FakeProfiles:
   def __init__(self, pages: list[Page[Post]]) -> None:
      self.pages = pages
      self.cursors: list[str | None] = []

   def posts(self, username: str, *, after: str | None = None) -> Page[Post]:
      self.cursors.append(after)

      return self.pages[len(self.cursors) - 1]

   def highlights(self, user_id: str) -> HighlightTray:
      tray = parse_highlight_tray(recorded("highlight_tray.json"))

      return replace(tray, has_more=True)

   def suggested(self, user_id: str) -> tuple[ProfileSummary, ...]:
      return parse_suggested_beside_profile(recorded("suggested_beside_profile.json"))

   def suggested_for_you(self) -> tuple[SuggestedAccount, ...]:
      return parse_suggested_accounts(recorded("suggested_accounts.json"))


class FakeProfilesClient:
   def __init__(self, pages: list[Page[Post]]) -> None:
      self.session = Session(sessionid="s", ds_user_id="1234567890", csrftoken="c")
      self.profiles = FakeProfiles(pages)
      self.closed = False

   def close(self) -> None:
      self.closed = True


def run_command(argv: list[str], client: FakeProfilesClient) -> tuple[int, str, str]:
   out = io.StringIO()
   errors = io.StringIO()

   def factory(path: Path, *, user_agent: str | None = None) -> Any:
      return client

   try:
      code = main(
         ["--session", "unused.json", *argv],
         environment={},
         client_factory=factory,
         stdout=out,
         stderr=errors,
      )
   except SystemExit as exited:
      code = int(exited.code or 0)

   return code, out.getvalue(), errors.getvalue()


def recorded_grid_pages() -> list[Page[Post]]:
   first = parse_profile_posts_page(recorded("author_grid_first_page.json"))
   second = parse_profile_posts_page(recorded("author_grid_next_page.json"))
   last = Page(items=second.items, has_next_page=False, end_cursor=None)

   return [replace(first, end_cursor="k1"), last]


def test_dumpsta_posts_walks_on_the_pages_own_cursor_and_stops_on_its_terminator() -> None:
   """Catches the command passing its first cursor again, or reading past a last page when
   ``--pages`` allows more."""

   client = FakeProfilesClient(recorded_grid_pages())

   code, out, _ = run_command(["--json", "posts", USERNAME, "--pages", "5"], client)
   payload = json.loads(out)

   assert code == 0
   assert client.profiles.cursors == [None, "k1"]
   assert payload["pages_read"] == 2
   assert payload["post_count"] == 24
   assert payload["more_available"] is False
   assert len(payload["posts"]) == 24
   assert client.closed


def test_dumpsta_highlights_says_when_the_tray_is_partial() -> None:
   """Catches a partial tray printed as if it were the whole tray."""

   code, out, _ = run_command(["highlights", USER_ID], FakeProfilesClient([]))

   assert code == 0
   assert out.strip().splitlines()[-1] == "highlights: 1  more_available: True"


def test_dumpsta_suggested_for_you_prints_each_accounts_reason() -> None:
   """Catches the reason left out of either output form."""

   items = recorded("suggested_accounts.json")["data"]["ayml"]["groups"][0]["items"]
   code, out, _ = run_command(["--json", "suggested-for-you"], FakeProfilesClient([]))
   payload = json.loads(out)
   _, text, _ = run_command(["suggested-for-you"], FakeProfilesClient([]))

   assert code == 0
   assert [account["reason"] for account in payload["accounts"]] == [
      item["social_context"] for item in items
   ]
   assert all(item["social_context"] in text for item in items)


def test_dumpsta_suggested_and_highlights_refuse_a_username(
   capsys: pytest.CaptureFixture[str],
) -> None:
   """Catches an account named by username reaching a read keyed on the numeric id. The parser
   writes its refusal to the process's own stderr."""

   for command in ("suggested", "highlights"):
      code, _, _ = run_command([command, USERNAME], FakeProfilesClient([]))

      assert code == 2
      assert "numeric id" in capsys.readouterr().err
