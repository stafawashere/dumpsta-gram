"""Gates on E2 batch 11d: the blocked accounts list and the post page load.

The blocked list is two Bloks fetches in one action, the settings screen's app and then the
reloader action whose container ids the screen's own answer names. The defect classes: another
form, header set or route on either fetch; the action sent with ids the screen did not name, or
sent without the screen; the page's unblock handler sent; a row mapped into the wrong field, the
screen's own line read as a name, or a flag inverted; and a screen or list laid out otherwise
accepted rather than refused.

The post page load is the parity route of ``media.by_code`` and the whole of ``media.page``. The
defect classes: a request of the recorded burst missing, extra, out of the page's order or
grouped unlike it, a post query sent where the document already carries the post; a part of the
page read from the wrong preload; a document missing a preload returning a partial page, or
costing ``by_code`` a post it carries; the cookie sync tail scheduled for the wrong page or after
a failed read; and the behavior setting dropped on the way down, or the departure sending more
than the post query.

The answers are the recorded ones of 2026-09-27, pseudonymised by
``scripts/build_post_page_fixtures.py``, and the documents are synthetic around the recorded
preloads. Nothing in this file touches the network.
"""

from __future__ import annotations

import asyncio
import copy
import io
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pytest

from dumpstagram._cli.main import main
from dumpstagram._core.account import read_blocked_accounts
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.posts import read_post, read_post_page
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import Request, Response
from dumpstagram._private.web.classify import classify_preloaded
from dumpstagram._private.web.documents.media import POST_BY_SHORTCODE
from dumpstagram._private.web.documents.page_load import (
   BADGE_COUNT,
   CHAT_TABS_JEWEL,
   OMNI_PICKER_NULL_STATE,
   STORIES_TRAY,
)
from dumpstagram._private.web.parse.account import (
   parse_blocked_accounts,
   parse_blocked_accounts_screen,
)
from dumpstagram._private.web.parse.media import (
   parse_comment_page,
   parse_more_from_author,
   parse_post_detail,
)
from dumpstagram._private.web.requests.account import (
   build_blocked_accounts_reloader_request,
   build_blocked_accounts_screen_request,
)
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY, PostRoute
from dumpstagram.client import SyncClient
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import BlockedAccount, PostDetail, PostPage
from dumpstagram.session import Session
from tests.test_direct import (
   BLOKS_VERSION_ID,
   FakeClock,
   ScriptedTransport,
   a_bootstrapped_session,
   json_response,
   make_paced,
)
from tests.test_feed_first_page import data_script, home_document, stream_call
from tests.test_page_load import DEVICE_ID, LOGIN_SURFACE, label, variables_of, with_device_id

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "post_page"

ORIGIN = "https://www.instagram.com"
BLOCKS_FETCH_URL = f"{ORIGIN}/async/wbloks/fetch/"
BLOCKED_PAGE = f"{ORIGIN}/accounts/blocked_accounts/"
BLOCKED_APP = "com.instagram.portable_settings.privacy.blocked_accounts_v2"
BLOCKED_RELOADER = "com.instagram.portable_settings.blocked_accounts.blocked_accounts_reloader"
BLOCKED_ROUTE = "comet.igweb.PolarisBlockedAccountsSettingsRoute"
BLOKS_HEADERS = {
   "accept",
   "accept-language",
   "content-type",
   "origin",
   "referer",
   "sec-fetch-dest",
   "sec-fetch-mode",
   "sec-fetch-site",
   "user-agent",
}
BLOKS_FORM = [
   "__d",
   "__user",
   "__a",
   "__req",
   "__hs",
   "dpr",
   "__ccg",
   "__rev",
   "__hsi",
   "__comet_req",
   "fb_dtsg",
   "jazoest",
   "lsd",
   "__spin_r",
   "__spin_b",
   "__spin_t",
   "__crn",
   "params",
]

