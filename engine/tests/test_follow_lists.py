"""Gates on E2 batch 3, the relationship lists: a page of an account's followers and the viewer's
relationship to each account on it.

Four defect classes live here.

A page can end the walk on the wrong signal. The second page of the owner's followers held seven
accounts where twelve were asked for and still said more existed, so a walk that stops on a
short page stops early, and a cursor read from anywhere but ``next_max_id`` cannot be followed.

The two requests can depart from what the browser's follow list sent: another path, another
page size, the page's cursor under another name, or a relationship asked for accounts other than
the ones on the page.

A relationship can land on the wrong account. The statuses answer is keyed by account id and
the page is a list, so a status matched by position rather than by id, or a flag read from its
neighbour, gives a caller the wrong relationship to a real person.

And the setting that leaves the second request out can fail to, or leave it in while dropping
the relationships.

The payloads are the recorded answers of 2026-09-27, pseudonymised by
``scripts/build_follow_lists_fixtures.py``. Nothing in this file touches the network.
"""

from __future__ import annotations

import copy
import io
import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

import pytest

from dumpstagram._cli.main import main
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.profiles import read_followers_page
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.web.parse.profiles import (
   attach_friendship_statuses,
   parse_followers_page,
   parse_friendship_statuses,
)
from dumpstagram._private.web.requests.profiles import (
   build_followers_request,
   build_friendship_statuses_request,
)
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY
from dumpstagram.client import SyncClient
from dumpstagram.errors import UpstreamRejected
from dumpstagram.models import Page, ProfileSummary
from dumpstagram.session import Session
from tests.test_direct import (
   FakeClock,
   ScriptedTransport,
   a_bootstrapped_session,
   json_response,
   make_paced,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "follow_lists"

SITE_ROOT = "https://www.instagram.com/"
USER_ID = "1234567890"
USERNAME = "an.account_1"
WEB_SESSION_ID = "abc123:def456:ghi789"
FOLLOWERS_URL = f"https://www.instagram.com/api/v1/friendships/{USER_ID}/followers/"
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
STATUS_FLAGS = (
   "following",
   "outgoing_request",
   "incoming_request",
   "is_bestie",
   "is_feed_favorite",
   "is_restricted",
)

SCRIPTED_BEHAVIOR = replace(PARITY, cookie_sync=False)


def recorded(name: str) -> Any:
   return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def recorded_users(name: str) -> list[dict[str, Any]]:
   users: list[dict[str, Any]] = recorded(name)["users"]

   return users


def recorded_statuses() -> dict[str, dict[str, Any]]:
   statuses: dict[str, dict[str, Any]] = recorded("friendship_statuses.json")["friendship_statuses"]

   return statuses


def sent_form(request: Any) -> list[tuple[str, str]]:
   return parse_qsl(request.content.decode("utf-8"))


def test_a_followers_page_maps_every_account_in_order_with_the_upstreams_cursor() -> None:
   """Catches accounts dropped or reordered, the id read from another key, a row's privacy
   dropped, and a cursor or terminator read from anywhere but ``next_max_id`` and
   ``has_more``."""

   answer = recorded("followers_first_page.json")
   users = answer["users"]
   page = parse_followers_page(answer)

   assert len(users) == 12
   assert [account.id for account in page.items] == [user["pk"] for user in users]
   assert [account.username for account in page.items] == [user["username"] for user in users]
   assert [account.is_private for account in page.items] == [user["is_private"] for user in users]
   assert {account.friendship_status for account in page.items} == {None}
   assert page.has_next_page is True
   assert page.end_cursor == answer["next_max_id"]
   assert len(page.end_cursor or "") == 120


def test_a_short_page_still_says_more_exist_and_only_has_more_ends_the_list() -> None:
   """Catches a walk that ends on a page shorter than the twelve asked for. The recorded second
   page held seven accounts and said ``has_more`` true. A planted false ends it, and a page
   without ``next_max_id`` carries no cursor rather than failing."""

   answer = recorded("followers_next_page.json")
   last = copy.deepcopy(answer)
   last["has_more"] = False
   without_cursor = copy.deepcopy(last)
   del without_cursor["next_max_id"]

   page = parse_followers_page(answer)

   assert len(page.items) == 7
   assert page.has_next_page is True
   assert page.end_cursor == answer["next_max_id"]
   assert parse_followers_page(last).has_next_page is False
   assert parse_followers_page(without_cursor).end_cursor is None


def test_a_followers_answer_whose_status_is_not_ok_is_refused() -> None:
   """Catches a REST refusal, which the classifier does not read, mapped as an empty page."""

   refused = {"message": "a refusal", "status": "fail", "users": []}

   with pytest.raises(UpstreamRejected):
      parse_followers_page(refused)


def test_each_relationship_flag_is_read_from_its_own_key() -> None:
   """Catches ``following`` read from a request flag or two flags swapped. Each flag in turn is
   planted alone on the first status, the others false, and must come out alone. The two flags
   the answer does not carry read as None."""

   first_id = next(iter(recorded_statuses()))

   for flag in STATUS_FLAGS:
      answer = recorded("friendship_statuses.json")
      planted = answer["friendship_statuses"][first_id]
      planted.update(dict.fromkeys(STATUS_FLAGS, False))
      planted[flag] = True

      status = parse_friendship_statuses(answer)[first_id]

      assert [getattr(status, name) for name in STATUS_FLAGS] == [
         name == flag for name in STATUS_FLAGS
      ]
      assert (status.followed_by, status.blocking) == (None, None)


def test_each_status_lands_on_the_account_it_names_and_an_unnamed_account_keeps_none() -> None:
   """Catches statuses matched by position rather than by id. The recorded answer names eleven
   of the page's twelve accounts, so the twelfth keeps None, and a status planted on the third
   account only must land there and nowhere else."""

   users = recorded_users("followers_first_page.json")
   answer = recorded("friendship_statuses.json")
   third_id = users[2]["pk"]

   for status in answer["friendship_statuses"].values():
      status["is_bestie"] = False

   answer["friendship_statuses"][third_id]["is_bestie"] = True
   page = attach_friendship_statuses(
      parse_followers_page(recorded("followers_first_page.json")),
      parse_friendship_statuses(answer),
   )
   statuses = [account.friendship_status for account in page.items]

   assert list(recorded_statuses()) == [user["pk"] for user in users[:11]]
   assert all(status is not None for status in statuses[:11])
   assert statuses[11] is None
   assert [status.is_bestie for status in statuses[:11] if status is not None] == [
      index == 2 for index in range(11)
   ]


def test_a_followers_page_is_the_follow_lists_rest_read() -> None:
   """The parity gate for the page. Catches another path, page size or surface, a body on a GET,
   the cursor sent under another name or on the first page, and a header set other than the
   follow list's."""

   session = a_bootstrapped_session()
   first = build_followers_request(session, USER_ID, web_session_id=WEB_SESSION_ID)
   later = build_followers_request(
      session, USER_ID, web_session_id=WEB_SESSION_ID, after="C000001ccc"
   )

   assert (first.method, first.url, first.content) == ("GET", FOLLOWERS_URL, None)
   assert dict(first.params) == {"count": "12", "search_surface": "follow_list_page"}
   assert dict(later.params) == {
      "count": "12",
      "search_surface": "follow_list_page",
      "max_id": "C000001ccc",
   }
   assert set(first.headers) == READ_HEADERS
   assert first.headers["referer"] == SITE_ROOT
   assert first.headers["x-csrftoken"] == session.csrftoken
   assert first.headers["x-web-session-id"] == WEB_SESSION_ID
   assert first.headers["x-ig-max-touch-points"] == "0"


def test_the_relationship_read_is_the_follow_lists_form_post() -> None:
   """The parity gate for the statuses. Catches another path, the ids joined another way or
   reordered, the form out of the browser's order, and the three headers a form POST adds
   missing."""

   session = a_bootstrapped_session()
   request = build_friendship_statuses_request(
      session, ["3", "1", "2"], web_session_id=WEB_SESSION_ID
   )
   form = sent_form(request)

   assert (request.method, request.url) == ("POST", STATUSES_URL)
   assert [name for name, _ in form] == ["user_ids", "jazoest", "fb_dtsg"]
   assert dict(form)["user_ids"] == "3,1,2"
   assert dict(form)["fb_dtsg"] == session.fb_dtsg
   assert set(request.headers) == READ_HEADERS | {"content-type", "origin", "x-instagram-ajax"}
   assert request.headers["content-type"] == "application/x-www-form-urlencoded"
   assert request.headers["x-instagram-ajax"] == "1047996704"


def first_page_with_statuses() -> ScriptedTransport:
   return ScriptedTransport(
      [
         json_response(recorded("followers_first_page.json")),
         json_response(recorded("friendship_statuses.json")),
      ]
   )


@pytest.mark.asyncio
async def test_a_page_is_followed_in_its_action_by_the_statuses_of_the_accounts_on_it() -> None:
   """Catches the statuses asked for other ids or in another order, a second web session id,
   and a page returned without the statuses its second request read."""

   transport = first_page_with_statuses()

   page = await read_followers_page(make_paced(transport), a_bootstrapped_session(), USER_ID)
   page_request, statuses_request = transport.sent
   users = recorded_users("followers_first_page.json")

   assert page_request.url == FOLLOWERS_URL
   assert statuses_request.url == STATUSES_URL
   assert dict(sent_form(statuses_request))["user_ids"] == ",".join(user["pk"] for user in users)
   assert page_request.headers["x-web-session-id"] == statuses_request.headers["x-web-session-id"]
   assert [account.friendship_status is not None for account in page.items] == [
      index < 11 for index in range(12)
   ]


@pytest.mark.asyncio
async def test_without_statuses_one_request_is_sent_and_no_token_is_fetched() -> None:
   """Catches the setting ignored, and a bootstrap spent on a GET that carries no page token."""

   transport = ScriptedTransport([json_response(recorded("followers_first_page.json"))])
   session = Session(sessionid="s", ds_user_id=USER_ID, csrftoken="c")

   page = await read_followers_page(make_paced(transport), session, USER_ID, with_statuses=False)

   assert [request.url for request in transport.sent] == [FOLLOWERS_URL]
   assert {account.friendship_status for account in page.items} == {None}


@pytest.mark.asyncio
async def test_an_empty_page_asks_for_no_statuses_and_a_username_is_refused_unsent() -> None:
   """Catches a statuses request for nobody, and a username put into the path."""

   empty = copy.deepcopy(recorded("followers_first_page.json"))
   empty["users"] = []
   empty["has_more"] = False
   transport = ScriptedTransport([json_response(empty)])
   sender = make_paced(transport)

   page = await read_followers_page(sender, a_bootstrapped_session(), USER_ID)

   assert page.items == ()
   assert len(transport.sent) == 1

   with pytest.raises(ValueError, match="numeric account id"):
      await read_followers_page(sender, a_bootstrapped_session(), USERNAME)

   assert len(transport.sent) == 1


def paced(transport: ScriptedTransport, client: AsyncClient) -> PacedSender:
   clock = FakeClock()
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)

   return PacedSender(transport, pacer, client._sender.pacing, client._sender.writes)


