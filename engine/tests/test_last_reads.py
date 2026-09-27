"""Gates on E2 batch 11e: the explore grid's later pages, an audio's page, the mutual followers,
and the audio id a post names.

Four defect classes live here.

A later page can lose posts or page on the wrong value. The explore grid's later pages lay a
section out as one list of mixed tiles, and its answer carries three values named like a cursor:
the root ``max_id``, a page counter in ``next_max_id`` and a ``max_id`` on every large tile's
cluster. Only the first reached the next page on the replays.

A walk can end on something other than the upstream's flag. An audio's one-reel page said more
existed and its next page was empty; a walk that stops on a short or empty page, or never asks for
the empty one, is ending on a heuristic.

A request can drift from the page's own. The audio page is a comet form with its own header set,
and its first page sends ``max_id`` empty; the mutual followers list sends ``page_size`` alone and
then the statuses of the accounts it returned.

A post can hide its audio page. A reels feed reel whose original sound lacks the mute flag has no
``audio``, and its audio page id must still be read.

The payloads are the recorded answers of 2026-09-27, pseudonymised by
``scripts/build_last_reads_fixtures.py``, and the first explore page and the reels pages of the
earlier batches. Nothing in this file touches the network.
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
from dumpstagram._core.discovery import read_audio_page, read_explore_grid
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.profiles import read_mutual_followers
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import Response
from dumpstagram._private.web.parse.discovery import (
   parse_audio_page,
   parse_explore_grid,
   parse_reels_feed_page,
)
from dumpstagram._private.web.parse.profiles import (
   attach_friendship_statuses,
   parse_friendship_statuses,
   parse_mutual_followers_page,
)
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY
from dumpstagram.client import SyncClient
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import AudioKind, AudioPage, ExploreGrid, MutualFollowers, Post
from dumpstagram.session import Session
from tests.test_direct import (
   FakeClock,
   ScriptedTransport,
   a_bootstrapped_session,
   json_response,
   make_paced,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "last_reads"
DISCOVERY_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "discovery"
REELS_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "discovery_search"

EXPLORE_URL = "https://www.instagram.com/api/v1/discover/web/explore_grid/"
EXPLORE_PAGE = "https://www.instagram.com/explore/"
AUDIO_URL = "https://www.instagram.com/api/v1/clips/music/"
STATUSES_URL = "https://www.instagram.com/api/v1/friendships/show_many/"
SITE_ROOT = "https://www.instagram.com/"
ORIGIN = "https://www.instagram.com"
USER_ID = "71234567"
USERNAME = "someone"
REELS_ROOT = "xdt_api__v1__clips__home__connection_v2"
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
AUDIO_HEADERS = {
   "accept",
   "accept-language",
   "content-type",
   "origin",
   "referer",
   "sec-fetch-dest",
   "sec-fetch-mode",
   "sec-fetch-site",
   "user-agent",
   "x-asbd-id",
   "x-fb-lsd",
   "x-ig-d",
   "x-ig-max-touch-points",
}
AUDIO_FORM_KEYS = [
   "audio_cluster_id",
   "max_id",
   "original_sound_audio_asset_id",
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
]

SCRIPTED_BEHAVIOR = replace(PARITY, cookie_sync=False)
WITHOUT_STATUSES = replace(SCRIPTED_BEHAVIOR, follow_list_statuses=False)


def recorded(name: str) -> Any:
   return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def first_explore_page() -> Any:
   return json.loads((DISCOVERY_FIXTURES / "explore_grid.json").read_text(encoding="utf-8"))


def reels_page(name: str) -> Any:
   return json.loads((REELS_FIXTURES / name).read_text(encoding="utf-8"))


def jsonp_response(parsed: dict[str, Any]) -> Response:
   """An answer as the audio page receives it, behind the ``for (;;);`` guard."""

   return Response(
      status_code=200,
      headers={"content-type": "text/javascript; charset=utf-8"},
      content=b"for (;;);" + json.dumps(parsed).encode("utf-8"),
      final_url=AUDIO_URL,
   )


def audio_payload(name: str) -> dict[str, Any]:
   payload: dict[str, Any] = recorded(name)["payload"]

   return payload


def audio_id_of(name: str) -> str:
   metadata = audio_payload(name)["metadata"]
   music = metadata["music_info"]

   if music is not None:
      return str(music["music_asset_info"]["audio_cluster_id"])

   return str(metadata["original_sound_info"]["audio_asset_id"])


def sent_form(request: Any) -> list[tuple[str, str]]:
   return parse_qsl(request.content.decode("utf-8"), keep_blank_values=True)


def paced(transport: ScriptedTransport, client: AsyncClient) -> PacedSender:
   clock = FakeClock()
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)

   return PacedSender(transport, pacer, client._sender.pacing, client._sender.writes)


async def scripted_client(transport: ScriptedTransport, behavior: Any) -> AsyncClient:
   client = AsyncClient(a_bootstrapped_session(), behavior=behavior)
   await client._sender.aclose()
   client._sender = paced(transport, client)

   return client


def dynamic_grid_media(answer: Any) -> list[tuple[list[str], list[str]]]:
   """Each section's large tile ids and fill tile ids, read straight off the answer."""

   sections = []

   for section in answer["sectional_items"]:
      entries = section["layout_content"]["medias"]
      featured = [
         item["media"]["id"]
         for entry in entries
         if "clips" in entry
         for item in entry["clips"]["items"]
      ]
      posts = [entry["media"]["id"] for entry in entries if "media" in entry]
      sections.append((featured, posts))

   return sections


