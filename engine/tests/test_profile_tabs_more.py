"""Gates on E2 batch 11a: a profile's reels tab and tagged tab, and the accounts an account
follows.

Four defect classes live here.

A tab can be read from the wrong place or into the wrong fields. The reels tab roots at the
account's user node and nests each reel under ``media``, and its item carries no username and no
caption, so a mapper borrowed from another read either fails or invents them. The tagged tab's
posts are other accounts' posts, so an author read from the tab's owner is a wrong answer about a
real person.

A tab can claim to be whole. Only its first page can be read, so its own ``has_next_page`` is the
one thing that says it is partial, and dropping it hides that.

A request can depart from what the browser sent: another path, a variable under another name, the
account id sent once where the tab sends it twice, or the following list sent with the followers
list's ``search_surface``, which the browser did not send.

And the following list can drift from its twin: the statuses asked for other accounts or left
out, the setting that governs the followers list ignored here, or a walk that stops on anything
but ``has_more``.

The payloads are the recorded answers of 2026-09-27, pseudonymised by
``scripts/build_profile_tabs_more_fixtures.py``. Nothing in this file touches the network.
"""

from __future__ import annotations

import copy
import io
import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, parse_qsl

import pytest

from dumpstagram._cli.main import main
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.profiles import (
   read_following_page,
   read_profile_reels,
   read_tagged_posts,
)
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.web.parse.profiles import (
   attach_friendship_statuses,
   parse_following_page,
   parse_friendship_statuses,
   parse_profile_reels,
   parse_tagged_posts,
)
from dumpstagram._private.web.requests.profiles import build_following_request
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY
from dumpstagram.client import SyncClient
from dumpstagram.errors import SchemaChanged, UpstreamRejected
from dumpstagram.models import (
   Page,
   PostThumbnail,
   ProfileReels,
   ProfileSummary,
   ReelThumbnail,
   TaggedPosts,
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

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "profile_tabs_more"

GRAPHQL_QUERY = "https://www.instagram.com/graphql/query"
SITE_ROOT = "https://www.instagram.com/"
REELS_DOC_ID = "29628758406714645"
TAGGED_DOC_ID = "28390247837269928"
REELS_ROOT = "fetch__XDTUserDict"
TAGGED_ROOT = "xdt_api__v1__usertags__user_id__feed_connection"
SHORT_DRAMA = "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider"

USER_ID = "1234567890"
USERNAME = "an.account_1"
WEB_SESSION_ID = "abc123:def456:ghi789"
FOLLOWING_URL = f"https://www.instagram.com/api/v1/friendships/{USER_ID}/following/"
STATUSES_URL = "https://www.instagram.com/api/v1/friendships/show_many/"
READ_HEADERS = {
   "accept",
   "accept-language",
   "referer",
   "sec-fetch-dest",
   "sec-fetch-mode",
   "sec-fetch-site",
   "user-agent",
   "x-asbd-id",
   "x-csrftoken",
   "x-ig-app-id",
   "x-ig-max-touch-points",
   "x-requested-with",
   "x-web-session-id",
}

SCRIPTED_BEHAVIOR = replace(PARITY, cookie_sync=False)


def recorded(name: str) -> Any:
   return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def reel_media(answer: Any) -> list[dict[str, Any]]:
   edges = answer["data"][REELS_ROOT]["clips_connection"]["edges"]

   return [edge["node"]["media"] for edge in edges]


def tagged_nodes(answer: Any) -> list[dict[str, Any]]:
   return [edge["node"] for edge in answer["data"][TAGGED_ROOT]["edges"]]


def sent_field(request: Any, name: str) -> str:
   return parse_qs(request.content.decode("utf-8"))[name][0]


def sent_form(request: Any) -> list[tuple[str, str]]:
   return parse_qsl(request.content.decode("utf-8"))


def users_of(name: str) -> list[dict[str, Any]]:
   users: list[dict[str, Any]] = recorded(name)["users"]

   return users


def test_a_reels_tab_maps_each_reel_from_its_media_with_the_tabs_own_flag() -> None:
   """Catches a reel read from the edge node rather than its ``media``, a field read from another
   key, a play count read from the null ``view_count`` beside it, and the tab's ``has_next_page``
   dropped. Distinct values are planted on the one recorded reel so that no two fields agree."""

   answer = recorded("reels_tab.json")
   media = reel_media(answer)[0]
   media.update(like_count=11, comment_count=7, play_count=159, view_count=None)
   media.update(original_width=1024, original_height=574)
   answer["data"][REELS_ROOT]["clips_connection"]["page_info"]["has_next_page"] = True

   tab = parse_profile_reels(answer)
   reel = tab.reels[0]

   assert isinstance(tab, ProfileReels)
   assert len(tab.reels) == 1
   assert isinstance(reel, ReelThumbnail)
   assert (reel.id, reel.pk, reel.code) == (media["id"], media["pk"], media["code"])
   assert reel.author_id == media["user"]["pk"]
   assert (reel.media_type, reel.product_type) == (2, "clips")
   assert (reel.like_count, reel.comment_count, reel.play_count) == (11, 7, 159)
   assert (reel.original_width, reel.original_height) == (1024, 574)
   assert [image.url for image in reel.images] == [
      candidate["url"] for candidate in media["image_versions2"]["candidates"]
   ]
   assert tab.has_more is True
   assert parse_profile_reels(recorded("reels_tab.json")).has_more is False


def test_a_reel_whose_play_count_is_null_maps_with_none() -> None:
   """Catches a null play count refused, since whether other accounts' reels carry one is not
   observed, and a missing one accepted silently."""

   answer = recorded("reels_tab.json")
   reel_media(answer)[0]["play_count"] = None

   assert parse_profile_reels(answer).reels[0].play_count is None

   del reel_media(answer)[0]["play_count"]

   with pytest.raises(SchemaChanged, match="play_count"):
      parse_profile_reels(answer)


def test_a_tagged_tab_maps_each_post_with_the_account_that_posted_it() -> None:
   """Catches posts dropped or reordered, an author read from anywhere but the post's own
   ``user``, and the tab's ``has_next_page`` dropped. The four recorded posts are a video, a
   carousel and two photos by other accounts."""

   answer = recorded("tagged_tab.json")
   nodes = tagged_nodes(answer)
   answer["data"][TAGGED_ROOT]["page_info"]["has_next_page"] = True

   tab = parse_tagged_posts(answer)

   assert isinstance(tab, TaggedPosts)
   assert all(isinstance(post, PostThumbnail) for post in tab.posts)
   assert [post.pk for post in tab.posts] == [node["pk"] for node in nodes]
   assert [post.author_id for post in tab.posts] == [node["user"]["pk"] for node in nodes]
   assert [post.author_username for post in tab.posts] == [
      node["user"]["username"] for node in nodes
   ]
   assert [post.media_type for post in tab.posts] == [2, 8, 1, 1]
   assert [post.carousel_media_count for post in tab.posts] == [None, 2, None, None]
   assert tab.has_more is True
   assert parse_tagged_posts(recorded("tagged_tab.json")).has_more is False


@pytest.mark.asyncio
async def test_the_reels_tab_is_the_browsers_query_with_the_account_id_twice() -> None:
   """The parity gate for the reels tab. Catches another query or path, the id sent once, a
   variable renamed, another page size, the variables out of the browser's order, and a username
   sent where the account id is meant, which is refused before anything is sent."""

   transport = ScriptedTransport([json_response(recorded("reels_tab.json"))])
   session = a_bootstrapped_session()

   tab = await read_profile_reels(make_paced(transport), session, USER_ID)
   request = transport.sent[0]
   variables = sent_variables(request)

   assert isinstance(tab, ProfileReels)
   assert request.url == GRAPHQL_QUERY
   assert sent_field(request, "doc_id") == REELS_DOC_ID
   assert sent_field(request, "fb_api_req_friendly_name") == "PolarisProfileReelsTabContentQuery"
   assert request.headers["x-root-field-name"] == REELS_ROOT
   assert request.headers["referer"] == SITE_ROOT
   assert variables == {
      "data": {"include_feed_video": True, "page_size": 12, "target_user_id": USER_ID},
      "user_id": USER_ID,
      SHORT_DRAMA: False,
   }
   assert list(variables) == ["data", "user_id", SHORT_DRAMA]

   with pytest.raises(ValueError, match="numeric account id"):
      await read_profile_reels(make_paced(transport), session, USERNAME)

   assert len(transport.sent) == 1


@pytest.mark.asyncio
async def test_the_tagged_tab_is_the_browsers_query_keyed_on_the_account_id() -> None:
   """The parity gate for the tagged tab. Catches another query or path, another count, the
   variables out of the browser's order, and a username refused only after it was sent."""

   transport = ScriptedTransport([json_response(recorded("tagged_tab.json"))])
   session = a_bootstrapped_session()

   tab = await read_tagged_posts(make_paced(transport), session, USER_ID)
   request = transport.sent[0]
   variables = sent_variables(request)

   assert len(tab.posts) == 4
   assert request.url == GRAPHQL_QUERY
   assert sent_field(request, "doc_id") == TAGGED_DOC_ID
   assert sent_field(request, "fb_api_req_friendly_name") == "PolarisProfileTaggedTabContentQuery"
   assert request.headers["x-root-field-name"] == TAGGED_ROOT
   assert request.headers["referer"] == SITE_ROOT
   assert variables == {"count": 12, "user_id": USER_ID, SHORT_DRAMA: False}
   assert list(variables) == ["count", "user_id", SHORT_DRAMA]

   with pytest.raises(ValueError, match="numeric account id"):
      await read_tagged_posts(make_paced(transport), session, USERNAME)

   assert len(transport.sent) == 1


def test_a_following_page_maps_every_account_with_the_numeric_offset_as_its_cursor() -> None:
   """Catches accounts dropped or reordered, the offset read from anywhere but ``next_max_id``,
   the terminator read from anywhere but ``has_more``, and a refusal mapped as an empty page."""

   first = recorded("following_first_page.json")
   page = parse_following_page(first)
   last = copy.deepcopy(recorded("following_next_page.json"))
   last["has_more"] = False
   del last["next_max_id"]

   assert [account.id for account in page.items] == [user["pk"] for user in first["users"]]
   assert [account.username for account in page.items] == [
      user["username"] for user in first["users"]
   ]
   assert (page.has_next_page, page.end_cursor) == (True, "12")
   assert parse_following_page(recorded("following_next_page.json")).end_cursor == "24"
   assert (parse_following_page(last).has_next_page, parse_following_page(last).end_cursor) == (
      False,
      None,
   )

   with pytest.raises(UpstreamRejected, match="following page"):
      parse_following_page({"message": "a refusal", "status": "fail", "users": []})


def test_a_following_page_is_the_lists_rest_read_without_a_search_surface() -> None:
   """The parity gate for the page. Catches the followers path, the followers list's
   ``search_surface`` sent where the browser sent none, another page size, the offset sent under
   another name or on the first page, and a header set other than the follow list's."""

   session = a_bootstrapped_session()
   first = build_following_request(session, USER_ID, web_session_id=WEB_SESSION_ID)
   later = build_following_request(session, USER_ID, web_session_id=WEB_SESSION_ID, after="24")

   assert (first.method, first.url, first.content) == ("GET", FOLLOWING_URL, None)
   assert dict(first.params) == {"count": "12"}
   assert dict(later.params) == {"count": "12", "max_id": "24"}
   assert set(first.headers) == READ_HEADERS
   assert first.headers["referer"] == SITE_ROOT
   assert first.headers["x-web-session-id"] == WEB_SESSION_ID


@pytest.mark.asyncio
async def test_a_following_page_is_followed_in_its_action_by_the_statuses_of_its_accounts() -> None:
   """Catches the statuses asked for other ids or in another order, a second web session id, and
   a page returned without the statuses its second request read. The page and the statuses are
   the browser's own pair from the capture night."""

   transport = ScriptedTransport(
      [
         json_response(recorded("following_browser_page.json")),
         json_response(recorded("following_statuses.json")),
      ]
   )

   page = await read_following_page(make_paced(transport), a_bootstrapped_session(), USER_ID)
   page_request, statuses_request = transport.sent
   users = users_of("following_browser_page.json")
   statuses = recorded("following_statuses.json")["friendship_statuses"]

   assert page_request.url == FOLLOWING_URL
   assert statuses_request.url == STATUSES_URL
   assert dict(sent_form(statuses_request))["user_ids"] == ",".join(user["pk"] for user in users)
   assert page_request.headers["x-web-session-id"] == statuses_request.headers["x-web-session-id"]
   assert [account.friendship_status is not None for account in page.items] == [True] * 12
   assert [
      account.friendship_status.following
      for account in page.items
      if account.friendship_status is not None
   ] == [statuses[user["pk"]]["following"] for user in users]


@pytest.mark.asyncio
async def test_a_following_page_without_statuses_is_one_request_and_a_username_is_refused() -> None:
   """Catches the setting ignored on this list, a bootstrap spent on a GET that carries no page
   token, and a username put into the path."""

   transport = ScriptedTransport([json_response(recorded("following_first_page.json"))])
   session = Session(sessionid="s", ds_user_id=USER_ID, csrftoken="c")
   sender = make_paced(transport)

   page = await read_following_page(sender, session, USER_ID, with_statuses=False)

   assert [request.url for request in transport.sent] == [FOLLOWING_URL]
   assert {account.friendship_status for account in page.items} == {None}

   with pytest.raises(ValueError, match="numeric account id"):
      await read_following_page(sender, session, USERNAME, with_statuses=False)

   assert len(transport.sent) == 1


def paced(transport: ScriptedTransport, client: AsyncClient) -> PacedSender:
   clock = FakeClock()
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)

   return PacedSender(transport, pacer, client._sender.pacing, client._sender.writes)