def two_pages_with_statuses() -> ScriptedTransport:
   return ScriptedTransport(
      [
         json_response(recorded("followers_first_page.json")),
         json_response(recorded("friendship_statuses.json")),
         json_response(recorded("followers_next_page.json")),
         json_response(recorded("friendship_statuses.json")),
      ]
   )


@pytest.mark.asyncio
async def test_the_async_walk_asks_for_the_next_page_with_the_first_pages_next_max_id() -> None:
   """Catches a walk that repeats the first page, passes another cursor, or stops at the first
   page's end."""

   transport = two_pages_with_statuses()
   client = AsyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR)
   await client._sender.aclose()
   client._sender = paced(transport, client)

   try:
      accounts = [account async for account in client.profiles.iter_followers(USER_ID, limit=15)]
   finally:
      await client.aclose()

   assert len(accounts) == 15
   assert [request.url for request in transport.sent] == [
      FOLLOWERS_URL,
      STATUSES_URL,
      FOLLOWERS_URL,
      STATUSES_URL,
   ]
   assert "max_id" not in transport.sent[0].params
   assert transport.sent[2].params["max_id"] == recorded("followers_first_page.json")["next_max_id"]


def test_the_blocking_walk_asks_for_the_next_page_with_the_first_pages_next_max_id() -> None:
   """The same walk on the blocking surface, each page read on the loop thread."""

   transport = two_pages_with_statuses()

   with SyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR) as client:
      client._loop.run(client._impl._sender.aclose(), operation="the scripted sender swap")
      client._impl._sender = paced(transport, client._impl)
      accounts = list(client.profiles.iter_followers(USER_ID, limit=13))

   assert len(accounts) == 13
   assert transport.sent[2].params["max_id"] == recorded("followers_first_page.json")["next_max_id"]


