"""Gates on E2 batch 5, stories, read only: the tray, one account's live stories and one highlight.

Five defect classes live here.

A read can mark a story seen. The engine sends no seen mutation until the arranged run verifies
one (W68), so no stories method may send anything but its read query, and the registry may hold
no seen mutation at all.

A mapper can read a field from the wrong key or invent one the answer does not carry. The tray
carries no items and a reel read no high resolution picture, a story video carries no dimensions,
and a tray's zero ``seen`` means never seen rather than 1970.

An empty answer can be misread. An account with no live story answers no reel, which is ``None``,
and a highlight that answers no reel is ``NotFound``; more than one reel for one id is the
upstream changing.

A request can go to the wrong path, carry other variables, or accept an identifier it should
refuse before sending.

And a command can take a username where an id is meant, or drop items in either output form.

The payloads are the recorded answers of 2026-09-27, pseudonymised by
``scripts/build_stories_fixtures.py``. Nothing in this file touches the network.
"""

from __future__ import annotations

import copy
import io
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import pytest

from dumpstagram._cli.main import main
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.stories import read_highlight, read_stories_tray, read_story_reel
from dumpstagram._private.web.documents.catalog import (
   COMPANION_QUERIES,
   READ_QUERIES,
   WRITE_QUERIES,
)
from dumpstagram._private.web.parse.stories import (
   parse_highlight_reel,
   parse_stories_tray,
   parse_story_reel,
)
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY
from dumpstagram.errors import NotFound, SchemaChanged
from dumpstagram.models import StoryReel, TrayReel
from dumpstagram.session import Session
from tests.test_direct import (
   FakeClock,
   ScriptedTransport,
   a_bootstrapped_session,
   json_response,
   make_paced,
   sent_variables,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "stories"

GRAPHQL_QUERY = "https://www.instagram.com/graphql/query"
API_GRAPHQL = "https://www.instagram.com/api/graphql"
SITE_ROOT = "https://www.instagram.com/"
TRAY_ROOT = "xdt_api__v1__feed__reels_tray"
REELS_ROOT = "xdt_api__v1__feed__reels_media"
TRAY_DOC_ID = "27703822975903310"
REEL_DOC_ID = "29184890191114309"
PROVIDER = "__relay_internal__pv__PolarisCommunityNoteStoriesLabelEnabledrelayprovider"
USER_ID = "81234567"
SEEN_MUTATIONS = (
   "PolarisStoriesV3SeenMutation",
   "PolarisAPIReelSeenMutation",
   "PolarisAPIForceStorySeenMutation",
)

SCRIPTED_BEHAVIOR = replace(PARITY, cookie_sync=False)


def recorded(name: str) -> Any:
   return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def tray_rows() -> list[dict[str, Any]]:
   rows: list[dict[str, Any]] = recorded("stories_tray.json")["data"][TRAY_ROOT]["tray"]

   return rows


def highlight_node() -> dict[str, Any]:
   node: dict[str, Any] = recorded("highlight.json")["data"][REELS_ROOT]["reels_media"][0]

   return node


def highlight_id() -> str:
   return str(highlight_node()["id"])


def at(seconds: int) -> datetime:
   return datetime.fromtimestamp(seconds, tz=UTC)


def sent_field(request: Any, name: str) -> str:
   return parse_qs(request.content.decode("utf-8"))[name][0]


def friendly_names(transport: ScriptedTransport) -> list[str]:
   return [sent_field(request, "fb_api_req_friendly_name") for request in transport.sent]


def test_the_tray_maps_every_row_in_order_with_its_owner_and_its_times() -> None:
   """Catches rows dropped or reordered, the owner read from the row's own id, a time read from
   another key, and a zero ``seen`` read as a time in 1970 rather than as never seen."""

   rows = tray_rows()
   tray = parse_stories_tray(recorded("stories_tray.json"))

   assert len(tray) == 33
   assert all(isinstance(reel, TrayReel) for reel in tray)
   assert [reel.id for reel in tray] == [row["id"] for row in rows]
   assert [reel.owner.id for reel in tray] == [row["user"]["pk"] for row in rows]
   assert [reel.owner.username for reel in tray] == [row["user"]["username"] for row in rows]
   assert [reel.owner.hd_profile_pic_url for reel in tray] == [
      row["user"]["hd_profile_pic_url_info"]["url"] for row in rows
   ]
   assert {(reel.owner.is_verified, reel.owner.is_private) for reel in tray} == {(None, None)}
   assert [reel.ranked_position for reel in tray] == [row["ranked_position"] for row in rows]
   assert [reel.latest_item_at for reel in tray] == [at(row["latest_reel_media"]) for row in rows]
   assert [reel.expiring_at for reel in tray] == [at(row["expiring_at"]) for row in rows]
   assert [reel.seen_at for reel in tray] == [
      at(row["seen"]) if row["seen"] else None for row in rows
   ]
   assert sum(1 for reel in tray if reel.seen_at is None) == 23
   assert [reel.has_close_friends_items for reel in tray] == [
      row["has_besties_media"] for row in rows
   ]


def test_a_highlight_maps_every_item_from_its_own_keys() -> None:
   """Catches items dropped or reordered, an item's owner read from the reel, the two times
   swapped, renditions, stickers or the audience lost, and the highlight's title or cover
   dropped."""

   node = highlight_node()
   items = node["items"]
   reel = parse_highlight_reel(recorded("highlight.json"))

   assert isinstance(reel, StoryReel)
   assert reel.id == node["id"]
   assert reel.id.startswith("highlight:")
   assert reel.reel_type == "highlight_reel"
   assert reel.title == node["title"]
   assert reel.cover_url == node["cover_media"]["cropped_image_version"]["url"]
   assert reel.owner.id == node["user"]["pk"]
   assert (reel.owner.is_verified, reel.owner.is_private) == (
      node["user"]["is_verified"],
      node["user"]["is_private"],
   )
   assert reel.owner.hd_profile_pic_url is None
   assert reel.latest_item_at == at(node["latest_reel_media"])
   assert len(reel.items) == 18
   assert [item.pk for item in reel.items] == [item["pk"] for item in items]
   assert [item.id for item in reel.items] == [item["id"] for item in items]
   assert [item.code for item in reel.items] == [item["code"] for item in items]
   assert [item.owner_id for item in reel.items] == [item["user"]["pk"] for item in items]
   assert [item.taken_at for item in reel.items] == [at(item["taken_at"]) for item in items]
   assert [item.expiring_at for item in reel.items] == [at(item["expiring_at"]) for item in items]
   assert [item.media_type for item in reel.items] == [item["media_type"] for item in items]
   assert [item.audience for item in reel.items] == [item["audience"] for item in items]
   assert [item.audience for item in reel.items].count("besties") == 2
   assert [len(item.images) for item in reel.items] == [
      len(item["image_versions2"]["candidates"]) for item in items
   ]
   assert [[video.version_type for video in item.videos] for item in reel.items] == [
      [version["type"] for version in item["video_versions"] or []] for item in items
   ]
   assert [item.video_duration for item in reel.items] == [item["video_duration"] for item in items]
   assert sum(len(item.mentions) for item in reel.items) == 4
   assert [[mention.username for mention in item.mentions] for item in reel.items] == [
      [
         sticker["bloks_sticker"]["sticker_data"]["ig_mention"]["username"]
         for sticker in item["story_bloks_stickers"] or []
      ]
      for item in items
   ]
   assert sum(len(item.music) for item in reel.items) == 11
   assert [[track.title for track in item.music] for item in reel.items] == [
      [sticker["music_asset_info"]["title"] for sticker in item["story_music_stickers"] or []]
      for item in items
   ]


def test_a_photo_item_carries_no_video_and_a_null_audio_flag_reads_as_unknown() -> None:
   """Catches a photo given renditions or a duration, and a null ``has_audio`` read as False."""

   reel = parse_highlight_reel(recorded("highlight.json"))
   photos = [item for item in reel.items if item.media_type == 1]
   videos = [item for item in reel.items if item.media_type == 2]

   assert len(photos) == 1
   assert photos[0].videos == ()
   assert photos[0].video_duration is None
   assert photos[0].has_audio is None
   assert all(len(item.videos) == 3 for item in videos)
   assert {item.has_audio for item in videos} == {True}


def test_no_live_story_is_none_and_a_highlight_with_no_reel_is_not_found() -> None:
   """Catches an empty answer read as a reel, or a missing highlight returned as ``None`` where
   the method promises a reel."""

   assert parse_story_reel(recorded("own_reel_empty.json")) is None

   with pytest.raises(NotFound):
      parse_highlight_reel(recorded("own_reel_empty.json"))


def test_more_than_one_reel_for_one_id_is_a_schema_change() -> None:
   """Catches a second reel silently dropped when one id was asked."""

   payload = copy.deepcopy(recorded("highlight.json"))
   reels = payload["data"][REELS_ROOT]["reels_media"]
   reels.append(copy.deepcopy(reels[0]))

   with pytest.raises(SchemaChanged, match="2 reels"):
      parse_story_reel(payload)

   with pytest.raises(SchemaChanged, match="2 reels"):
      parse_highlight_reel(payload)


def test_a_story_video_without_its_type_is_a_schema_change() -> None:
   """Catches a rendition read without the one field besides its address that it carries."""

   payload = copy.deepcopy(recorded("highlight.json"))
   del payload["data"][REELS_ROOT]["reels_media"][0]["items"][0]["video_versions"][0]["type"]

   with pytest.raises(SchemaChanged, match="video_versions"):
      parse_highlight_reel(payload)


@pytest.mark.asyncio
async def test_the_three_reads_send_the_variables_replayed_live() -> None:
   """The parity gate for the stories reads. Catches another path, another query, the highlight
   flag left off a highlight or put on a reel, a missing root field header, or another
   referer."""

   transport = ScriptedTransport(
      [
         json_response(recorded("stories_tray.json")),
         json_response(recorded("own_reel_empty.json")),
         json_response(recorded("highlight.json")),
      ]
   )
   sender = make_paced(transport)
   session = a_bootstrapped_session()

   tray = await read_stories_tray(sender, session)
   reel = await read_story_reel(sender, session, USER_ID)
   highlight = await read_highlight(sender, session, highlight_id())

   assert len(tray) == 33
   assert reel is None
   assert len(highlight.items) == 18
   assert [request.url for request in transport.sent] == [
      API_GRAPHQL,
      GRAPHQL_QUERY,
      GRAPHQL_QUERY,
   ]
   assert [sent_field(request, "doc_id") for request in transport.sent] == [
      TRAY_DOC_ID,
      REEL_DOC_ID,
      REEL_DOC_ID,
   ]
   assert sent_variables(transport.sent[0]) == {
      "data": {"is_following_feed": False},
      "suggestedUsersData": {
         "max_id": "",
         "max_number_to_display": 0,
         "module": "stories_tray",
         "paginate": False,
      },
   }
   assert sent_variables(transport.sent[1]) == {"reel_ids_arr": [USER_ID], PROVIDER: True}
   assert sent_variables(transport.sent[2]) == {
      "reel_ids_arr": [highlight_id()],
      "is_highlight": True,
      PROVIDER: True,
   }
   assert "x-root-field-name" not in transport.sent[0].headers
   assert transport.sent[1].headers["x-root-field-name"] == REELS_ROOT
   assert transport.sent[2].headers["x-root-field-name"] == REELS_ROOT
   assert {request.headers["referer"] for request in transport.sent} == {SITE_ROOT}


@pytest.mark.asyncio
async def test_a_username_and_a_bare_highlight_number_are_refused_before_anything_is_sent() -> None:
   """Catches an identifier reaching the request unchecked."""

   transport = ScriptedTransport([])
   sender = make_paced(transport)
   session = a_bootstrapped_session()
   bare_number = highlight_id().removeprefix("highlight:")

   with pytest.raises(ValueError, match="numeric account id"):
      await read_story_reel(sender, session, "someone")

   with pytest.raises(ValueError, match="highlight id"):
      await read_highlight(sender, session, bare_number)

   with pytest.raises(ValueError, match="highlight id"):
      await read_highlight(sender, session, f"{highlight_id()}x")

   assert transport.sent == []


def paced(transport: ScriptedTransport, client: AsyncClient) -> PacedSender:
   clock = FakeClock()
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)

   return PacedSender(transport, pacer, client._sender.pacing, client._sender.writes)