def test_a_later_explore_page_maps_every_tile_of_its_single_list_sections() -> None:
   """Catches a later page refused for its ``medias`` block, a large tile read as a fill tile or
   dropped, a tile read twice, and the sections out of the upstream's order. Of the two recorded
   sections one puts its large tile last and the other first."""

   answer = recorded("explore_next_page.json")
   grid = parse_explore_grid(answer)
   expected = dynamic_grid_media(answer)

   assert len(grid.sections) == 2
   assert [
      ([post.id for post in section.featured], [post.id for post in section.posts])
      for section in grid.sections
   ] == expected
   assert [(len(featured), len(posts)) for featured, posts in expected] == [(1, 2), (1, 2)]
   assert all(isinstance(post, Post) for post in grid.posts)
   assert grid.more_available is True


@pytest.mark.parametrize(
   "unit",
   [
      {"other": {}},
      {"media": {}, "clips": {"items": []}},
      "not an entry",
   ],
)
def test_a_later_page_entry_of_another_shape_raises(unit: Any) -> None:
   """Catches an entry that is neither a fill tile nor a large tile skipped with whatever posts
   it held."""

   answer = recorded("explore_next_page.json")
   answer["sectional_items"][0]["layout_content"]["medias"].append(unit)

   with pytest.raises(SchemaChanged, match="neither a fill tile nor a large tile"):
      parse_explore_grid(answer)


def test_the_explore_cursor_is_the_root_max_id_and_not_the_counter_or_a_tiles_cluster() -> None:
   """The W115 gate on the mapper. Catches the cursor read from ``next_max_id``, the page counter,
   from a large tile's own ``max_id``, or from nowhere, on both a first and a later page."""

   first = first_explore_page()
   later = recorded("explore_next_page.json")
   cluster_cursors = {
      entry["clips"]["max_id"]
      for section in later["sectional_items"]
      for entry in section["layout_content"]["medias"]
      if "clips" in entry
   }

   assert parse_explore_grid(first).end_cursor == first["max_id"]
   assert parse_explore_grid(later).end_cursor == later["max_id"]
   assert later["max_id"] == later["session_paging_token"]
   assert later["max_id"] != later["next_max_id"]
   assert later["max_id"] not in cluster_cursors
   assert cluster_cursors


@pytest.mark.asyncio
async def test_a_later_explore_page_is_the_first_pages_get_with_max_id_in_the_browsers_order() -> (
   None
):
   """The parity gate for the next page. Catches the cursor sent under another name or not at
   all, sent on the first page, the six parameters out of the order the browser sent them, and
   another header set or referer."""

   transport = ScriptedTransport(
      [json_response(first_explore_page()), json_response(recorded("explore_next_page.json"))]
   )
   sender = make_paced(transport)
   session = a_bootstrapped_session()

   first = await read_explore_grid(sender, session)
   await read_explore_grid(sender, session, after=first.end_cursor)
   first_request, next_request = transport.sent

   assert "max_id" not in first_request.params
   assert (next_request.method, next_request.url, next_request.content) == (
      "GET",
      EXPLORE_URL,
      None,
   )
   assert list(next_request.params.items()) == [
      ("include_fixed_destinations", "true"),
      ("is_nonpersonalized_explore", "false"),
      ("is_prefetch", "false"),
      ("max_id", first_explore_page()["max_id"]),
      ("module", "explore_popular"),
      ("omit_cover_media", "false"),
   ]
   assert set(next_request.headers) == READ_HEADERS
   assert next_request.headers["referer"] == EXPLORE_PAGE