QUOTED = r'"(?:[^"\\]|\\.)*"'
BOOL = r"\(bk\.action\.bool\.Const, (true|false)\)"
BLOCKED_ROW = re.compile(
   rf"\(bk\.action\.array\.Make, ({QUOTED}), ({QUOTED}), ({QUOTED}), {BOOL}, ({QUOTED}), {BOOL}\)"
)
RELOADER_IDS = re.compile(
   r'"container_id_of_list", "container_id_of_rows"\), \(bk\.action\.array\.Make, '
   r"\(bk\.action\.i32\.Const, (\d+)\), \(bk\.action\.i32\.Const, (\d+)\)"
)

POST_ROOT = "PolarisPostRootQuery"
POST_COMMENTS = "PolarisPostCommentsContainerQuery"
POST_GRID = "PolarisDesktopPostPageRelatedMediaGridQuery"

SCRIPTED_BEHAVIOR = replace(PARITY, cookie_sync=False)


def recorded(name: str) -> Any:
   return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def jsonp_response(parsed: dict[str, Any]) -> Response:
   return Response(
      status_code=200,
      headers={"content-type": "text/javascript; charset=utf-8"},
      content=("for (;;);" + json.dumps(parsed)).encode("utf-8"),
      final_url=BLOCKS_FETCH_URL,
   )


def sent_form(request: Request) -> list[tuple[str, str]]:
   return parse_qsl(request.content.decode("utf-8"), keep_blank_values=True)


def list_script(answer: dict[str, Any]) -> str:
   [entry] = answer["payload"]["layout"]["bloks_payload"]["data"]

   return str(entry["data"]["initial_lispy"])


def rows_written_in(script: str) -> list[tuple[str, str, str, bool, str, bool]]:
   """The rows a list's script holds, read with a pattern of its own rather than the engine's
   reader."""

   return [
      (
         json.loads(user_id),
         json.loads(username),
         json.loads(secondary),
         verified == "true",
         json.loads(picture),
         automatic == "true",
      )
      for user_id, username, secondary, verified, picture, automatic in BLOCKED_ROW.findall(script)
   ]


def strings_in(value: Any) -> list[str]:
   if isinstance(value, dict):
      return [found for inner in value.values() for found in strings_in(inner)]

   if isinstance(value, list):
      return [found for inner in value for found in strings_in(inner)]

   return [value] if isinstance(value, str) else []


def screen_ids() -> tuple[int, int]:
   scripts = strings_in(recorded("blocked_screen.json"))
   [(list_id, rows_id)] = [pair for script in scripts for pair in RELOADER_IDS.findall(script)]

   return int(list_id), int(rows_id)


def post_item() -> dict[str, Any]:
   root = recorded("post_page_preloads.json")[POST_ROOT]["data"]

   return dict(root["xdt_api__v1__media__shortcode__web_info"]["items"][0])


CODE = str(post_item()["code"])
POST_PAGE = f"{ORIGIN}/p/{CODE}/"
DOCUMENT = f"GET /p/{CODE}/"

POST_RECORDED_BURST = [
   [DOCUMENT],
   [BADGE_COUNT.friendly_name],
   [STORIES_TRAY.friendly_name],
   [CHAT_TABS_JEWEL.friendly_name, OMNI_PICKER_NULL_STATE.friendly_name],
   [LOGIN_SURFACE],
]
"""The post page cold load of ``run-2026-09-27-131354-b10-post-page-cold``: the document at 0 ms,
the badge count at 1998, the stories tray at 2388, the jewel and the omni picker at 2429 and 2431,
and the login interstitial alone at 2643. Left out of it: ``/data/manifest.json`` at 1451 and
``fxcal`` at 2174, which have no verified finding, the feed timeline prefetch at 2386, which the
profile and inbox loads leave out too, and the cookie sync from 6978, which is a later step. The
second cold load sent the same five with the jewel pair before the stories tray (W112)."""