@pytest.mark.asyncio
async def test_no_stories_method_sends_a_seen_mutation_and_the_registry_holds_none() -> None:
   """The W68 gate. Catches any stories method sending a request other than its read query,
   a mutation among them, and a seen mutation registered anywhere a later change could send it
   from."""

   transport = ScriptedTransport(
      [
         json_response(recorded("stories_tray.json")),
         json_response(recorded("highlight.json")),
         json_response(recorded("highlight.json")),
      ]
   )
   client = AsyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR)
   await client._sender.aclose()
   client._sender = paced(transport, client)

   try:
      await client.stories.tray()
      await client.stories.reel(USER_ID)
      await client.stories.highlight(highlight_id())
   finally:
      await client.aclose()

   read_names = {query.friendly_name for query in READ_QUERIES}
   registered = {
      query.friendly_name for query in (*READ_QUERIES, *COMPANION_QUERIES, *WRITE_QUERIES)
   }
   sent = friendly_names(transport)

   assert sent == [
      "PolarisStoriesV3TrayContainerQuery",
      "PolarisStoriesV3ReelPageStandaloneQuery",
      "PolarisStoriesV3ReelPageStandaloneQuery",
   ]
   assert set(sent) <= read_names
   assert not any(name.endswith("Mutation") for name in sent)
   assert not any(name in registered for name in SEEN_MUTATIONS)
   assert not any("Seen" in name for name in registered)


