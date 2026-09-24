"""Gates on the media model: video renditions, their duration, audio and carousel slides.

The fixtures under ``fixtures/media/`` are nodes the live timeline and the live post query sent on
2026-09-23, written by ``probes/media_shape.py --write-fixtures`` with every URL, id, name and
text replaced and every dimension, duration, flag and enumeration kept. The key sets are the live
ones, so a mapper that reads a key the upstream does not send fails here rather than live.

Four ways the mapping can be wrong are gated. A video can lose its renditions, their size, or its
length, which the web payload carries only inside the DASH manifest. A carousel can lose its
slides or flatten them into the parent's kind. The audio can come from the wrong slot, or name
the wrong artist. And a key the upstream renamed can be filled with a default rather than raise.

No carousel slide that was a video was seen live, so the one gate on a video slide builds it
from the live reel's own keys, which is said again where it is done.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from dumpstagram._private.web.parse.feed import parse_feed_page
from dumpstagram._private.web.parse.media import parse_post_detail
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import AudioKind, Post, PostDetail, VideoRendition
from tests.test_feed import item, payload
from tests.test_likes import post_payload

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "media"


def fixture(name: str) -> dict[str, Any]:
   loaded: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))

   return loaded


def feed_post(node: dict[str, Any]) -> Post:
   """Map one live-shaped media node through the whole timeline mapper, union wrapper included."""

   wrapper = item()
   wrapper["node"]["media"] = node
   page = parse_feed_page(payload([wrapper]))
   post = page.items[0].post

   assert post is not None

   return post


def detail(node: dict[str, Any]) -> PostDetail:
   return parse_post_detail(post_payload([node]))


def test_a_reel_maps_its_renditions_with_their_size_and_type_in_order() -> None:
   """Catches a reel whose renditions are dropped, reordered, or read with the wrong size."""

   post = feed_post(fixture("video_node"))

   assert post.media_type == 2
   assert post.videos == (
      VideoRendition(
         url="https://scontent.fixture.cdninstagram.com/v/fixture-3.mp4",
         width=720,
         height=1280,
         version_type=101,
      ),
      VideoRendition(
         url="https://scontent.fixture.cdninstagram.com/v/fixture-4.mp4",
         width=720,
         height=1280,
         version_type=102,
      ),
      VideoRendition(
         url="https://scontent.fixture.cdninstagram.com/v/fixture-5.mp4",
         width=720,
         height=1280,
         version_type=103,
      ),
   )
   assert (post.original_width, post.original_height) == (1080, 1920)
   assert len(post.images) == 14
   assert post.carousel_children == ()


def test_a_reel_reads_its_duration_from_the_manifest() -> None:
   """Catches a duration that is missing, truncated to whole seconds, or read from the wrong
   node, since the two reels carry 68.26667 and 86.599998 seconds."""

   assert feed_post(fixture("video_node")).video_duration == pytest.approx(68.26667, abs=1e-9)
   assert feed_post(fixture("video_with_music_node")).video_duration == pytest.approx(
      86.599998, abs=1e-9
   )


@pytest.mark.parametrize(
   ("iso", "seconds"),
   [("PT1H2M3.5S", 3723.5), ("PT4M", 240.0), ("PT0S", 0.0), ("PT10.048S", 10.048)],
)
def test_a_manifest_duration_is_read_in_hours_minutes_and_seconds(iso: str, seconds: float) -> None:
   """Catches a duration parser that reads only the seconds, which a reel over a minute would
   expose as a wrong length rather than an error."""

   node = fixture("video_node")
   node["video_dash_manifest"] = (
      f'<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" mediaPresentationDuration="{iso}"/>'
   )

   assert feed_post(node).video_duration == pytest.approx(seconds, abs=1e-9)


def test_an_original_sound_names_the_account_that_made_it() -> None:
   """Catches the audio read from the wrong slot, or its artist and id left out."""

   post = feed_post(fixture("video_node"))

   assert post.has_audio is True
   assert post.audio is not None
   assert post.audio.kind is AudioKind.ORIGINAL_SOUND
   assert post.audio.audio_id == "10000000000000004"
   assert post.audio.title == "fixture original_audio_title"
   assert post.audio.artist == "fixture username"
   assert post.audio.artist_id == "10000000002"
   assert post.audio.is_explicit is False
   assert post.audio.should_mute is False


def test_a_licensed_song_names_its_title_and_display_artist() -> None:
   """Catches a song mapped as an original sound, or with the cluster id and artist mixed up."""

   post = feed_post(fixture("video_with_music_node"))

   assert post.audio is not None
   assert post.audio.kind is AudioKind.MUSIC
   assert post.audio.audio_id == "1000000000000007"
   assert post.audio.title == "fixture title"
   assert post.audio.artist == "fixture display_artist"
   assert post.audio.artist_id is None
   assert post.audio.should_mute is False


def test_a_reel_with_both_audio_slots_filled_raises() -> None:
   """Catches a mapper that picks one of two tracks when the union stops being a union."""

   node = fixture("video_node")
   node["clips_metadata"]["music_info"] = fixture("video_with_music_node")["clips_metadata"][
      "music_info"
   ]

   with pytest.raises(SchemaChanged) as caught:
      feed_post(node)

   assert caught.value.path is not None
   assert caught.value.path.endswith("clips_metadata")


def test_a_carousel_maps_every_slide_with_its_own_kind() -> None:
   """Catches slides dropped, reordered, or given the parent's kind rather than their own."""

   post = feed_post(fixture("carousel_node"))

   assert post.media_type == 8
   assert post.carousel_media_count == 6
   assert [child.pk for child in post.carousel_children] == [
      "1000000000000000011",
      "1000000000000000012",
      "1000000000000000013",
      "1000000000000000014",
      "1000000000000000015",
      "1000000000000000016",
   ]

   for child in post.carousel_children:
      assert child.id == f"{child.pk}_10000000010"
      assert child.media_type == 1
      assert child.product_type == "carousel_item"
      assert (child.original_width, child.original_height) == (1080, 1350)
      assert len(child.images) == 13
      assert child.videos == ()
      assert child.video_duration is None

   assert post.videos == ()
   assert post.video_duration is None
   assert post.has_audio is None
   assert post.audio is None


