"""Gates on E2 batch 6, the viewer's own account: the pending follow requests and the activity
feed.

Four defect classes live here.

A request can depart from what the browser's inbox load sent: another path, a body on the GET,
another body on the POST, another referer, or a header set other than the follow list's.

A mapper can put a value in the wrong place. The follow request row sends its id twice, once as
a number, and the activity feed names accounts inside a line of text by offsets, carries fifteen
counters side by side, and pairs its section titles with indices, so a value read from its
neighbour gives a caller a wrong account, a wrong count or a wrong heading.

A list can end on the wrong signal. Neither read has been observed past its first page, so the
upstream's own flags, ``next_max_id`` and ``is_last_page``, are the only thing a caller has.

And the activity read can mark the feed seen. A browser follows it with ``news/inbox_seen``,
which has never been verified, and nothing here may send it (W74).

The payloads are the recorded answers of 2026-09-27, pseudonymised by
``scripts/build_account_fixtures.py``. Nothing in this file touches the network.
"""

from __future__ import annotations

import copy
import io
import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

import pytest

from dumpstagram._cli.main import main
from dumpstagram._core.account import read_activity_feed, read_follow_requests
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.web.parse.account import parse_activity_feed, parse_follow_requests
from dumpstagram._private.web.requests.account import (
   build_activity_feed_request,
   build_follow_requests_request,
)
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY
from dumpstagram.client import SyncClient
from dumpstagram.errors import AuthenticationFailed, SchemaChanged, UpstreamRejected
from dumpstagram.models import ActivityFeed, FollowRequests
from dumpstagram.session import Session
from tests.test_direct import (
   FakeClock,
   ScriptedTransport,
   a_bootstrapped_session,
   json_response,
   make_paced,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "account"

INBOX_PAGE = "https://www.instagram.com/direct/inbox/"
FOLLOW_REQUESTS_URL = "https://www.instagram.com/api/v1/friendships/pending/"
ACTIVITY_FEED_URL = "https://www.instagram.com/api/v1/news/inbox/"
WEB_SESSION_ID = "abc123:def456:ghi789"
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
COUNTERS = (
   "likes",
   "comments",
   "comment_likes",
   "relationships",
   "requests",
   "usertags",
   "photos_of_you",
   "new_posts",
   "media_to_approve",
   "fundraiser",
   "promotional",
   "shopping_notification",
   "campaign_notification",
   "activity_feed_dot_badge",
   "activity_feed_dot_badge_only",
)

SCRIPTED_BEHAVIOR = replace(PARITY, cookie_sync=False)


def recorded(name: str) -> Any:
   return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def recorded_stories() -> list[dict[str, Any]]:
   stories: list[dict[str, Any]] = recorded("activity_feed.json")["old_stories"]

   return stories


def sent_form(request: Any) -> list[tuple[str, str]]:
   return parse_qsl(request.content.decode("utf-8"))


def test_a_follow_request_row_reads_its_id_from_the_string_key_and_more_from_next_max_id() -> None:
   """Catches the id read from the numeric ``pk``, a row dropped, and ``has_more`` read from
   anything but ``next_max_id``. The recorded answer carried it null; a planted cursor must say
   more exist and a planted ``big_list`` must not."""

   answer = recorded("follow_requests.json")
   with_cursor = copy.deepcopy(answer)
   with_cursor["next_max_id"] = "C000001"
   big_without_cursor = copy.deepcopy(answer)
   big_without_cursor["big_list"] = True

   requests = parse_follow_requests(answer)
   row = answer["users"][0]

   assert [account.id for account in requests.accounts] == [row["id"]]
   assert requests.accounts[0].username == row["username"]
   assert requests.accounts[0].is_private is row["is_private"]
   assert requests.has_more is False
   assert parse_follow_requests(with_cursor).has_more is True
   assert parse_follow_requests(big_without_cursor).has_more is False


def test_an_account_answer_whose_status_is_not_ok_is_refused() -> None:
   """Catches a REST refusal, which the classifier does not read, mapped as an empty list or an
   empty feed."""

   requests_refused = {**recorded("follow_requests.json"), "status": "fail"}
   feed_refused = {**recorded("activity_feed.json"), "status": "fail"}

   with pytest.raises(UpstreamRejected):
      parse_follow_requests(requests_refused)

   with pytest.raises(UpstreamRejected):
      parse_activity_feed(feed_refused)


def test_the_follow_requests_read_is_the_inbox_loads_get() -> None:
   """The parity gate for the requests. Catches another path, a query or a body on the GET,
   another referer, and a header set other than the follow list's."""

   session = a_bootstrapped_session()
   request = build_follow_requests_request(session, web_session_id=WEB_SESSION_ID)

   assert (request.method, request.url, request.content) == ("GET", FOLLOW_REQUESTS_URL, None)
   assert dict(request.params) == {}
   assert set(request.headers) == READ_HEADERS
   assert request.headers["referer"] == INBOX_PAGE
   assert request.headers["x-csrftoken"] == session.csrftoken
   assert request.headers["x-web-session-id"] == WEB_SESSION_ID


def test_the_activity_read_is_the_inbox_loads_form_post_with_only_the_page_token() -> None:
   """The parity gate for the feed. Catches another path, a field beyond the two replayed or
   out of their order, another referer, the three headers a form POST adds missing, and a
   request built without a token."""

   session = a_bootstrapped_session()
   request = build_activity_feed_request(session, web_session_id=WEB_SESSION_ID)
   form = sent_form(request)

   assert (request.method, request.url) == ("POST", ACTIVITY_FEED_URL)
   assert [name for name, _ in form] == ["fb_dtsg", "jazoest"]
   assert dict(form)["fb_dtsg"] == session.fb_dtsg
   assert set(request.headers) == READ_HEADERS | {"content-type", "origin", "x-instagram-ajax"}
   assert request.headers["referer"] == INBOX_PAGE
   assert request.headers["content-type"] == "application/x-www-form-urlencoded"
   assert request.headers["x-instagram-ajax"] == "1047996704"

   with pytest.raises(AuthenticationFailed):
      build_activity_feed_request(
         Session(sessionid="s", ds_user_id="1", csrftoken="c"), web_session_id=WEB_SESSION_ID
      )


def test_every_activity_item_maps_in_order_with_its_kind_time_and_text() -> None:
   """Catches items dropped or reordered, the id, kind or number read from a neighbouring key,
   the time read from anything but the item's own ``timestamp``, and the line read from its
   markup form."""

   stories = recorded_stories()
   feed = parse_activity_feed(recorded("activity_feed.json"))

   assert len(feed.earlier_items) == 69
   assert (feed.new_items, feed.priority_items) == ((), ())
   assert [item.id for item in feed.earlier_items] == [story["pk"] for story in stories]
   assert [item.kind for item in feed.earlier_items] == [story["notif_name"] for story in stories]
   assert [item.story_type for item in feed.earlier_items] == [
      story["story_type"] for story in stories
   ]
   assert [item.created_at for item in feed.earlier_items] == [
      datetime.fromtimestamp(story["args"]["timestamp"], tz=UTC) for story in stories
   ]
   assert [item.text for item in feed.earlier_items] == [story["args"]["text"] for story in stories]


def test_each_link_names_the_account_its_span_of_the_text_shows() -> None:
   """Catches a link's start and end swapped or read from another key, and the id or username
   of one link read from its neighbour. All 116 recorded links cover their username, and the
   markup form with its markup stripped is the text."""

   feed = parse_activity_feed(recorded("activity_feed.json"))
   links = [(item, link) for item in feed.earlier_items for link in item.links]
   stripped = [
      re.sub(r"\{([^|{}]+)\|[^{}]*\}", r"\1", story["args"]["rich_text"])
      for story in recorded_stories()
   ]

   assert len(links) == 116
   assert all(item.text[link.start : link.end] == link.username for item, link in links)
   assert [link.id for _, link in links] == [
      raw["id"] for story in recorded_stories() for raw in story["args"].get("links", [])
   ]
   assert {link.kind for _, link in links} == {"user"}
   assert stripped == [item.text for item in feed.earlier_items]


def test_what_an_item_carries_only_sometimes_is_none_or_empty_where_it_is_absent() -> None:
   """Catches an optional field filled from another item, read from the wrong key, or required.
   The counts are the fixture's own: the accounts on 67 and 50, the follow button on 9, the
   thumbnail on 57, a comment on 1 and a route on 68."""

   stories = recorded_stories()
   feed = parse_activity_feed(recorded("activity_feed.json"))
   pairs = list(zip(stories, feed.earlier_items, strict=True))

   assert [item.account_id for _, item in pairs] == [
      story["args"].get("profile_id") for story, _ in pairs
   ]
   assert [item.account_username for _, item in pairs] == [
      story["args"].get("profile_name") for story, _ in pairs
   ]
   assert [item.second_account_id for _, item in pairs] == [
      story["args"].get("second_profile_id") for story, _ in pairs
   ]
   assert [item.comment_id for _, item in pairs] == [
      story["args"].get("comment_id") for story, _ in pairs
   ]
   assert [item.destination for _, item in pairs] == [
      story["args"].get("destination") for story, _ in pairs
   ]
   assert [
      [(entry.id, entry.shortcode, entry.image_url) for entry in item.media] for _, item in pairs
   ] == [
      [(raw["id"], raw["shortcode"], raw["image"]) for raw in story["args"].get("media", [])]
      for story, _ in pairs
   ]
   assert sum(item.account_id is not None for _, item in pairs) == 67
   assert sum(item.second_account_id is not None for _, item in pairs) == 50
   assert sum(item.follow_account is not None for _, item in pairs) == 9
   assert sum(bool(item.media) for _, item in pairs) == 57
   assert sum(item.comment_id is not None for _, item in pairs) == 1
   assert sum(item.destination is not None for _, item in pairs) == 68


def test_a_follow_button_carries_its_account_and_the_viewers_relationship_to_it() -> None:
   """Catches the follow button's account read from the item's other accounts, and its
   relationship dropped. The recorded follow request item's button says the account asked."""

   stories = recorded_stories()
   feed = parse_activity_feed(recorded("activity_feed.json"))

   for story, item in zip(stories, feed.earlier_items, strict=True):
      raw = story["args"].get("inline_follow")

      if raw is None:
         continue

      account = item.follow_account
      user_info = raw["user_info"]

      assert account is not None
      assert (account.id, account.username) == (user_info["pk"], user_info["username"])
      assert account.friendship_status is not None
      assert account.friendship_status.following is user_info["friendship_status"]["following"]
      assert (
         account.friendship_status.incoming_request
         is user_info["friendship_status"]["incoming_request"]
      )

   request_item = next(
      item for item in feed.earlier_items if item.kind == "private_user_follow_request"
   )
   assert request_item.follow_account is not None
   assert request_item.follow_account.friendship_status is not None
   assert request_item.follow_account.friendship_status.incoming_request is True


def test_each_counter_is_read_from_its_own_key() -> None:
   """Catches two counters swapped. All fifteen were zero when read, so each is planted with
   its own number and must come out with it."""

   answer = recorded("activity_feed.json")

   for position, name in enumerate(COUNTERS):
      answer["counts"][name] = position + 1

   counts = parse_activity_feed(answer).counts

   assert [getattr(counts, name) for name in COUNTERS] == [
      position + 1 for position in range(len(COUNTERS))
   ]


def test_the_feed_carries_its_sections_last_page_flag_and_last_check() -> None:
   """Catches a section title paired with another index, the last page flag read as a constant,
   the last check read from an item, and titles and indices of unequal length accepted."""

   answer = recorded("activity_feed.json")
   feed = parse_activity_feed(answer)
   not_last = {**copy.deepcopy(answer), "is_last_page": False}
   unpaired = copy.deepcopy(answer)
   unpaired["partition"]["time_bucket"]["indices"].pop()
   bucket = answer["partition"]["time_bucket"]

   assert [(section.title, section.first_index) for section in feed.sections] == list(
      zip(bucket["headers"], bucket["indices"], strict=True)
   )
   assert [section.first_index for section in feed.sections] == [0, 3, 5, 11, 60]
   assert feed.is_last_page is True
   assert parse_activity_feed(not_last).is_last_page is False
   assert feed.last_checked_at == datetime.fromtimestamp(answer["last_checked"], tz=UTC)

   with pytest.raises(SchemaChanged):
      parse_activity_feed(unpaired)


def test_new_and_priority_items_land_in_their_own_lists_and_items_joins_them_in_order() -> None:
   """Catches the new list read from the earlier one, and ``items`` joining the lists in
   another order. No new or priority item was recorded, so earlier ones are planted there."""

   answer = recorded("activity_feed.json")
   stories = answer["old_stories"]
   answer["priority_stories"] = [stories[5]]
   answer["new_stories"] = [stories[0], stories[1]]

   feed = parse_activity_feed(answer)

   assert [item.id for item in feed.priority_items] == [stories[5]["pk"]]
   assert [item.id for item in feed.new_items] == [stories[0]["pk"], stories[1]["pk"]]
   assert len(feed.earlier_items) == 69
   assert [item.id for item in feed.items[:4]] == [
      stories[5]["pk"],
      stories[0]["pk"],
      stories[1]["pk"],
      stories[0]["pk"],
   ]
   assert len(feed.items) == 72


@pytest.mark.asyncio
async def test_the_follow_requests_read_is_one_get_and_spends_no_bootstrap() -> None:
   """Catches a bootstrap spent on a GET that carries no page token, and a second request."""

   transport = ScriptedTransport([json_response(recorded("follow_requests.json"))])
   session = Session(sessionid="s", ds_user_id="1234567890", csrftoken="c")

   requests = await read_follow_requests(make_paced(transport), session)

   assert [request.url for request in transport.sent] == [FOLLOW_REQUESTS_URL]
   assert len(requests.accounts) == 1


@pytest.mark.asyncio
async def test_the_activity_read_is_one_post_and_never_marks_the_feed_seen() -> None:
   """Catches the read followed by a second request, which is how a seen marking would go out,
   and the answer returned unmapped."""

   transport = ScriptedTransport([json_response(recorded("activity_feed.json"))])

   feed = await read_activity_feed(make_paced(transport), a_bootstrapped_session())

   assert [(request.method, request.url) for request in transport.sent] == [
      ("POST", ACTIVITY_FEED_URL)
   ]
   assert not any("inbox_seen" in request.url for request in transport.sent)
   assert len(feed.earlier_items) == 69


def paced(transport: ScriptedTransport, client: AsyncClient) -> PacedSender:
   clock = FakeClock()
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)

   return PacedSender(transport, pacer, client._sender.pacing, client._sender.writes)