def last_explore_page() -> Any:
   answer = recorded("explore_next_page.json")
   answer["more_available"] = False

   return answer


@pytest.mark.asyncio
async def test_the_explore_walk_follows_the_root_max_id_and_ends_on_more_available() -> None:
   """Catches ``iter_explore`` repeating the first page, sending another cursor, stopping before
   the upstream says the grid ends, or asking past it."""

   transport = ScriptedTransport(
      [json_response(first_explore_page()), json_response(last_explore_page())]
   )
   client = await scripted_client(transport, SCRIPTED_BEHAVIOR)

   try:
      posts = [post async for post in client.feeds.iter_explore(limit=None)]
   finally:
      await client.aclose()

   assert len(posts) == 11
   assert len(transport.sent) == 2
   assert transport.sent[1].params["max_id"] == first_explore_page()["max_id"]


def test_the_blocking_explore_walk_answers_as_its_async_twin() -> None:
   """The same walk on the blocking surface, each page read on the loop thread."""

   transport = ScriptedTransport(
      [json_response(first_explore_page()), json_response(last_explore_page())]
   )

   with SyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR) as client:
      client._loop.run(client._impl._sender.aclose(), operation="the scripted sender swap")
      client._impl._sender = paced(transport, client._impl)
      posts = list(client.feeds.iter_explore(limit=7))

   assert len(posts) == 7
   assert transport.sent[1].params["max_id"] == first_explore_page()["max_id"]


@pytest.mark.asyncio
async def test_an_explore_page_that_says_more_with_no_cursor_stops_the_walk_loudly() -> None:
   """Catches a walk that treats a missing cursor as the end, which would be a heuristic end the
   upstream never signalled."""

   no_cursor = first_explore_page()
   del no_cursor["max_id"]
   transport = ScriptedTransport([json_response(no_cursor)])
   client = await scripted_client(transport, SCRIPTED_BEHAVIOR)

   try:
      with pytest.raises(SchemaChanged, match="no cursor"):
         _ = [post async for post in client.feeds.iter_explore(limit=None)]
   finally:
      await client.aclose()

   assert len(transport.sent) == 1


def test_a_songs_audio_page_maps_the_track_the_count_and_every_reel() -> None:
   """Catches the track read from another slot or key, the count from another number, a reel
   dropped or reordered, a reel that names another audio, the collaborators of the audio page's
   thinner rows read as accounts, and the cursor lost."""

   answer = recorded("audio_song_first_page.json")
   payload = answer["payload"]
   asset = payload["metadata"]["music_info"]["music_asset_info"]
   page = parse_audio_page(answer)

   assert isinstance(page, AudioPage)
   assert page.audio is not None
   assert page.audio.kind is AudioKind.MUSIC
   assert page.audio.audio_id == asset["audio_cluster_id"]
   assert (page.audio.title, page.audio.artist) == (asset["title"], asset["display_artist"])
   assert page.clips_count == 2869
   assert page.is_restricted is False
   assert [clip.id for clip in page.clips] == [item["media"]["id"] for item in payload["items"]]
   assert [clip.code for clip in page.clips] == [item["media"]["code"] for item in payload["items"]]
   assert {clip.audio_id for clip in page.clips} == {asset["audio_cluster_id"]}
   assert payload["items"][2]["media"]["coauthor_producers"]
   assert page.clips[2].collaborators is None
   assert all(clip.author.hd_profile_pic_url is None for clip in page.clips)
   assert all(clip.is_seen is False for clip in page.clips)
   assert page.more_available is True
   assert page.end_cursor == payload["paging_info"]["max_id"]


