"""Gates on E2 batch 11c, the viewer's own account from the capture night: the saved posts, the
saved collections and the close friends list.

Four defect classes live here.

A request can depart from what was replayed: another path, a query or a body on the saved posts
GET, other variables on the saved tab, another form or header set on the close friends fetch, or
its Bloks version left out. The close friends page also sends a ``close_friend_count_updater``
action whose effect is UNRESOLVED, and nothing here may send it.

A mapper can put a value in the wrong place or invent one. A saved post carries no comment count
and the saved advertisement no counts flag, so neither may be filled in; a collection's covers
come in two shapes; and the close friends are one of two lists of accounts in a Bloks tree, told
apart only by the state their rows start in.

A structure the engine has not read can be accepted silently. A Bloks tree laid out differently
must raise rather than return the wrong list or part of one.

A list can end on the wrong signal. Neither saved read has been observed past its first page, so
the upstream's own flags are the only thing a caller has.

The payloads are the recorded answers of 2026-09-27, pseudonymised by
``scripts/build_own_account_more_fixtures.py``. Nothing in this file touches the network.
"""

from __future__ import annotations

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
from dumpstagram._core.account import read_close_friends, read_saved_posts
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import Response
from dumpstagram._private.web.parse.account import (
   parse_close_friends,
   parse_saved_collections,
   parse_saved_posts,
)
from dumpstagram._private.web.parse.bloks import BloksAtom, BloksCall, read_bloks_script
from dumpstagram._private.web.requests.account import (
   build_close_friends_request,
   build_saved_collections_request,
   build_saved_posts_request,
)
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY
from dumpstagram.client import SyncClient
from dumpstagram.errors import AuthenticationFailed, SchemaChanged, UpstreamRejected
from dumpstagram.models import (
   ProfileSummary,
   SavedCollectionKind,
   SavedCollections,
   SavedPosts,
)
from dumpstagram.session import Session
from tests.test_direct import (
   BLOKS_VERSION_ID,
   FakeClock,
   ScriptedTransport,
   a_bootstrapped_session,
   json_response,
   make_paced,
   sent_variables,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "own_account_more"

SITE_ROOT = "https://www.instagram.com/"
SAVED_POSTS_URL = "https://www.instagram.com/api/v1/feed/saved/posts/"
API_GRAPHQL_URL = "https://www.instagram.com/api/graphql"
BLOKS_FETCH_URL = "https://www.instagram.com/async/wbloks/fetch/"
CLOSE_FRIENDS_PAGE = "https://www.instagram.com/accounts/close_friends/"
CLOSE_FRIENDS_APP = "com.instagram.portable_settings.privacy.close_friends_screen_v2"
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
CLOSE_FRIENDS_HEADERS = {
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
CLOSE_FRIENDS_FORM = [
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

CLOSE_FRIENDS_LIST = "110655765_0"
CLOSE_FRIENDS_SELECTED = "110655766_0"
OFFERED_LIST = "110655784_0"
OFFERED_SELECTED = "110655786_0"

ACCOUNT_ROW = re.compile(
   r"\(bk\.action\.i(?:64|32)\.Const, (\d+)\), (\"(?:[^\"\\]|\\.)*\"), (\"(?:[^\"\\]|\\.)*\"), "
   r"(\"(?:[^\"\\]|\\.)*\"), \(bk\.action\.bool\.Const, (true|false)\)"
)

SCRIPTED_BEHAVIOR = replace(PARITY, cookie_sync=False)


def recorded(name: str) -> Any:
   return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def bloks_data(answer: dict[str, Any]) -> dict[str, dict[str, Any]]:
   entries = answer["payload"]["layout"]["bloks_payload"]["data"]

   return {entry["id"]: entry["data"] for entry in entries}


def rows_written_in(script: str) -> list[tuple[str, str, str, str, bool]]:
   """The accounts a list's script holds, read with a pattern of its own rather than the
   engine's reader."""

   return [
      (user_id, json.loads(username), json.loads(name), json.loads(picture), flag == "true")
      for user_id, username, name, picture, flag in ACCOUNT_ROW.findall(script)
   ]


def jsonp_response(parsed: dict[str, Any]) -> Response:
   return Response(
      status_code=200,
      headers={"content-type": "text/javascript; charset=utf-8"},
      content=("for (;;);" + json.dumps(parsed)).encode("utf-8"),
      final_url=BLOKS_FETCH_URL,
   )


def sent_form(request: Any) -> list[tuple[str, str]]:
   return parse_qsl(request.content.decode("utf-8"), keep_blank_values=True)


def test_every_saved_post_maps_in_order_with_no_comment_count_invented() -> None:
   """Catches a post dropped or reordered, an identifier or the author read from a neighbour,
   the like state lost, and a comment count or ``is_seen`` put on a model whose read carries
   neither."""

   answer = recorded("saved_posts.json")
   saved = parse_saved_posts(answer)
   items = [item["media"] for item in answer["items"]]

   assert [post.pk for post in saved.posts] == [item["pk"] for item in items]
   assert [post.code for post in saved.posts] == [item["code"] for item in items]
   assert [post.id for post in saved.posts] == [item["id"] for item in items]
   assert [post.author.username for post in saved.posts] == [
      item["user"]["username"] for item in items
   ]
   assert [post.has_liked for post in saved.posts] == [item["has_liked"] for item in items]
   assert [post.product_type for post in saved.posts] == ["clips", "clips", "ad"]
   assert not any("comment_count" in item for item in items)
   assert not hasattr(saved.posts[0], "comment_count")
   assert not hasattr(saved.posts[0], "is_seen")


def test_what_the_saved_advertisement_lacks_is_none_and_not_a_default() -> None:
   """Catches the advertisement's missing counts flag read as False or True, its missing
   ``clips_metadata`` refused, and the reels' flag and audio lost."""

   answer = recorded("saved_posts.json")
   advertisement = answer["items"][2]["media"]
   saved = parse_saved_posts(answer)
   reel, _, saved_advertisement = saved.posts

   assert "like_and_view_counts_disabled" not in advertisement
   assert "clips_metadata" not in advertisement
   assert saved_advertisement.like_and_view_counts_disabled is None
   assert saved_advertisement.audio is None
   assert reel.like_and_view_counts_disabled is False
   assert reel.audio is not None
   assert reel.video_duration is not None


def test_the_saved_posts_more_flag_is_more_available_and_a_refusal_is_not_an_empty_page() -> None:
   """Catches ``has_more`` read from anything but ``more_available``, such as the presence of
   ``next_max_id``, and a refusal mapped as no saved posts."""

   answer = recorded("saved_posts.json")
   last_page = {**answer, "more_available": False}
   refused = {**answer, "status": "fail"}

   assert parse_saved_posts(answer).has_more is True
   assert parse_saved_posts(last_page).has_more is False

   with pytest.raises(UpstreamRejected):
      parse_saved_posts(refused)


def test_the_saved_posts_read_is_a_bare_get_with_the_follow_lists_headers() -> None:
   """The parity gate for the saved view. Catches another path, a query or a body on the GET,
   another referer, and a header set other than the REST family's."""

   session = a_bootstrapped_session()
   request = build_saved_posts_request(session, web_session_id=WEB_SESSION_ID)

   assert (request.method, request.url, request.content) == ("GET", SAVED_POSTS_URL, None)
   assert dict(request.params) == {}
   assert set(request.headers) == READ_HEADERS
   assert request.headers["referer"] == SITE_ROOT
   assert request.headers["x-csrftoken"] == session.csrftoken


@pytest.mark.asyncio
async def test_the_saved_posts_read_is_one_get_and_spends_no_bootstrap() -> None:
   """Catches a bootstrap spent on a GET that carries no page token, and a second request."""

   transport = ScriptedTransport([json_response(recorded("saved_posts.json"))])
   session = Session(sessionid="s", ds_user_id="1234567890", csrftoken="c")

   saved = await read_saved_posts(make_paced(transport), session)

   assert [request.url for request in transport.sent] == [SAVED_POSTS_URL]
   assert len(saved.posts) == 3


def test_each_collection_maps_its_kind_count_and_covers() -> None:
   """Catches the kind read from the id or the name, the audio collection's null count read as
   0, a cover list dropped, the two cover shapes mixed, and a cover's renditions cut to one."""

   answer = recorded("saved_collections.json")
   edges = answer["data"]["viewer"]["collections_unified_with_auto_collections"]["edges"]
   all_posts_node = edges[0]["node"]
   audio_node = edges[1]["node"]
   collections = parse_saved_collections(answer).collections
   all_posts, audio = collections

   assert [collection.kind for collection in collections] == [
      SavedCollectionKind.ALL_POSTS,
      SavedCollectionKind.AUDIO,
   ]
   assert (all_posts.id, all_posts.name) == ("ALL_MEDIA_AUTO_COLLECTION", "All posts")
   assert (audio.id, audio.name) == ("AUDIO_AUTO_COLLECTION", "Audio")
   assert all_posts.media_count == all_posts_node["collection_media_count"] == 232
   assert audio.media_count is None
   assert [cover.media_id for cover in all_posts.covers] == [
      cover["id"] for cover in all_posts_node["cover_media_list"]
   ]
   assert [list(cover.image_urls) for cover in all_posts.covers] == [
      [candidate["url"] for candidate in cover["image_versions2"]["candidates"]]
      for cover in all_posts_node["cover_media_list"]
   ]
   assert [cover.media_id for cover in audio.covers] == [None] * 4
   assert [cover.image_urls for cover in audio.covers] == [
      (cover["thumbnail_uri"],) for cover in audio_node["cover_audio_list"]
   ]


def test_a_collection_of_an_unread_type_is_other_and_the_more_flag_is_has_next_page() -> None:
   """Catches a named collection, whose type has not been read, refused or read as an
   automatic one, and ``has_more`` read from anything but the page's ``has_next_page``."""

   answer = recorded("saved_collections.json")
   connection = answer["data"]["viewer"]["collections_unified_with_auto_collections"]
   named = copy.deepcopy(connection["edges"][0])
   named["node"]["__typename"] = "XDTSavedCollectionNotRead"
   named["node"]["collection_id"] = "17900000000000001"
   named["node"]["collection_name"] = "a named collection"
   connection["edges"].append(named)
   connection["page_info"]["has_next_page"] = True

   saved = parse_saved_collections(answer)

   assert saved.collections[2].kind is SavedCollectionKind.OTHER
   assert saved.collections[2].id == "17900000000000001"
   assert saved.has_more is True
   assert parse_saved_collections(recorded("saved_collections.json")).has_more is False


def test_the_saved_tab_read_sends_the_browsers_variables() -> None:
   """The parity gate for the saved tab. Catches another query, the three collection types in
   another order or cut, another page size, an ``after`` on the first page, and another path or
   referer."""

   request = build_saved_collections_request(a_bootstrapped_session())
   form = dict(sent_form(request))

   assert request.url == API_GRAPHQL_URL
   assert form["doc_id"] == "27584326974521636"
   assert form["fb_api_req_friendly_name"] == "PolarisProfileSavedTabContentQuery"
   assert sent_variables(request) == {
      "collection_types": ["ALL_MEDIA_AUTO_COLLECTION", "MEDIA", "AUDIO_AUTO_COLLECTION"],
      "first": 12,
   }
   assert request.headers["referer"] == SITE_ROOT


def test_the_close_friends_are_the_list_whose_rows_start_selected() -> None:
   """Catches the accounts offered to add returned instead, the two lists joined, a row dropped
   or reordered, and the id, username, name, picture or badge read from a neighbour."""

   answer = recorded("close_friends.json")
   data = bloks_data(answer)
   expected = rows_written_in(data[CLOSE_FRIENDS_LIST]["initial_lispy"])
   offered = rows_written_in(data[OFFERED_LIST]["initial_lispy"])

   close_friends = parse_close_friends(answer)

   assert data[CLOSE_FRIENDS_SELECTED]["initial_lispy"] == "(bk.action.bool.Const, true)"
   assert data[OFFERED_SELECTED]["initial_lispy"] == "(bk.action.bool.Const, false)"
   assert (len(expected), len(offered)) == (7, 3)
   assert [
      (
         account.id,
         account.username,
         account.full_name,
         account.profile_pic_url,
         account.is_verified,
      )
      for account in close_friends
   ] == expected
   assert all(isinstance(account, ProfileSummary) for account in close_friends)
   assert all(account.is_private is None for account in close_friends)


def test_the_lists_are_found_by_structure_so_the_selected_state_decides_and_ids_do_not() -> None:
   """Catches the list chosen by its position or by a component id the upstream renumbers on
   every answer: with every id renumbered the same seven return, and with the two starting
   states swapped the offered accounts return."""

   answer = recorded("close_friends.json")
   renumbered = json.loads(json.dumps(answer).replace("1106557", "3302118"))
   swapped = copy.deepcopy(answer)
   data = bloks_data(swapped)
   data[CLOSE_FRIENDS_SELECTED]["initial_lispy"] = "(bk.action.bool.Const, false)"
   data[OFFERED_SELECTED]["initial_lispy"] = "(bk.action.bool.Const, true)"
   offered = rows_written_in(bloks_data(answer)[OFFERED_LIST]["initial_lispy"])

   assert "110655765_0" not in json.dumps(renumbered)
   assert parse_close_friends(renumbered) == parse_close_friends(answer)
   assert [account.id for account in parse_close_friends(swapped)] == [row[0] for row in offered]


@pytest.mark.parametrize(
   "change",
   [
      "both lists selected",
      "neither list selected",
      "a selected state that is not a constant",
      "a row without its username",
      "an id that is not a number",
      "a list that is not an array",
      "a script that does not close",
   ],
)
def test_a_close_friends_tree_laid_out_otherwise_raises_rather_than_guessing(change: str) -> None:
   """Catches a tree the engine has not read being answered anyway: the wrong list, a partial
   list, or rows missing what every row read carried."""

   answer = recorded("close_friends.json")
   data = bloks_data(answer)
   close_friends = data[CLOSE_FRIENDS_LIST]

   if change == "both lists selected":
      data[OFFERED_SELECTED]["initial_lispy"] = "(bk.action.bool.Const, true)"
   elif change == "neither list selected":
      data[CLOSE_FRIENDS_SELECTED]["initial_lispy"] = "(bk.action.bool.Const, false)"
   elif change == "a selected state that is not a constant":
      data[CLOSE_FRIENDS_SELECTED]["initial_lispy"] = '(bk.action.bloks.GetVariable2, "x")'
   elif change == "a row without its username":
      close_friends["initial_lispy"] = close_friends["initial_lispy"].replace('"username", ', "", 1)
   elif change == "an id that is not a number":
      close_friends["initial_lispy"] = re.sub(
         r"i64\.Const, \d+", "i64.Const, abc", close_friends["initial_lispy"], count=1
      )
   elif change == "a list that is not an array":
      close_friends["initial_lispy"] = "(bk.action.bool.Const, true)"
   else:
      close_friends["initial_lispy"] = close_friends["initial_lispy"][:-1]

   with pytest.raises(SchemaChanged):
      parse_close_friends(answer)


def test_the_bloks_reader_keeps_strings_whole_and_refuses_what_is_not_its_grammar() -> None:
   """Catches a parenthesis or comma inside a string read as structure, an escape left
   undecoded, a bare word read as a string, and a malformed script read as far as it goes."""

   script = r'(bk.action.array.Make, "a (b, c)", "x\/y é", (bk.action.i64.Const, 12), null)'

   value = read_bloks_script(script, "<script>")

   assert value == BloksCall(
      name="bk.action.array.Make",
      arguments=(
         "a (b, c)",
         "x/y é",
         BloksCall(name="bk.action.i64.Const", arguments=(BloksAtom("12"),)),
         BloksAtom("null"),
      ),
   )

   for malformed in ("(bk.action.array.Make, 1", "(a))", '("a")', r'(a, "\q")', "(a) (b)"):
      with pytest.raises(SchemaChanged):
         read_bloks_script(malformed, "<script>")


def test_the_close_friends_fetch_is_the_settings_pages_app_fetch() -> None:
   """The parity gate for the Bloks fetch. Catches another path, app, type or version, a form
   field added, dropped or moved, ``params`` other than an empty object, another route, and an
   ``x-`` header the page's fetch did not carry."""

   session = a_bootstrapped_session()
   request = build_close_friends_request(session)
   url = urlsplit(request.url)
   form = sent_form(request)

   assert request.method == "POST"
   assert f"{url.scheme}://{url.netloc}{url.path}" == BLOKS_FETCH_URL
   assert parse_qsl(url.query) == [
      ("appid", CLOSE_FRIENDS_APP),
      ("type", "app"),
      ("__bkv", BLOKS_VERSION_ID),
   ]
   assert [name for name, _ in form] == CLOSE_FRIENDS_FORM
   assert dict(form)["params"] == "{}"
   assert dict(form)["__crn"] == "comet.igweb.PolarisSettingsCloseFriendsRoute"
   assert dict(form)["fb_dtsg"] == session.fb_dtsg
   assert set(request.headers) == CLOSE_FRIENDS_HEADERS
   assert request.headers["referer"] == CLOSE_FRIENDS_PAGE


def test_the_close_friends_fetch_is_refused_without_a_token_or_a_bloks_version() -> None:
   """Catches the fetch sent with an empty page token or an empty ``__bkv``."""

   without_token = Session(sessionid="s", ds_user_id="1", csrftoken="c")
   without_version = a_bootstrapped_session()
   without_version.bloks_version_id = None

   with pytest.raises(AuthenticationFailed):
      build_close_friends_request(without_token)

   with pytest.raises(SchemaChanged):
      build_close_friends_request(without_version)


@pytest.mark.asyncio
async def test_the_close_friends_read_is_one_fetch_and_never_the_count_updater() -> None:
   """Catches the page's second fetch or its ``close_friend_count_updater`` action sent, and
   the prefixed answer returned unmapped."""

   transport = ScriptedTransport([jsonp_response(recorded("close_friends.json"))])

   close_friends = await read_close_friends(make_paced(transport), a_bootstrapped_session())

   assert len(transport.sent) == 1
   assert CLOSE_FRIENDS_APP in transport.sent[0].url
   assert not any("count_updater" in request.url for request in transport.sent)
   assert len(close_friends) == 7


def paced(transport: ScriptedTransport, client: AsyncClient) -> PacedSender:
   clock = FakeClock()
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)

   return PacedSender(transport, pacer, client._sender.pacing, client._sender.writes)


@pytest.mark.asyncio
async def test_the_async_namespace_sends_each_read_once_and_nothing_else() -> None:
   """Catches ``client.account`` reaching another read, or a method sending more than its one
   request."""

   transport = ScriptedTransport(
      [
         json_response(recorded("saved_posts.json")),
         json_response(recorded("saved_collections.json")),
         jsonp_response(recorded("close_friends.json")),
      ]
   )
   client = AsyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR)
   await client._sender.aclose()
   client._sender = paced(transport, client)

   try:
      saved = await client.account.saved()
      collections = await client.account.collections()
      close_friends = await client.account.close_friends()
   finally:
      await client.aclose()

   assert isinstance(saved, SavedPosts)
   assert isinstance(collections, SavedCollections)
   assert len(close_friends) == 7
   assert [urlsplit(request.url).path for request in transport.sent] == [
      "/api/v1/feed/saved/posts/",
      "/api/graphql",
      "/async/wbloks/fetch/",
   ]


def test_the_blocking_namespace_sends_each_read_once_and_nothing_else() -> None:
   """The same three reads on the blocking surface, each on the loop thread."""

   transport = ScriptedTransport(
      [
         jsonp_response(recorded("close_friends.json")),
         json_response(recorded("saved_collections.json")),
         json_response(recorded("saved_posts.json")),
      ]
   )

   with SyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR) as client:
      client._loop.run(client._impl._sender.aclose(), operation="the scripted sender swap")
      client._impl._sender = paced(transport, client._impl)
      close_friends = client.account.close_friends()
      collections = client.account.collections()
      saved = client.account.saved()

   assert len(close_friends) == 7
   assert len(collections.collections) == 2
   assert len(saved.posts) == 3
   assert [urlsplit(request.url).path for request in transport.sent] == [
      "/async/wbloks/fetch/",
      "/api/graphql",
      "/api/v1/feed/saved/posts/",
   ]