@pytest.mark.asyncio
async def test_the_async_namespace_sends_each_read_once_and_nothing_else() -> None:
   """Catches ``client.account`` reaching another read, or a method sending more than its
   one request."""

   transport = ScriptedTransport(
      [
         json_response(recorded("follow_requests.json")),
         json_response(recorded("activity_feed.json")),
      ]
   )
   client = AsyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR)
   await client._sender.aclose()
   client._sender = paced(transport, client)

   try:
      requests = await client.account.follow_requests()
      feed = await client.account.activity()
   finally:
      await client.aclose()

   assert isinstance(requests, FollowRequests)
   assert isinstance(feed, ActivityFeed)
   assert [request.url for request in transport.sent] == [FOLLOW_REQUESTS_URL, ACTIVITY_FEED_URL]


def test_the_blocking_namespace_sends_each_read_once_and_nothing_else() -> None:
   """The same two reads on the blocking surface, each on the loop thread."""

   transport = ScriptedTransport(
      [
         json_response(recorded("activity_feed.json")),
         json_response(recorded("follow_requests.json")),
      ]
   )

   with SyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR) as client:
      client._loop.run(client._impl._sender.aclose(), operation="the scripted sender swap")
      client._impl._sender = paced(transport, client._impl)
      feed = client.account.activity()
      requests = client.account.follow_requests()

   assert len(feed.earlier_items) == 69
   assert len(requests.accounts) == 1
   assert [request.url for request in transport.sent] == [ACTIVITY_FEED_URL, FOLLOW_REQUESTS_URL]