def a_post_document(
   *,
   comments: dict[str, Any] | None = None,
   without: tuple[str, ...] = (),
   device_id: bool = True,
) -> str:
   preloads = recorded("post_page_preloads.json")

   if comments is not None:
      preloads[POST_COMMENTS] = comments

   calls = [
      stream_call(f"adp_{name}RelayPreloader_{index:012x}", result)
      for index, (name, result) in enumerate(preloads.items())
      if name not in without
   ]
   document = home_document(data_script(*calls))

   return with_device_id(document) if device_id else document


def html_answer(body: str) -> Response:
   return Response(
      status_code=200,
      headers={"content-type": "text/html; charset=utf-8"},
      content=body.encode("utf-8"),
      final_url=POST_PAGE,
   )


class BurstTransport:
   """Answers the post page document with ``document`` and every other request with an empty
   answer, and records which requests were in flight together."""

   def __init__(self, document: str | None = None) -> None:
      self.document = html_answer(document if document is not None else a_post_document())
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

      if name == POST_BY_SHORTCODE.friendly_name:
         return json_response(recorded("post_page_preloads.json")[POST_ROOT])

      return json_response({"data": {"companion": {}}, "extensions": {"is_final": True}})


def paced(transport: Any) -> PacedSender:
   clock = FakeClock()

   return PacedSender(transport, Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0))


class RecordingCookieSync:
   def __init__(self) -> None:
      self.started: list[str] = []

   def start(
      self, session: Session, page_url: str, *, loaded_at: float, user_agent: str = ""
   ) -> None:
      self.started.append(page_url)


def the_recorded_post() -> PostDetail:
   return parse_post_detail(classify_preloaded(recorded("post_page_preloads.json")[POST_ROOT]))


def test_the_blocked_accounts_are_the_reloaders_rows_in_order_with_both_flags() -> None:
   """Catches a row dropped or reordered, the secondary text read as another field or its empty
   value filled, and either flag inverted or read from the other."""

   answer = recorded("blocked_list.json")
   list_id, rows_id = screen_ids()
   screen = parse_blocked_accounts_screen(recorded("blocked_screen.json"))

   blocked = parse_blocked_accounts(answer, screen)
   expected = rows_written_in(list_script(answer))

   assert len(expected) == 14
   assert [
      (
         entry.id,
         entry.username,
         entry.secondary_text,
         entry.is_verified,
         entry.profile_pic_url,
         entry.is_auto_blocked,
      )
      for entry in blocked
   ] == expected
   assert {entry.is_auto_blocked for entry in blocked} == {True, False}
   assert "" in [entry.secondary_text for entry in blocked]
   assert (screen.list_id, screen.rows_id) == (list_id, rows_id)


def test_the_screen_line_of_an_automatic_row_is_kept_as_text_and_not_as_a_name() -> None:
   """Catches the model growing a ``full_name`` read from the screen's own line, which every row
   blocked automatically carried in place of a name."""

   blocked = parse_blocked_accounts(
      recorded("blocked_list.json"), parse_blocked_accounts_screen(recorded("blocked_screen.json"))
   )
   automatic_lines = {entry.secondary_text for entry in blocked if entry.is_auto_blocked}
   manual_lines = [entry.secondary_text for entry in blocked if not entry.is_auto_blocked]

   assert len(automatic_lines) == 1
   assert len(set(manual_lines)) == len(manual_lines)
   assert not hasattr(blocked[0], "full_name")
   assert all(isinstance(entry, BlockedAccount) for entry in blocked)