def test_a_video_slide_maps_its_renditions_and_duration() -> None:
   """Catches a slide mapper that reads only photos. No video slide was seen live, so this one is
   the live carousel's first slide given the live reel's video keys and kind."""

   node = fixture("carousel_node")
   reel = fixture("video_node")
   slide = node["carousel_media"][0]
   slide["media_type"] = 2
   slide["video_versions"] = reel["video_versions"]
   slide["video_dash_manifest"] = reel["video_dash_manifest"]

   child = feed_post(node).carousel_children[0]

   assert child.media_type == 2
   assert [rendition.version_type for rendition in child.videos] == [101, 102, 103]
   assert child.video_duration == pytest.approx(68.26667, abs=1e-9)
   assert feed_post(node).carousel_children[1].media_type == 1


def test_the_post_query_maps_a_reel_and_a_carousel_the_way_the_timeline_does() -> None:
   """Catches the post read left without the media fields, and a slide mapper that demands the
   ``has_audio`` the post query's slides do not carry."""

   reel = detail(fixture("post_detail_video_item"))
   carousel = detail(fixture("post_detail_carousel_item"))

   assert [rendition.version_type for rendition in reel.videos] == [101, 102, 103]
   assert reel.video_duration == pytest.approx(68.26667, abs=1e-9)
   assert reel.has_audio is True
   assert reel.audio is not None
   assert reel.audio.kind is AudioKind.ORIGINAL_SOUND
   assert reel.audio.artist_id == "10000000002"

   assert len(carousel.carousel_children) == 6
   assert {child.media_type for child in carousel.carousel_children} == {1}
   assert carousel.carousel_children[0].accessibility_caption is None
   assert carousel.audio is None


def test_a_photo_carries_no_video_audio_or_slides() -> None:
   """Catches a photo given empty-looking media rather than none, the synthetic 2026-09-21 node."""

   post = feed_post(item()["node"]["media"])

   assert post.videos == ()
   assert post.video_duration is None
   assert post.has_audio is None
   assert post.audio is None
   assert post.carousel_children == ()


def without(node: dict[str, Any], *path: str | int) -> dict[str, Any]:
   trimmed = copy.deepcopy(node)
   parent: Any = trimmed

   for step in path[:-1]:
      parent = parent[step]

   del parent[path[-1]]

   return trimmed


MISSING_KEYS = [
   ("video_node", ("video_versions",), "video_versions"),
   ("video_node", ("video_versions", 0, "type"), "video_versions[0].type"),
   ("video_node", ("video_versions", 1, "width"), "video_versions[1].width"),
   ("video_node", ("video_dash_manifest",), "video_dash_manifest"),
   ("video_node", ("has_audio",), "has_audio"),
   ("video_node", ("clips_metadata",), "clips_metadata"),
   ("video_node", ("clips_metadata", "music_info"), "clips_metadata.music_info"),
   (
      "video_node",
      ("clips_metadata", "original_sound_info", "ig_artist", "username"),
      "original_sound_info.ig_artist.username",
   ),
   (
      "video_with_music_node",
      ("clips_metadata", "music_info", "music_asset_info", "display_artist"),
      "music_asset_info.display_artist",
   ),
   (
      "video_with_music_node",
      ("clips_metadata", "music_info", "music_consumption_info", "should_mute_audio"),
      "music_consumption_info.should_mute_audio",
   ),
   ("carousel_node", ("carousel_media",), "carousel_media"),
   ("carousel_node", ("carousel_media", 2, "media_type"), "carousel_media[2].media_type"),
   ("carousel_node", ("carousel_media", 0, "video_versions"), "carousel_media[0].video_versions"),
]


@pytest.mark.parametrize(
   ("name", "path", "reported"), MISSING_KEYS, ids=[reported for _, _, reported in MISSING_KEYS]
)
def test_a_missing_named_key_raises_schema_changed_naming_it(
   name: str, path: tuple[str | int, ...], reported: str
) -> None:
   """Catches a default filled in where the upstream renamed or dropped a key."""

   with pytest.raises(SchemaChanged) as caught:
      feed_post(without(fixture(name), *path))

   assert caught.value.path is not None
   assert caught.value.path.endswith(reported)


def test_a_manifest_without_a_duration_raises() -> None:
   """Catches a reel reported with no length because its manifest changed shape."""

   node = fixture("video_node")
   node["video_dash_manifest"] = '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static"/>'

   with pytest.raises(SchemaChanged) as caught:
      feed_post(node)

   assert caught.value.path is not None
   assert caught.value.path.endswith("video_dash_manifest")


def test_a_duration_outside_the_root_element_is_not_read() -> None:
   """Catches a manifest searched past its root tag, where a representation's own attributes
   could name something that is not the whole video's length."""

   node = fixture("video_node")
   node["video_dash_manifest"] = (
      '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period mediaPresentationDuration="PT5S"/></MPD>'
   )

   with pytest.raises(SchemaChanged):
      feed_post(node)