@pytest.mark.asyncio
async def test_the_behavior_setting_reaches_the_read_through_the_namespace() -> None:
   """Catches ``followers`` sending the statuses whatever the client's behavior says."""

   transport = ScriptedTransport([json_response(recorded("followers_first_page.json"))])
   behavior = replace(SCRIPTED_BEHAVIOR, follow_list_statuses=False)
   client = AsyncClient(a_bootstrapped_session(), behavior=behavior)
   await client._sender.aclose()
   client._sender = paced(transport, client)

   try:
      page = await client.profiles.followers(USER_ID)
   finally:
      await client.aclose()

   assert len(page.items) == 12
   assert [request.url for request in transport.sent] == [FOLLOWERS_URL]


class FakeProfiles:
   def __init__(self, pages: list[Page[ProfileSummary]]) -> None:
      self.pages = pages
      self.cursors: list[str | None] = []

   def followers(self, user_id: str, *, after: str | None = None) -> Page[ProfileSummary]:
      self.cursors.append(after)

      return self.pages[len(self.cursors) - 1]


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


def recorded_follower_pages() -> list[Page[ProfileSummary]]:
   first = attach_friendship_statuses(
      parse_followers_page(recorded("followers_first_page.json")),
      parse_friendship_statuses(recorded("friendship_statuses.json")),
   )
   second = parse_followers_page(recorded("followers_next_page.json"))

   return [replace(first, end_cursor="k1"), replace(second, has_next_page=False)]