def test_the_blocked_fetches_are_the_settings_pages_two_fetches() -> None:
   """The parity gate for both Bloks fetches. Catches another app, type, version, route or
   referer, a form field added, dropped or moved, the screen's ``params`` other than an empty
   object, the action's ids in another order or form, and an ``x-`` header the page's fetches
   did not carry."""

   session = a_bootstrapped_session()
   list_id, rows_id = screen_ids()
   screen = build_blocked_accounts_screen_request(session)
   reloader = build_blocked_accounts_reloader_request(session, list_id=list_id, rows_id=rows_id)

   for request, app, kind in ((screen, BLOCKED_APP, "app"), (reloader, BLOCKED_RELOADER, "action")):
      url = urlsplit(request.url)
      form = sent_form(request)

      assert request.method == "POST"
      assert f"{url.scheme}://{url.netloc}{url.path}" == BLOCKS_FETCH_URL
      assert parse_qsl(url.query) == [("appid", app), ("type", kind), ("__bkv", BLOKS_VERSION_ID)]
      assert [name for name, _ in form] == BLOKS_FORM
      assert dict(form)["__crn"] == BLOCKED_ROUTE
      assert set(request.headers) == BLOKS_HEADERS
      assert request.headers["referer"] == BLOCKED_PAGE

   assert dict(sent_form(screen))["params"] == "{}"
   assert dict(sent_form(reloader))["params"] == (
      f'{{"container_id_of_list":{list_id},"container_id_of_rows":{rows_id}}}'
   )


def _screen_without_the_reloader(screen: dict[str, Any], answer: dict[str, Any]) -> None:
   text = json.dumps(screen).replace("blocked_accounts_reloader", "blocked_accounts_other")
   screen.clear()
   screen.update(json.loads(text))


def _screen_naming_it_twice(screen: dict[str, Any], answer: dict[str, Any]) -> None:
   [script] = [
      found
      for found in re.findall(r'"(\(bk\.action\.core\.Match(?:[^"\\]|\\.)*)"', json.dumps(screen))
      if "blocked_accounts_reloader" in found
   ]
   flexbox = screen["payload"]["layout"]["bloks_payload"]["tree"]["bk.components.Flexbox"]
   flexbox["on_appear"] = json.loads(f'"{script}"')


def _two_data_entries(screen: dict[str, Any], answer: dict[str, Any]) -> None:
   data = answer["payload"]["layout"]["bloks_payload"]["data"]
   data.append({**copy.deepcopy(data[0]), "id": "another_0"})


def _no_embedded_payload(screen: dict[str, Any], answer: dict[str, Any]) -> None:
   answer["payload"]["layout"]["bloks_payload"]["embedded_payloads"] = []


def _another_container_replaced(screen: dict[str, Any], answer: dict[str, Any]) -> None:
   action = answer["payload"]["layout"]["bloks_payload"]["tree"]["bk.components.internal.Action"]
   list_id, _ = screen_ids()
   action["handler"] = action["handler"].replace(
      f"(bk.action.i64.Const, {list_id})", "(bk.action.i64.Const, 12345)", 1
   )


def _rewrite_list(answer: dict[str, Any], old: str, new: str) -> None:
   [entry] = answer["payload"]["layout"]["bloks_payload"]["data"]
   script = entry["data"]["initial_lispy"]
   assert old in script
   entry["data"]["initial_lispy"] = script.replace(old, new, 1)


def _the_keys_in_another_order(screen: dict[str, Any], answer: dict[str, Any]) -> None:
   _rewrite_list(answer, '"username", "secondary_text"', '"secondary_text", "username"')


def _an_id_that_is_not_a_number(screen: dict[str, Any], answer: dict[str, Any]) -> None:
   first_id = rows_written_in(list_script(answer))[0][0]
   _rewrite_list(answer, f'"{first_id}"', '"not-a-number"')


def _a_flag_that_is_not_a_constant(screen: dict[str, Any], answer: dict[str, Any]) -> None:
   _rewrite_list(answer, "(bk.action.bool.Const, false)", '(bk.action.bloks.GetVariable2, "x")')


BLOCKED_LAYOUTS = {
   "a screen that names no reloader": _screen_without_the_reloader,
   "a screen that names it twice": _screen_naming_it_twice,
   "two data entries": _two_data_entries,
   "no embedded payload": _no_embedded_payload,
   "another container replaced": _another_container_replaced,
   "the keys in another order": _the_keys_in_another_order,
   "an id that is not a number": _an_id_that_is_not_a_number,
   "a flag that is not a constant": _a_flag_that_is_not_a_constant,
}