def two_pages_without_statuses() -> ScriptedTransport:
   return ScriptedTransport(
      [
         json_response(recorded("following_first_page.json")),
         json_response(recorded("following_next_page.json")),
      ]
   )


WITHOUT_STATUSES = replace(SCRIPTED_BEHAVIOR, follow_list_statuses=False)


@pytest.mark.asyncio
async def test_the_async_walk_asks_for_the_next_page_at_the_first_pages_offset() -> None:
   """Catches a walk that repeats the first page, passes another cursor, or stops at the first
   page's end. The statuses are off, so this also holds one setting governing both lists."""

   transport = two_pages_without_statuses()
   client = AsyncClient(a_bootstrapped_session(), behavior=WITHOUT_STATUSES)
   await client._sender.aclose()
   client._sender = paced(transport, client)

   try:
      accounts = [account async for account in client.profiles.iter_following(USER_ID, limit=15)]
   finally:
      await client.aclose()

   assert len(accounts) == 15
   assert [request.url for request in transport.sent] == [FOLLOWING_URL, FOLLOWING_URL]
   assert "max_id" not in transport.sent[0].params
   assert transport.sent[1].params["max_id"] == "12"


def test_the_blocking_walk_asks_for_the_next_page_at_the_first_pages_offset() -> None:
   """The same walk on the blocking surface, each page read on the loop thread."""

   transport = two_pages_without_statuses()

   with SyncClient(a_bootstrapped_session(), behavior=WITHOUT_STATUSES) as client:
      client._loop.run(client._impl._sender.aclose(), operation="the scripted sender swap")
      client._impl._sender = paced(transport, client._impl)
      accounts = list(client.profiles.iter_following(USER_ID, limit=13))

   assert len(accounts) == 13
   assert [request.url for request in transport.sent] == [FOLLOWING_URL, FOLLOWING_URL]
   assert transport.sent[1].params["max_id"] == "12"