class FakeStories:
   def __init__(self, reel: StoryReel | None) -> None:
      self.reel_answer = reel
      self.asked: list[tuple[str, str]] = []

   def tray(self) -> tuple[TrayReel, ...]:
      self.asked.append(("tray", ""))

      return parse_stories_tray(recorded("stories_tray.json"))

   def reel(self, user_id: str) -> StoryReel | None:
      self.asked.append(("reel", user_id))

      return self.reel_answer

   def highlight(self, highlight_id: str) -> StoryReel:
      self.asked.append(("highlight", highlight_id))

      return parse_highlight_reel(recorded("highlight.json"))


class FakeStoriesClient:
   def __init__(self, reel: StoryReel | None = None) -> None:
      self.session = Session(sessionid="s", ds_user_id="1234567890", csrftoken="c")
      self.stories = FakeStories(reel)
      self.closed = False

   def close(self) -> None:
      self.closed = True


def run_command(argv: list[str], client: FakeStoriesClient) -> tuple[int, str, str]:
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


def test_dumpsta_stories_tray_story_and_highlight_print_every_row_and_item() -> None:
   """Catches a row or an item cut short in either output form, a reel with no live story
   printed as anything but null, and the id passed on as something else."""

   tray_client = FakeStoriesClient()
   _, tray_out, _ = run_command(["--json", "stories-tray"], tray_client)
   _, tray_text, _ = run_command(["stories-tray"], FakeStoriesClient())
   empty_client = FakeStoriesClient(reel=None)
   _, empty_out, _ = run_command(["--json", "story", USER_ID], empty_client)
   highlight_client = FakeStoriesClient()
   _, highlight_out, _ = run_command(["--json", "highlight", highlight_id()], highlight_client)
   _, highlight_text, _ = run_command(["highlight", highlight_id()], FakeStoriesClient())

   tray = json.loads(tray_out)
   empty = json.loads(empty_out)
   highlight = json.loads(highlight_out)

   assert tray["reel_count"] == 33
   assert len(tray["reels"]) == 33
   assert tray_text.strip().splitlines()[-1] == "reels: 33"
   assert empty_client.stories.asked == [("reel", USER_ID)]
   assert empty["reel"] is None
   assert empty["item_count"] == 0
   assert highlight_client.stories.asked == [("highlight", highlight_id())]
   assert highlight["item_count"] == 18
   assert len(highlight["reel"]["items"]) == 18
   assert highlight_text.strip().splitlines()[-1] == "items: 18"
   assert tray_client.closed
   assert highlight_client.closed


def test_dumpsta_story_refuses_a_username_and_highlight_a_bare_number(
   capsys: pytest.CaptureFixture[str],
) -> None:
   """Catches a username passed on as an account id, and a highlight id without its prefix."""

   client = FakeStoriesClient()
   story_refused, _, _ = run_command(["story", "someone"], client)
   highlight_refused, _, _ = run_command(
      ["highlight", highlight_id().removeprefix("highlight:")], client
   )

   assert story_refused == 2
   assert highlight_refused == 2
   assert client.stories.asked == []
   assert "highlight:<number>" in capsys.readouterr().err