@pytest.mark.parametrize("change", sorted(BLOCKED_LAYOUTS))
def test_a_blocked_list_laid_out_otherwise_raises_rather_than_guessing(change: str) -> None:
   """Catches a screen or a list laid out unlike the four read being accepted, and the action
   built from ids the screen did not name once and only once."""

   screen = recorded("blocked_screen.json")
   answer = recorded("blocked_list.json")
   BLOCKED_LAYOUTS[change](screen, answer)

   with pytest.raises(SchemaChanged):
      parse_blocked_accounts(answer, parse_blocked_accounts_screen(screen))


@pytest.mark.asyncio
async def test_the_blocked_read_is_the_screen_then_its_reloader_and_never_an_unblock() -> None:
   """Catches the action sent without the screen, with ids other than the ones its answer named,
   in another order, twice, or the page's unblock handler sent."""

   transport = ScriptedTransport(
      [
         jsonp_response(recorded("blocked_screen.json")),
         jsonp_response(recorded("blocked_list.json")),
      ]
   )
   list_id, rows_id = screen_ids()

   blocked = await read_blocked_accounts(make_paced(transport), a_bootstrapped_session())

   screen, reloader = transport.sent
   assert BLOCKED_APP in screen.url
   assert BLOCKED_RELOADER in reloader.url
   assert json.loads(dict(sent_form(reloader))["params"]) == {
      "container_id_of_list": list_id,
      "container_id_of_rows": rows_id,
   }
   assert not any("unblock" in request.url for request in transport.sent)
   assert len(blocked) == 14


@pytest.mark.asyncio
async def test_a_post_page_load_sends_the_recorded_burst_in_its_groups() -> None:
   """Catches a companion missing, extra, out of order or grouped unlike the recorded load, a
   second quick promotion call as a profile load sends, and a post, comments or grid query sent
   where the document carries each."""

   transport = BurstTransport()

   await read_post(
      paced(transport), a_bootstrapped_session(), CODE, route=PostRoute.PAGE, companions=True
   )

   assert transport.groups == POST_RECORDED_BURST


@pytest.mark.asyncio
async def test_every_companion_names_the_post_page_and_the_documents_device_id() -> None:
   """Catches a companion claiming another page as referer, and a device id generated where the
   document carried one."""

   transport = BurstTransport()

   await read_post(
      paced(transport), a_bootstrapped_session(), CODE, route=PostRoute.PAGE, companions=True
   )

   iris = [
      request
      for request in transport.sent[1:]
      if label(request) in (BADGE_COUNT.friendly_name, CHAT_TABS_JEWEL.friendly_name)
   ]

   assert {request.headers["referer"] for request in transport.sent[1:]} == {POST_PAGE}
   assert len(iris) == 2
   assert {variables_of(request)["device_id_for_iris_subscription"] for request in iris} == {
      DEVICE_ID
   }


@pytest.mark.asyncio
async def test_by_code_on_the_page_reads_the_post_out_of_the_document() -> None:
   """Catches the post read from another preload, a query sent for it, and a missing comments
   or grid preload costing the caller the post the document carries."""

   transport = BurstTransport(a_post_document(without=(POST_COMMENTS, POST_GRID)))

   post = await read_post(paced(transport), a_bootstrapped_session(), CODE, route=PostRoute.PAGE)

   assert [label(request) for request in transport.sent] == [DOCUMENT]
   assert post == the_recorded_post()