def test_a_later_songs_page_has_no_track_and_the_original_sounds_last_page_no_cursor() -> None:
   """Catches a later page's null track read as a guessed one, its count taken for a count, a
   last page given a cursor, and an empty last page read as anything but empty and final."""

   later_song = parse_audio_page(recorded("audio_song_second_page.json"))
   first_sound = parse_audio_page(recorded("audio_original_first_page.json"))
   last_sound = parse_audio_page(recorded("audio_original_second_page.json"))
   sound_payload = audio_payload("audio_original_first_page.json")

   assert later_song.audio is None
   assert later_song.clips_count == 0
   assert len(later_song.clips) == 2
   assert first_sound.audio is not None
   assert first_sound.audio.kind is AudioKind.ORIGINAL_SOUND
   assert (
      first_sound.audio.audio_id
      == sound_payload["metadata"]["original_sound_info"]["audio_asset_id"]
   )
   assert [clip.pk for clip in first_sound.clips] == [
      item["media"]["pk"] for item in sound_payload["items"]
   ]
   assert (first_sound.more_available, len(first_sound.clips)) == (True, 1)
   assert (last_sound.clips, last_sound.more_available, last_sound.end_cursor) == ((), False, None)
   assert last_sound.audio is not None


def test_an_audio_page_filling_both_track_slots_raises() -> None:
   """Catches a page naming a song and an original sound at once read as either one."""

   answer = recorded("audio_song_first_page.json")
   original = audio_payload("audio_original_first_page.json")["metadata"]["original_sound_info"]
   answer["payload"]["metadata"]["original_sound_info"] = original

   with pytest.raises(SchemaChanged, match="both music_info and original_sound_info"):
      parse_audio_page(answer)


@pytest.mark.asyncio
async def test_the_audio_page_is_the_pages_form_post_with_its_own_header_set() -> None:
   """The parity gate for the audio page. Catches another path or method, the form's fields out of
   the page's order, both ids not the audio's, ``max_id`` left out or filled on the first page,
   the next page sent on another cursor, a csrf or app id header the page did not send, and
   another referer or route."""

   audio_id = audio_id_of("audio_song_first_page.json")
   transport = ScriptedTransport(
      [
         jsonp_response(recorded("audio_song_first_page.json")),
         jsonp_response(recorded("audio_song_second_page.json")),
      ]
   )
   sender = make_paced(transport)
   session = a_bootstrapped_session()

   first = await read_audio_page(sender, session, audio_id)
   await read_audio_page(sender, session, audio_id, after=first.end_cursor)
   first_request, next_request = transport.sent
   first_form = dict(sent_form(first_request))

   assert (first_request.method, first_request.url) == ("POST", AUDIO_URL)
   assert [key for key, _ in sent_form(first_request)] == AUDIO_FORM_KEYS
   assert first_form["audio_cluster_id"] == audio_id
   assert first_form["original_sound_audio_asset_id"] == audio_id
   assert first_form["max_id"] == ""
   assert first_form["__crn"] == "comet.igweb.PolarisClipsAudioRoute"
   assert (first_form["__comet_req"], first_form["__d"], first_form["__a"]) == ("7", "www", "1")
   assert first_form["fb_dtsg"] == session.fb_dtsg
   assert first_form["lsd"] == session.lsd
   assert (
      dict(sent_form(next_request))["max_id"]
      == audio_payload("audio_song_first_page.json")["paging_info"]["max_id"]
   )
   assert set(first_request.headers) == AUDIO_HEADERS
   assert first_request.headers["x-fb-lsd"] == session.lsd
   assert first_request.headers["x-ig-d"] == "www"
   assert first_request.headers["referer"] == f"{ORIGIN}/reels/audio/{audio_id}/"


@pytest.mark.asyncio
@pytest.mark.parametrize("audio_id", ["", "a title", "12a", "1_2"])
async def test_an_audio_id_that_is_not_digits_is_refused_before_anything_is_sent(
   audio_id: str,
) -> None:
   """Catches a title or a compound id reaching the audio page's form."""

   transport = ScriptedTransport([])

   with pytest.raises(ValueError, match="numeric audio id"):
      await read_audio_page(make_paced(transport), a_bootstrapped_session(), audio_id)

   assert transport.sent == []