@pytest.mark.asyncio
async def test_following_sends_the_statuses_under_the_default_behavior() -> None:
   """Catches ``following`` leaving the statuses out whatever the client's behavior says."""

   transport = ScriptedTransport(
      [
         json_response(recorded("following_browser_page.json")),
         json_response(recorded("following_statuses.json")),
      ]
   )
   client = AsyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR)
   await client._sender.aclose()
   client._sender = paced(transport, client)

   try:
      await client.profiles.following(USER_ID)
   finally:
      await client.aclose()

   assert [request.url for request in transport.sent] == [FOLLOWING_URL, STATUSES_URL]


class FakeProfiles:
   def __init__(self, pages: list[Page[ProfileSummary]]) -> None:
      self.pages = pages
      self.cursors: list[str | None] = []
      self.asked: list[str] = []

   def following(self, user_id: str, *, after: str | None = None) -> Page[ProfileSummary]:
      self.asked.append("following")
      self.cursors.append(after)

      return self.pages[len(self.cursors) - 1]

   def followers(self, user_id: str, *, after: str | None = None) -> Page[ProfileSummary]:
      self.asked.append("followers")
      self.cursors.append(after)

      return self.pages[len(self.cursors) - 1]

   def reels(self, user_id: str) -> ProfileReels:
      self.asked.append("reels")

      return parse_profile_reels(recorded("reels_tab.json"))

   def tagged(self, user_id: str) -> TaggedPosts:
      self.asked.append("tagged")

      return parse_tagged_posts(recorded("tagged_tab.json"))