@pytest.mark.asyncio
async def test_the_page_reads_each_part_out_of_its_own_preload() -> None:
   """Catches the comments or the grid read from another preload, a comment dropped, the
   upstream's terminator replaced, or the grid trimmed of the post itself."""

   comments = recorded("first_comments.json")
   transport = BurstTransport(a_post_document(comments=comments))

   page = await read_post_page(paced(transport), a_bootstrapped_session(), CODE)

   grid = recorded("post_page_preloads.json")[POST_GRID]

   assert isinstance(page, PostPage)
   assert page.post == the_recorded_post()
   assert page.comments == parse_comment_page(comments)
   assert len(page.comments.items) == 2
   assert page.author_grid == parse_more_from_author(classify_preloaded(grid))
   assert len(page.author_grid) == 7
   assert page.post.pk in [thumbnail.pk for thumbnail in page.author_grid]


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [POST_ROOT, POST_COMMENTS, POST_GRID])
async def test_a_page_missing_a_preload_raises_and_schedules_no_tail(missing: str) -> None:
   """Catches a partial page returned when the document stops carrying one of its three parts,
   and the cookie sync tail scheduled after a read that failed."""

   transport = BurstTransport(a_post_document(without=(missing,)))
   cookie_sync = RecordingCookieSync()

   with pytest.raises(SchemaChanged):
      await read_post_page(
         paced(transport),
         a_bootstrapped_session(),
         CODE,
         cookie_sync=cookie_sync,  # type: ignore[arg-type]
      )

   assert cookie_sync.started == []


@pytest.mark.asyncio
async def test_a_page_load_schedules_the_cookie_sync_tail_for_the_post_page() -> None:
   """Catches the tail scheduled for another page, or not at all, after a load that succeeded."""

   cookie_sync = RecordingCookieSync()

   await read_post(
      paced(BurstTransport()),
      a_bootstrapped_session(),
      CODE,
      route=PostRoute.PAGE,
      cookie_sync=cookie_sync,  # type: ignore[arg-type]
   )

   assert cookie_sync.started == [POST_PAGE]


def client_over(transport: Any, behavior: Any = SCRIPTED_BEHAVIOR) -> AsyncClient:
   client = AsyncClient(a_bootstrapped_session(), behavior=behavior)
   client._sender = paced(transport)

   return client


@pytest.mark.asyncio
async def test_by_code_loads_the_page_by_default_and_the_departure_sends_the_query_alone() -> None:
   """Catches the setting dropped on the way down, so that the page is the documented default
   and not the sent one, and the departure sending anything but the post query."""

   page_transport = BurstTransport()
   query_transport = BurstTransport()
   by_page = client_over(page_transport)
   by_query = client_over(query_transport, replace(SCRIPTED_BEHAVIOR, post_route=PostRoute.QUERY))

   try:
      page_post = await by_page.media.by_code(CODE)
      query_post = await by_query.media.by_code(CODE)
   finally:
      await by_page.aclose()
      await by_query.aclose()

   assert PARITY.post_route is PostRoute.PAGE
   assert page_transport.groups == POST_RECORDED_BURST
   assert [label(request) for request in query_transport.sent] == [POST_BY_SHORTCODE.friendly_name]
   assert page_post == query_post == the_recorded_post()


@pytest.mark.asyncio
async def test_the_async_namespace_page_and_blocked_send_their_reads_and_nothing_else() -> None:
   """Catches ``media.page`` sending a query beside the document with the companions off, and
   ``account.blocked`` reaching another read."""

   transport = BurstTransport()
   client = client_over(transport, replace(SCRIPTED_BEHAVIOR, page_load_companions=False))

   try:
      page = await client.media.page(CODE)
   finally:
      await client.aclose()

   blocked_transport = ScriptedTransport(
      [
         jsonp_response(recorded("blocked_screen.json")),
         jsonp_response(recorded("blocked_list.json")),
      ]
   )
   blocked_client = client_over(blocked_transport)

   try:
      blocked = await blocked_client.account.blocked()
   finally:
      await blocked_client.aclose()

   assert [label(request) for request in transport.sent] == [DOCUMENT]
   assert page.post == the_recorded_post()
   assert len(blocked) == 14
   assert [urlsplit(request.url).path for request in blocked_transport.sent] == [
      "/async/wbloks/fetch/",
      "/async/wbloks/fetch/",
   ]