@pytest.mark.asyncio
async def test_the_audio_walk_spends_the_empty_read_and_ends_on_the_upstreams_flag() -> None:
   """The W116 gate. Catches a walk that stops on a short page while the upstream says more
   exist, one that stops on the empty page without reading it, one that asks past the flag that
   ends it, and the next page sent on another cursor."""

   audio_id = audio_id_of("audio_original_first_page.json")
   transport = ScriptedTransport(
      [
         jsonp_response(recorded("audio_original_first_page.json")),
         jsonp_response(recorded("audio_original_second_page.json")),
      ]
   )
   client = await scripted_client(transport, SCRIPTED_BEHAVIOR)

   try:
      clips = [clip async for clip in client.feeds.iter_audio(audio_id, limit=None)]
   finally:
      await client.aclose()

   assert len(clips) == 1
   assert len(transport.sent) == 2
   assert (
      dict(sent_form(transport.sent[1]))["max_id"]
      == audio_payload("audio_original_first_page.json")["paging_info"]["max_id"]
   )


def test_the_blocking_audio_reads_answer_as_their_async_twins() -> None:
   """The page read and the walk on the blocking surface, each on the loop thread."""

   audio_id = audio_id_of("audio_original_first_page.json")
   transport = ScriptedTransport(
      [
         jsonp_response(recorded("audio_original_first_page.json")),
         jsonp_response(recorded("audio_original_first_page.json")),
         jsonp_response(recorded("audio_original_second_page.json")),
      ]
   )

   with SyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR) as client:
      client._loop.run(client._impl._sender.aclose(), operation="the scripted sender swap")
      client._impl._sender = paced(transport, client._impl)
      page = client.feeds.audio(audio_id)
      clips = list(client.feeds.iter_audio(audio_id, limit=None))

   assert page.audio is not None
   assert len(clips) == 1
   assert len(transport.sent) == 3
   assert (
      dict(sent_form(transport.sent[2]))["max_id"]
      == audio_payload("audio_original_first_page.json")["paging_info"]["max_id"]
   )


def test_a_reels_feed_reel_names_its_audio_page_though_its_audio_is_none() -> None:
   """The W118 gate. Catches ``audio_id`` read off the model's ``audio``, which a reel whose
   original sound lacks the mute flag does not have, a song's id read from another key, and a post
   that names no track given an id."""

   first = reels_page("reels_first_page.json")
   later = reels_page("reels_next_page.json")
   first_reel = first["data"][REELS_ROOT]["edges"][0]["node"]["media"]
   song_reel = later["data"][REELS_ROOT]["edges"][-1]["node"]["media"]
   reel = parse_reels_feed_page(first).items[0]
   song = parse_reels_feed_page(later).items[-1]
   photo_grid = parse_explore_grid(first_explore_page())
   photos = [post for post in photo_grid.posts if post.media_type == 1]

   assert reel.audio is None
   assert reel.audio_id == first_reel["clips_metadata"]["original_sound_info"]["audio_asset_id"]
   assert song.audio is not None
   assert (
      song.audio_id
      == song_reel["clips_metadata"]["music_info"]["music_asset_info"]["audio_cluster_id"]
   )
   assert song.audio_id == song.audio.audio_id
   assert photos
   assert {photo.audio_id for photo in photos} == {None}


def test_a_reel_tagged_at_a_place_sent_without_coordinates_names_the_place_and_no_location() -> (
   None
):
   """The W120 gate. Catches a reels page refused for a place sent with only its name and pk,
   coordinates guessed for it, the place dropped instead of named, and a place with coordinates
   no longer read as a whole ``Location`` on the reads that send one."""

   answer = recorded("reels_thin_location_page.json")
   media = [edge["node"]["media"] for edge in answer["data"][REELS_ROOT]["edges"]]
   thin = [index for index, node in enumerate(media) if node.get("location")]
   page = parse_reels_feed_page(answer)
   tagged = page.items[thin[0]]
   raw_place = media[thin[0]]["location"]
   explore = parse_explore_grid(first_explore_page())
   song = parse_audio_page(recorded("audio_song_first_page.json"))
   located = [post for post in (*explore.posts, *song.clips) if post.location is not None]

   assert thin == [2]
   assert set(raw_place) == {"name", "pk"}
   assert tagged.location is None
   assert tagged.tagged_place is not None
   assert (tagged.tagged_place.id, tagged.tagged_place.name) == (
      str(raw_place["pk"]),
      raw_place["name"],
   )
   assert [post.tagged_place for index, post in enumerate(page.items) if index != 2] == [None] * 3
   assert located
   assert all(
      post.tagged_place is not None
      and (post.tagged_place.id, post.tagged_place.name) == (post.location.id, post.location.name)
      for post in located
      if post.location is not None
   )