class FakeAccount:
   def __init__(self, requests: FollowRequests, feed: ActivityFeed) -> None:
      self.requests = requests
      self.feed = feed

   def follow_requests(self) -> FollowRequests:
      return self.requests

   def activity(self) -> ActivityFeed:
      return self.feed


class FakeAccountClient:
   def __init__(self) -> None:
      self.session = Session(sessionid="s", ds_user_id="1234567890", csrftoken="c")
      self.account = FakeAccount(
         replace(parse_follow_requests(recorded("follow_requests.json")), has_more=True),
         parse_activity_feed(recorded("activity_feed.json")),
      )
      self.closed = False

   def close(self) -> None:
      self.closed = True


def run_command(argv: list[str], client: FakeAccountClient) -> tuple[int, str]:
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


def test_dumpsta_follow_requests_prints_every_account_and_whether_more_exist() -> None:
   """Catches an account left out of either form, and the more flag dropped or inverted."""

   client = FakeAccountClient()
   code, out = run_command(["--json", "follow-requests"], client)
   payload = json.loads(out)
   text_code, text = run_command(["follow-requests"], FakeAccountClient())
   lines = text.strip().splitlines()
   row = recorded("follow_requests.json")["users"][0]

   assert (code, text_code) == (0, 0)
   assert payload["command"] == "follow-requests"
   assert payload["account_count"] == 1
   assert payload["more_available"] is True
   assert payload["accounts"][0]["id"] == row["id"]
   assert lines[0].startswith(f"{row['id']}  {row['username']}")
   assert lines[-1] == "accounts: 1  more_available: True"
   assert client.closed


def test_dumpsta_activity_prints_every_item_with_the_counts_and_the_last_page_flag() -> None:
   """Catches an item left out of either form, a list counted as another, and the last page
   flag or the sections dropped from the JSON."""

   code, out = run_command(["--json", "activity"], FakeAccountClient())
   payload = json.loads(out)
   text_code, text = run_command(["activity"], FakeAccountClient())
   lines = text.strip().splitlines()
   first = recorded_stories()[0]

   assert (code, text_code) == (0, 0)
   assert payload["command"] == "activity"
   assert (payload["new_count"], payload["earlier_count"], payload["priority_count"]) == (0, 69, 0)
   assert len(payload["earlier_items"]) == 69
   assert payload["is_last_page"] is True
   assert [section["first_index"] for section in payload["sections"]] == [0, 3, 5, 11, 60]
   assert (
      payload["earlier_items"][0]["links"][0]["username"] == first["args"]["links"][0]["username"]
   )
   assert len(lines) == 70
   assert lines[0].endswith(f"{first['notif_name']}  {first['args']['text']}")
   assert lines[-1] == "new: 0  earlier: 69  priority: 0  last_page: True"