class FakeProfilesClient:
   def __init__(self, pages: list[Page[ProfileSummary]]) -> None:
      self.session = Session(sessionid="s", ds_user_id=USER_ID, csrftoken="c")
      self.profiles = FakeProfiles(pages)
      self.closed = False

   def close(self) -> None:
      self.closed = True


def run_command(argv: list[str], client: FakeProfilesClient) -> tuple[int, str]:
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


def recorded_following_pages() -> list[Page[ProfileSummary]]:
   first = attach_friendship_statuses(
      parse_following_page(recorded("following_browser_page.json")),
      parse_friendship_statuses(recorded("following_statuses.json")),
   )
   second = parse_following_page(recorded("following_next_page.json"))

   return [first, replace(second, has_next_page=False)]


def test_dumpsta_following_reads_the_following_list_and_stops_on_its_terminator() -> None:
   """Catches the command reading the followers list, passing its first offset again, or
   reading past a last page when ``--pages`` allows more."""

   client = FakeProfilesClient(recorded_following_pages())

   code, out = run_command(["--json", "following", USER_ID, "--pages", "5"], client)
   payload = json.loads(out)

   assert code == 0
   assert client.profiles.asked == ["following", "following"]
   assert client.profiles.cursors == [None, "12"]
   assert payload["command"] == "following"
   assert payload["pages_read"] == 2
   assert payload["account_count"] == 24
   assert payload["more_available"] is False
   assert payload["accounts"][0]["friendship_status"] is not None
   assert client.closed