def test_dumpsta_followers_walks_on_the_pages_own_cursor_and_stops_on_its_terminator() -> None:
   """Catches the command passing its first cursor again, reading past a last page when
   ``--pages`` allows more, or leaving the relationships out of the JSON."""

   client = FakeProfilesClient(recorded_follower_pages())

   code, out = run_command(["--json", "followers", USER_ID, "--pages", "5"], client)
   payload = json.loads(out)

   assert code == 0
   assert client.profiles.cursors == [None, "k1"]
   assert payload["pages_read"] == 2
   assert payload["account_count"] == 19
   assert payload["more_available"] is False
   assert payload["accounts"][0]["friendship_status"] is not None
   assert payload["accounts"][11]["friendship_status"] is None
   assert client.closed


def test_dumpsta_followers_text_ends_on_the_trailer_and_the_cursor_to_resume_from() -> None:
   """Catches the text form printing no cursor when more exist, or a count of the wrong list."""

   pages = recorded_follower_pages()[:1]
   code, out = run_command(["followers", USER_ID], FakeProfilesClient(pages))
   lines = out.strip().splitlines()

   assert code == 0
   assert len(lines) == 14
   assert lines[-2] == "pages_read: 1  accounts: 12  more_available: True"
   assert lines[-1] == "next_cursor: k1"


def test_dumpsta_followers_refuses_a_username(capsys: pytest.CaptureFixture[str]) -> None:
   """Catches an account named by username reaching a read keyed on the numeric id."""

   code, _ = run_command(["followers", USERNAME], FakeProfilesClient([]))

   assert code == 2
   assert "numeric id" in capsys.readouterr().err