class FakeAccount:
   def __init__(self) -> None:
      self.saved_posts = parse_saved_posts(recorded("saved_posts.json"))
      self.saved_collections = parse_saved_collections(recorded("saved_collections.json"))
      self.friends = parse_close_friends(recorded("close_friends.json"))

   def saved(self) -> SavedPosts:
      return self.saved_posts

   def collections(self) -> SavedCollections:
      return self.saved_collections

   def close_friends(self) -> tuple[ProfileSummary, ...]:
      return self.friends


class FakeAccountClient:
   def __init__(self) -> None:
      self.session = Session(sessionid="s", ds_user_id="1234567890", csrftoken="c")
      self.account = FakeAccount()
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


def test_dumpsta_saved_prints_every_post_and_whether_more_exist() -> None:
   """Catches a post left out of either form, a comment count invented in the JSON, and the
   more flag dropped."""

   client = FakeAccountClient()
   code, out = run_command(["--json", "saved"], client)
   payload = json.loads(out)
   text_code, text = run_command(["saved"], FakeAccountClient())
   lines = text.strip().splitlines()
   items = [item["media"] for item in recorded("saved_posts.json")["items"]]

   assert (code, text_code) == (0, 0)
   assert payload["command"] == "saved"
   assert payload["post_count"] == 3
   assert payload["more_available"] is True
   assert [post["code"] for post in payload["posts"]] == [item["code"] for item in items]
   assert "comment_count" not in payload["posts"][0]
   assert payload["posts"][2]["like_and_view_counts_disabled"] is None
   assert lines[0].startswith(f"{items[0]['code']}  {items[0]['user']['username']}  clips")
   assert lines[-1] == "posts: 3  more_available: True"
   assert client.closed