def test_a_thin_place_outside_the_reels_feed_is_still_refused() -> None:
   """Catches the reels feed's allowance for a place without coordinates widened to reads that
   have always sent them, where a missing coordinate is a schema change."""

   explore = first_explore_page()
   song = recorded("audio_song_first_page.json")
   explore_located = next(
      item["media"]
      for section in explore["sectional_items"]
      for item in section["layout_content"]["fill_items"]
      if item["media"].get("location")
   )
   song_located = next(
      item["media"] for item in song["payload"]["items"] if item["media"].get("location")
   )
   del explore_located["location"]["lat"]
   del song_located["location"]["lng"]

   with pytest.raises(SchemaChanged, match="lat"):
      parse_explore_grid(explore)

   with pytest.raises(SchemaChanged, match="lng"):
      parse_audio_page(song)


def test_a_post_filling_both_audio_slots_raises_rather_than_naming_either() -> None:
   """Catches a post naming a song and an original sound read as one of them."""

   answer = reels_page("reels_next_page.json")
   media = answer["data"][REELS_ROOT]["edges"][-1]["node"]["media"]
   media["clips_metadata"]["original_sound_info"] = {"audio_asset_id": "1"}

   with pytest.raises(SchemaChanged, match="both music_info and original_sound_info"):
      parse_reels_feed_page(answer)


def test_mutual_followers_map_every_account_from_its_string_id_with_the_answers_own_end() -> None:
   """Catches an account read from its numeric ``pk``, an account dropped or reordered, a null
   ``next_max_id`` read as more, a filled one as none, and a cursor of an unknown type accepted."""

   answer = recorded("mutual_followers.json")
   page = parse_mutual_followers_page(answer)
   more = parse_mutual_followers_page({**answer, "next_max_id": 12})
   more_as_text = parse_mutual_followers_page({**answer, "next_max_id": "a-cursor"})

   assert [account.id for account in page.items] == [user["id"] for user in answer["users"]]
   assert [account.username for account in page.items] == [
      user["username"] for user in answer["users"]
   ]
   assert (page.has_next_page, page.end_cursor) == (False, None)
   assert (more.has_next_page, more.end_cursor) == (True, "12")
   assert (more_as_text.has_next_page, more_as_text.end_cursor) == (True, "a-cursor")

   with pytest.raises(SchemaChanged, match="next_max_id"):
      parse_mutual_followers_page({**answer, "next_max_id": {"page": 2}})


@pytest.mark.asyncio
async def test_mutual_followers_are_the_lists_get_then_its_accounts_statuses_in_one_action() -> (
   None
):
   """The W117 gate. Catches another path or parameter, a cursor sent where none was observed,
   the statuses asked for other ids or in another order, a second web session id, and the answer
   returned without the statuses its second request read."""

   transport = ScriptedTransport(
      [
         json_response(recorded("mutual_followers.json")),
         json_response(recorded("mutual_statuses.json")),
      ]
   )
   users = recorded("mutual_followers.json")["users"]
   statuses = recorded("mutual_statuses.json")["friendship_statuses"]

   mutual = await read_mutual_followers(make_paced(transport), a_bootstrapped_session(), USER_ID)
   page_request, statuses_request = transport.sent

   assert isinstance(mutual, MutualFollowers)
   assert page_request.method == "GET"
   assert page_request.url == f"{ORIGIN}/api/v1/friendships/{USER_ID}/mutual_followers/"
   assert dict(page_request.params) == {"page_size": "12"}
   assert set(page_request.headers) == READ_HEADERS
   assert page_request.headers["referer"] == SITE_ROOT
   assert statuses_request.url == STATUSES_URL
   assert dict(sent_form(statuses_request))["user_ids"] == ",".join(user["id"] for user in users)
   assert page_request.headers["x-web-session-id"] == statuses_request.headers["x-web-session-id"]
   assert [
      account.friendship_status.following if account.friendship_status is not None else None
      for account in mutual.accounts
   ] == [statuses[user["id"]]["following"] for user in users]
   assert mutual.has_more is False