def test_dumpsta_profile_reels_and_tagged_print_the_tab_and_its_flag() -> None:
   """Catches either command reading another tab, a count of the wrong list, and the flag that
   says the tab is partial left out of either form."""

   reels_client = FakeProfilesClient([])
   reels_code, reels_out = run_command(["--json", "profile-reels", USER_ID], reels_client)
   reels = json.loads(reels_out)

   tagged_client = FakeProfilesClient([])
   tagged_code, tagged_text = run_command(["tagged", USER_ID], tagged_client)

   assert (reels_code, tagged_code) == (0, 0)
   assert reels_client.profiles.asked == ["reels"]
   assert (reels["command"], reels["reel_count"], reels["more_available"]) == (
      "profile-reels",
      1,
      False,
   )
   assert reels["reels"][0]["product_type"] == "clips"
   assert tagged_client.profiles.asked == ["tagged"]
   assert tagged_text.strip().splitlines()[-1] == "posts: 4  more_available: False"


@pytest.mark.parametrize("command", ["following", "profile-reels", "tagged"])
def test_each_new_command_refuses_a_username(
   command: str, capsys: pytest.CaptureFixture[str]
) -> None:
   """Catches an account named by username reaching a read keyed on the numeric id."""

   code, _ = run_command([command, USERNAME], FakeProfilesClient([]))

   assert code == 2
   assert "numeric id" in capsys.readouterr().err