def test_dumpsta_collections_prints_each_collection_with_its_kind_and_count() -> None:
   """Catches a collection left out of either form, its kind or count dropped, and the covers
   left out of the JSON."""

   code, out = run_command(["--json", "collections"], FakeAccountClient())
   payload = json.loads(out)
   text_code, text = run_command(["collections"], FakeAccountClient())
   lines = text.strip().splitlines()

   assert (code, text_code) == (0, 0)
   assert payload["command"] == "collections"
   assert payload["collection_count"] == 2
   assert payload["more_available"] is False
   assert [collection["kind"] for collection in payload["collections"]] == ["all_posts", "audio"]
   assert [collection["media_count"] for collection in payload["collections"]] == [232, None]
   assert len(payload["collections"][0]["covers"]) == 4
   assert lines == [
      "ALL_MEDIA_AUTO_COLLECTION  All posts  all_posts  posts 232",
      "AUDIO_AUTO_COLLECTION  Audio  audio  posts None",
      "collections: 2  more_available: False",
   ]


def test_dumpsta_close_friends_prints_every_account_in_order() -> None:
   """Catches an account left out or reordered in either form, and the count wrong."""

   code, out = run_command(["--json", "close-friends"], FakeAccountClient())
   payload = json.loads(out)
   text_code, text = run_command(["close-friends"], FakeAccountClient())
   lines = text.strip().splitlines()
   expected = rows_written_in(
      bloks_data(recorded("close_friends.json"))[CLOSE_FRIENDS_LIST]["initial_lispy"]
   )

   assert (code, text_code) == (0, 0)
   assert payload["command"] == "close-friends"
   assert payload["account_count"] == 7
   assert [account["id"] for account in payload["accounts"]] == [row[0] for row in expected]
   assert lines[0].startswith(f"{expected[0][0]}  {expected[0][1]}")
   assert len(lines) == 8
   assert lines[-1] == "close friends: 7"