@pytest.mark.asyncio
async def test_mutual_followers_under_the_setting_and_the_default_and_a_username_refused() -> None:
   """Catches the statuses setting ignored on this list in either direction, a bootstrap spent on
   a GET that carries no page token, and a username put into the path."""

   quiet = ScriptedTransport([json_response(recorded("mutual_followers.json"))])
   default = ScriptedTransport(
      [
         json_response(recorded("mutual_followers.json")),
         json_response(recorded("mutual_statuses.json")),
      ]
   )
   session = Session(sessionid="s", ds_user_id=USER_ID, csrftoken="c")
   sender = make_paced(quiet)

   mutual = await read_mutual_followers(sender, session, USER_ID, with_statuses=False)
   client = await scripted_client(default, SCRIPTED_BEHAVIOR)

   try:
      await client.profiles.mutual_followers(USER_ID)
   finally:
      await client.aclose()

   assert len(quiet.sent) == 1
   assert {account.friendship_status for account in mutual.accounts} == {None}
   assert [request.url for request in default.sent][1] == STATUSES_URL
   assert len(default.sent) == 2

   with pytest.raises(ValueError, match="numeric account id"):
      await read_mutual_followers(sender, session, USERNAME, with_statuses=False)

   assert len(quiet.sent) == 1


def test_the_blocking_mutual_followers_leave_the_statuses_out_when_told() -> None:
   """The read on the blocking surface under the departure, on the loop thread."""

   transport = ScriptedTransport([json_response(recorded("mutual_followers.json"))])

   with SyncClient(a_bootstrapped_session(), behavior=WITHOUT_STATUSES) as client:
      client._loop.run(client._impl._sender.aclose(), operation="the scripted sender swap")
      client._impl._sender = paced(transport, client._impl)
      mutual = client.profiles.mutual_followers(USER_ID)

   assert len(mutual.accounts) == 4
   assert len(transport.sent) == 1


class FakeFeeds:
   def __init__(self, grids: list[ExploreGrid], audio_pages: list[AudioPage]) -> None:
      self.grids = grids
      self.audio_pages = audio_pages
      self.explore_cursors: list[str | None] = []
      self.audio_calls: list[tuple[str, str | None]] = []

   def explore(self, *, after: str | None = None) -> ExploreGrid:
      self.explore_cursors.append(after)

      return self.grids[len(self.explore_cursors) - 1]

   def audio(self, audio_id: str, *, after: str | None = None) -> AudioPage:
      self.audio_calls.append((audio_id, after))

      return self.audio_pages[len(self.audio_calls) - 1]


class FakeProfiles:
   def __init__(self) -> None:
      self.asked: list[str] = []

   def mutual_followers(self, user_id: str) -> MutualFollowers:
      self.asked.append(user_id)
      page = attach_friendship_statuses(
         parse_mutual_followers_page(recorded("mutual_followers.json")),
         parse_friendship_statuses(recorded("mutual_statuses.json")),
      )

      return MutualFollowers(accounts=page.items, has_more=page.has_next_page)


class FakeClient:
   def __init__(
      self, grids: list[ExploreGrid] | None = None, audio_pages: list[AudioPage] | None = None
   ) -> None:
      self.session = Session(sessionid="s", ds_user_id=USER_ID, csrftoken="c")
      self.feeds = FakeFeeds(grids or [], audio_pages or [])
      self.profiles = FakeProfiles()
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


def recorded_grids() -> list[ExploreGrid]:
   return [
      parse_explore_grid(first_explore_page()),
      parse_explore_grid(last_explore_page()),
   ]


def recorded_audio_pages() -> list[AudioPage]:
   return [
      parse_audio_page(recorded("audio_original_first_page.json")),
      parse_audio_page(recorded("audio_original_second_page.json")),
   ]