def test_the_blocking_namespace_page_and_blocked_answer_as_their_twins() -> None:
   """The same two reads on the blocking surface, each on the loop thread."""

   transport = ScriptedTransport(
      [
         html_answer(a_post_document()),
         jsonp_response(recorded("blocked_screen.json")),
         jsonp_response(recorded("blocked_list.json")),
      ]
   )
   behavior = replace(SCRIPTED_BEHAVIOR, page_load_companions=False)

   with SyncClient(a_bootstrapped_session(), behavior=behavior) as client:
      client._loop.run(client._impl._sender.aclose(), operation="the scripted sender swap")
      client._impl._sender = paced(transport)
      page = client.media.page(CODE)
      blocked = client.account.blocked()

   assert page.post == the_recorded_post()
   assert len(blocked) == 14
   assert [request.method for request in transport.sent] == ["GET", "POST", "POST"]


class FakeMedia:
   def page(self, code: str) -> PostPage:
      return PostPage(
         post=the_recorded_post(),
         comments=parse_comment_page(recorded("first_comments.json")),
         author_grid=parse_more_from_author(
            classify_preloaded(recorded("post_page_preloads.json")[POST_GRID])
         ),
      )


class FakeAccount:
   def blocked(self) -> tuple[BlockedAccount, ...]:
      return parse_blocked_accounts(
         recorded("blocked_list.json"),
         parse_blocked_accounts_screen(recorded("blocked_screen.json")),
      )


class FakeClient:
   def __init__(self) -> None:
      self.session = Session(sessionid="s", ds_user_id="1234567890", csrftoken="c")
      self.media = FakeMedia()
      self.account = FakeAccount()
      self.closed = False

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


def test_dumpsta_blocked_prints_every_account_in_order_with_its_flag() -> None:
   """Catches an account left out or reordered in either form, the automatic flag dropped or
   inverted, and the screen's own line printed as if it were a name."""

   client = FakeClient()
   code, out = run_command(["--json", "blocked"], client)
   payload = json.loads(out)
   text_code, text = run_command(["blocked"], FakeClient())
   lines = text.strip().splitlines()
   expected = rows_written_in(list_script(recorded("blocked_list.json")))

   assert (code, text_code) == (0, 0)
   assert payload["command"] == "blocked"
   assert payload["account_count"] == 14
   assert [account["id"] for account in payload["accounts"]] == [row[0] for row in expected]
   assert [account["is_auto_blocked"] for account in payload["accounts"]] == [
      row[5] for row in expected
   ]
   assert [account["secondary_text"] for account in payload["accounts"]] == [
      row[2] for row in expected
   ]
   assert lines[:-1] == [f"{row[0]}  {row[1]}{'  auto' if row[5] else ''}" for row in expected]
   assert lines[-1] == "blocked: 14"
   assert client.closed


def test_dumpsta_post_page_prints_the_post_its_comments_and_the_grid() -> None:
   """Catches a part of the page left out of either form, a comment or a grid post dropped, and
   the comments' terminator lost."""

   code, out = run_command(["--json", "post-page", CODE], FakeClient())
   payload = json.loads(out)
   text_code, text = run_command(["post-page", CODE], FakeClient())
   comments = recorded("first_comments.json")
   comment_ids = [
      edge["node"]["pk"]
      for edge in comments["data"]["xdt_api__v1__media__media_id__comments__connection"]["edges"]
   ]

   assert (code, text_code) == (0, 0)
   assert payload["command"] == "post-page"
   assert payload["post"]["code"] == CODE
   assert [comment["id"] for comment in payload["comments"]["comments"]] == comment_ids
   assert payload["comments"]["more_available"] is False
   assert len(payload["author_grid"]) == 7
   assert text.startswith(f"{CODE}  pk {post_item()['pk']}")
   assert "2 comments, no more comments" in text
   assert text.rstrip().endswith("posts: 7")