def test_dumpsta_explore_reads_pages_on_the_root_cursor_until_the_grids_own_end() -> None:
   """Catches ``--pages`` ignored, the first cursor passed again or another one passed, a page
   read past the grid's end, and a post, the page count or the cursor left out of either form."""

   client = FakeClient(recorded_grids())
   code, out = run_command(["--json", "explore", "--pages", "5"], client)
   _, text = run_command(["explore", "--pages", "5"], FakeClient(recorded_grids()))
   payload = json.loads(out)

   assert code == 0
   assert client.feeds.explore_cursors == [None, first_explore_page()["max_id"]]
   assert payload["command"] == "explore"
   assert (payload["pages_read"], payload["section_count"], payload["post_count"]) == (2, 3, 11)
   assert payload["more_available"] is False
   assert payload["end_cursor"] == recorded("explore_next_page.json")["max_id"]
   assert "audio_id" in payload["sections"][0]["featured"][0]
   posts = [
      post for section in payload["sections"] for post in (*section["featured"], *section["posts"])
   ]
   located = [post for post in posts if post["location"] is not None]
   assert located
   assert all(
      post["tagged_place"] == {"id": post["location"]["id"], "name": post["location"]["name"]}
      for post in located
   )
   assert text.strip().splitlines()[-1] == "sections: 3  posts: 11  more_available: False"
   assert client.closed


def test_dumpsta_audio_reads_the_track_and_its_reels_until_the_pages_own_end() -> None:
   """Catches the command passing another audio id or cursor, stopping on the short first page
   while the page says more exist, reading past the empty last page, and the track, the count or
   a reel left out of either form."""

   audio_id = audio_id_of("audio_original_first_page.json")
   client = FakeClient(audio_pages=recorded_audio_pages())
   code, out = run_command(["--json", "audio", audio_id, "--pages", "5"], client)
   _, text = run_command(
      ["audio", audio_id, "--pages", "5"], FakeClient(audio_pages=recorded_audio_pages())
   )
   payload = json.loads(out)
   first_cursor = audio_payload("audio_original_first_page.json")["paging_info"]["max_id"]

   assert code == 0
   assert client.feeds.audio_calls == [(audio_id, None), (audio_id, first_cursor)]
   assert (payload["command"], payload["audio_id"]) == ("audio", audio_id)
   assert payload["audio"]["kind"] == "original_sound_info"
   assert payload["audio"]["audio_id"] == audio_id
   assert (payload["clips_count"], payload["pages_read"], payload["clip_count"]) == (1, 2, 1)
   assert (payload["more_available"], payload["end_cursor"]) == (False, None)
   assert payload["clips"][0]["audio_id"] == audio_id
   assert text.strip().splitlines()[-1] == "pages: 2  reels: 1  more_available: False"
   assert client.closed


def test_dumpsta_mutual_followers_prints_every_account_its_status_and_the_flag() -> None:
   """Catches the command reading another account, an account or its relationship left out of
   either form, and the flag that says the list goes on dropped."""

   client = FakeClient()
   code, out = run_command(["--json", "mutual-followers", USER_ID], client)
   _, text = run_command(["mutual-followers", USER_ID], FakeClient())
   payload = json.loads(out)

   assert code == 0
   assert client.profiles.asked == [USER_ID]
   assert (payload["command"], payload["user_id"], payload["account_count"]) == (
      "mutual-followers",
      USER_ID,
      4,
   )
   assert payload["more_available"] is False
   assert all(account["friendship_status"] is not None for account in payload["accounts"])
   assert text.strip().splitlines()[-1] == "accounts: 4  more_available: False"


@pytest.mark.parametrize(
   ("argv", "message"),
   [(["audio", "a title"], "numeric id"), (["mutual-followers", USERNAME], "numeric id")],
)
def test_the_new_commands_refuse_a_name(
   argv: list[str], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
   """Catches a title or a username reaching a read keyed on a numeric id."""

   client = FakeClient()
   code, _ = run_command(argv, client)

   assert code == 2
   assert message in capsys.readouterr().err
   assert client.feeds.audio_calls == []
   assert client.profiles.asked == []


def test_a_copied_fixture_is_not_mutated_by_a_read() -> None:
   """Catches a mapper that edits the answer it was given, which would make the absent-as-null
   defaults leak into the caller's copy of the payload."""

   answer = recorded("audio_song_first_page.json")
   before = copy.deepcopy(answer)

   parse_audio_page(answer)

   assert answer == before
