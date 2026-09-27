"""Map the explore grid, a place's header and grid, and the new posts check into typed models.

Built from the answers ``probes/e2_discovery_feeds.py`` kept on 2026-09-27. Dropped, and why:

- on the explore grid, ``clusters``, one ``explore_all`` cluster naming the grid's own tab,
  ``rank_token``, ``session_paging_token``, ``max_id`` and ``next_max_id``, which a later page
  would carry back and which no request here sends (W77), ``auto_load_more_enabled``,
  ``quantum_signals_parsed``, and ``debug_info``, ``grid_overlay_debug_info``, ``interests``,
  ``overlay_info``, ``tentpole_interest`` and ``tentpole_interests``, null on both answers
- on a section, ``layout_type``, ``explore_item_info``, the large tile's cluster fields
  (``id``, ``type``, ``design``, ``label``, ``content_source``, ``badge_label``, ``tag``,
  ``chaining_info``, ``max_id`` and ``more_available``), which are presentation and a reel
  viewer's chaining, and on a post everything the timeline's post mapper drops, and
  ``video_duration``, ``play_count``, ``ig_play_count``, ``owner``, ``music_metadata``,
  ``impression_token``, ``explore``, ``explore_context`` and the rest of the REST node's
  telemetry and presentation
- on a place, ``ig_business.profile``, null on both answers, and ``hours.status``, an empty
  string on both, since neither shape has been seen filled
- on a place's grid, ``page_info.end_cursor``, which nothing here follows, ``cursor`` on each
  edge, null on all, and on a node everything :class:`~dumpstagram.models.PostThumbnail` does
  not carry (W79)
- on the reels feed, ``gating``, null on all four answers, ``has_previous_page`` and
  ``start_cursor``, false and null, each edge's ``cursor``, an empty string on all 11, and on a
  reel everything the timeline's post mapper drops, and ``media_repost_count``,
  ``tappable_elements``, ``brs_severity``, ``view_state_item_type``, ``is_in_profile_grid``,
  ``profile_grid_control_enabled``, ``can_viewer_reshare``, ``ig_media_sharing_disabled``,
  ``sharing_friction_info``, ``enable_media_notes_production``, ``fb_like_count``,
  ``fb_comment_count``, ``creative_config`` and ``is_shared_from_basel``, which are sharing
  controls, Facebook's own counts and telemetry, and the author's ``profile_pic_url_hd``,
  ``is_embeds_disabled``, ``is_unpublished``, ``is_ai_user``, ``aigm_account_label_info`` and
  ``show_account_transparency_details`` (W101)
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from dumpstagram._private.web.parse.common import (
   _object_at,
   _optional_string,
   _required,
   _required_flag,
   _required_integer,
   _required_string,
)
from dumpstagram._private.web.parse.media import (
   _music,
   _original_sound,
   _post_thumbnail,
   audio_page_id,
   parse_post,
   tagged_place,
)
from dumpstagram._private.web.parse.posting import _raise_unless_ok
from dumpstagram._private.web.parse.profiles import _list_of
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import (
   AudioPage,
   ExploreGrid,
   ExploreSection,
   LocationPosts,
   MediaAudio,
   Page,
   Place,
   Post,
)

__all__ = [
   "AUDIO_PAGE_PATH",
   "LOCATION_INFO_PATH",
   "LOCATION_POSTS_PATH",
   "NEW_FEED_POSTS_PATH",
   "REELS_FEED_PATH",
   "REST_KEYS_ABSENT_AS_NULL",
   "parse_audio_page",
   "parse_explore_grid",
   "parse_location_info",
   "parse_location_posts",
   "parse_new_feed_posts",
   "parse_reels_feed_page",
]

LOCATION_INFO_PATH = (
   "data",
   "xdt_location_get_web_info",
   "native_location_data",
   "location_info",
)
"""The path to the place in a ``PolarisExploreLocationsContainerQuery`` payload."""

LOCATION_POSTS_PATH = ("data", "xdt_location_get_web_info_tab")
"""The path to the grid's connection."""

NEW_FEED_POSTS_PATH = ("data", "xdt_api__v1__new_feed_posts_exist")
"""The path to the object carrying the new posts flag."""

REELS_FEED_PATH = ("data", "xdt_api__v1__clips__home__connection_v2")
"""The path to the reels feed's connection, the same on its first page and on every later one."""

REEL_KEYS_ABSENT_AS_NULL = frozenset({"is_seen", "accessibility_caption"})
"""The keys a reels feed reel leaves out that a timeline post sends, each read as null when
absent (W101). Both were absent on all 11 reels of the four answers read. ``is_seen`` then reads
as False, as a profile grid's null does under W53, since the feed is not a timeline the viewer
has seen things in."""

REST_KEYS_ABSENT_AS_NULL = frozenset(
   {
      "accessibility_caption",
      "carousel_media",
      "carousel_media_count",
      "clips_metadata",
      "has_audio",
      "is_seen",
      "video_dash_manifest",
      "video_versions",
   }
)
"""The keys the explore grid's REST media leaves out, each read as null when absent (W77): the
ones a GraphQL node of the same kind sends null, and ``is_seen``, which a profile's grid sends
null.

Over the 40 posts of both answers, 37 reels, 2 photos and 1 carousel: ``is_seen`` was absent on
all 40, ``accessibility_caption`` on the 37 reels, ``carousel_media`` and
``carousel_media_count`` on the 39 posts that are not a carousel, and ``clips_metadata``,
``has_audio``, ``video_versions`` and ``video_dash_manifest`` on the 2 photos and the carousel.
Each of the carousel's 16 photo slides lacked ``video_versions`` and ``video_dash_manifest``. A
key outside this set that the mapper needs still raises when it is absent. ``location`` and
``usertags``, absent on 35 and 34, are read as not carried, as on every post read.
"""

AUDIO_PAGE_PATH = ("payload",)
"""The path to the audio page inside the ``for (;;);`` wrapper, whose other keys are ``__ar``,
``rid`` and ``lid``."""

_EXPLORE = "<explore grid>"

_SECTION_CONTENT_KEYS = frozenset({"one_by_two_item", "fill_items"})

_DYNAMIC_GRID_CONTENT_KEYS = frozenset({"medias"})
"""The one block a later explore page's section carried, on all 12 sections of both replays of
the next page (W115)."""


def _absent_as_null(node: Any) -> Any:
   """``node`` with each of :data:`REST_KEYS_ABSENT_AS_NULL` it lacks set to null, and each of
   its carousel slides treated the same way. Anything but an object is returned untouched, for
   the post mapper to refuse."""

   if not isinstance(node, dict):
      return node

   filled = {key: None for key in REST_KEYS_ABSENT_AS_NULL if key not in node}
   graph_node = {**node, **filled}
   slides = graph_node.get("carousel_media")

   if isinstance(slides, list):
      graph_node["carousel_media"] = [_absent_as_null(slide) for slide in slides]

   return graph_node


def _explore_post(node: Any, path: str) -> Post:
   """One REST media node of the grid, mapped as a timeline post is.

   ``is_seen`` is never sent here, and the grid is not a feed the viewer has seen things in, so
   it reads as False, as a profile grid's null does under W53.
   """

   return parse_post(_absent_as_null(node), path, null_is_unseen=True)


def _media_of(entry: Any, path: str) -> Post:
   return _explore_post(_required(entry, "media", path), f"{path}.media")


def _explore_section(section: Any, path: str) -> ExploreSection:
   """One section: the large tile's reel cluster and the fill tiles beside it.

   All eight sections read carried exactly these two blocks. A section carrying another block
   raises rather than being dropped, because a post it holds would silently go missing.
   """

   if not isinstance(section, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

   content_path = f"{path}.layout_content"
   content = _object_at(section, ("layout_content",))
   is_a_dynamic_grid = set(content) == _DYNAMIC_GRID_CONTENT_KEYS

   if is_a_dynamic_grid:
      return _dynamic_grid_section(section, content, path)

   unknown = sorted(set(content) - _SECTION_CONTENT_KEYS)

   if unknown:
      raise SchemaChanged(
         f"{content_path} carries {', '.join(unknown)}, a block this version does not know",
         path=content_path,
      )

   large_tile_path = f"{content_path}.one_by_two_item.clips"
   large_tile = _object_at(content, ("one_by_two_item", "clips"))
   featured_items = _list_of(large_tile, "items", large_tile_path)
   fill_items = _list_of(content, "fill_items", content_path)

   return ExploreSection(
      feed_type=_required_string(section, "feed_type", path),
      featured=tuple(
         _media_of(item, f"{large_tile_path}.items[{index}]")
         for index, item in enumerate(featured_items)
      ),
      posts=tuple(
         _media_of(item, f"{content_path}.fill_items[{index}]")
         for index, item in enumerate(fill_items)
      ),
   )


def _dynamic_grid_section(
   section: dict[str, Any], content: dict[str, Any], path: str
) -> ExploreSection:
   """One section of a later page, whose one ``medias`` block holds the large tile and the fill
   tiles in a single list (W115).

   An entry is a fill tile, ``{"media": ...}``, or a large tile, ``{"clips": {"items": [{"media":
   ...}]}}``. On all 12 sections read each held two fill tiles and one large tile of one reel, the
   large tile first on half of them and last on the other half. The large tiles' posts are the
   section's ``featured`` and the fill tiles its ``posts``, as on a first page, so where the large
   tile sat is not kept. An entry of any other shape raises, because a post it held would go
   missing.
   """

   medias_path = f"{path}.layout_content.medias"
   entries = _list_of(content, "medias", f"{path}.layout_content")
   featured: list[Post] = []
   posts: list[Post] = []

   for index, entry in enumerate(entries):
      entry_path = f"{medias_path}[{index}]"
      keys = set(entry) if isinstance(entry, dict) else None

      if keys == {"media"}:
         posts.append(_media_of(entry, entry_path))

         continue

      if keys != {"clips"}:
         raise SchemaChanged(
            f"{entry_path} is neither a fill tile nor a large tile", path=entry_path
         )

      tile_path = f"{entry_path}.clips"
      tile = _object_at(entry, ("clips",))
      items = _list_of(tile, "items", tile_path)
      featured.extend(
         _media_of(item, f"{tile_path}.items[{item_index}]")
         for item_index, item in enumerate(items)
      )

   return ExploreSection(
      feed_type=_required_string(section, "feed_type", path),
      featured=tuple(featured),
      posts=tuple(posts),
   )


def _cursor_if_carried(node: dict[str, Any], path: str) -> str | None:
   """``max_id`` where the answer carries it, ``None`` where the key is absent or null, as it was
   absent on the last audio page read. A value of another type raises."""

   if node.get("max_id") is None:
      return None

   return _required_string(node, "max_id", path)


def parse_explore_grid(payload: Any) -> ExploreGrid:
   """One page of the explore grid, first or later, its sections in the upstream's order.

   ``end_cursor`` is the root ``max_id``, which equalled the root ``session_paging_token`` on all
   five answers read and is what the next page is asked for with. The root ``next_max_id``, a page
   counter, and the ``max_id`` each large tile's cluster carries are not the paging value (W115).

   Findings: ``read-the-explore-grid`` and ``read-the-explore-grid-next-page``.
   """

   _raise_unless_ok(payload, "explore grid")

   sections = _list_of(payload, "sectional_items", _EXPLORE)

   return ExploreGrid(
      sections=tuple(
         _explore_section(section, f"{_EXPLORE}.sectional_items[{index}]")
         for index, section in enumerate(sections)
      ),
      more_available=_required_flag(payload, "more_available", _EXPLORE),
      end_cursor=_cursor_if_carried(payload, _EXPLORE),
   )


def _coordinate(node: dict[str, Any], key: str, path: str) -> float:
   raw = _required(node, key, path)
   is_a_number = isinstance(raw, int | float) and not isinstance(raw, bool)

   if not is_a_number:
      raise SchemaChanged(f"{path}.{key} is not a number", path=f"{path}.{key}")

   return float(raw)


def parse_location_info(payload: Any) -> Place:
   """One ``PolarisExploreLocationsContainerQuery`` payload, the place it describes.

   Finding: ``read-a-location-s-info``.
   """

   info = _object_at(payload, LOCATION_INFO_PATH)
   path = ".".join(LOCATION_INFO_PATH)

   return Place(
      id=_required_string(info, "location_id", path),
      name=_required_string(info, "name", path),
      category=_required_string(info, "category", path),
      lat=_coordinate(info, "lat", path),
      lng=_coordinate(info, "lng", path),
      media_count=_required_integer(info, "media_count", path),
      slug=_required_string(info, "slug", path),
      address=_required_string(info, "location_address", path),
      city=_required_string(info, "location_city", path),
      zip_code=_required_string(info, "location_zip", path),
      phone=_required_string(info, "phone", path),
      price_range=_required_integer(info, "price_range", path),
   )


def parse_location_posts(payload: Any) -> LocationPosts:
   """The first page of a place's grid, the posts in the upstream's order.

   A node carries its author without ``full_name`` or a high resolution picture, no ``is_seen``,
   and slides without ``product_type``, so the post is a
   :class:`~dumpstagram.models.PostThumbnail` rather than a ``Post`` with guesses in it (W79).

   Finding: ``read-a-location-page-tab``.
   """

   connection = _object_at(payload, LOCATION_POSTS_PATH)
   connection_path = ".".join(LOCATION_POSTS_PATH)
   edges = _list_of(connection, "edges", connection_path)
   posts = tuple(
      _post_thumbnail(
         _required(edge, "node", f"{connection_path}.edges[{index}]"),
         f"{connection_path}.edges[{index}].node",
      )
      for index, edge in enumerate(edges)
   )
   page_info_path = f"{connection_path}.page_info"
   page_info = _object_at(connection, ("page_info",))

   return LocationPosts(
      posts=posts,
      has_more=_required_flag(page_info, "has_next_page", page_info_path),
   )


def parse_new_feed_posts(payload: Any) -> bool:
   """Whether the home feed has new posts, the upstream's flag as sent.

   Finding: ``check-for-new-feed-posts``.
   """

   root = _object_at(payload, NEW_FEED_POSTS_PATH)

   return _required_flag(root, "new_feed_posts_exist", ".".join(NEW_FEED_POSTS_PATH))


def _reel_feed_node(media: Any) -> Any:
   """``media`` as the timeline's post mapper reads it, with what the reels feed leaves out or
   sends in another shape made explicit (W101). Anything but an object is returned untouched,
   for the post mapper to refuse.

   - :data:`REEL_KEYS_ABSENT_AS_NULL` read as null when absent.
   - ``is_paid_partnership``, absent on all 11 reels, reads as False when absent, which carries
     no information here, as ``is_seen`` does on a grid.
   - The author's ``hd_profile_pic_url_info``, absent on all 11, reads as null, so the author's
     ``hd_profile_pic_url`` is ``None``; the author's ``profile_pic_url_hd`` is not read.
   - ``coauthor_producers`` carried ``pk`` and ``id`` only on the one reel that had one, with no
     username, so it is not read and ``collaborators`` is ``None``, not carried.
   - A location sent with only ``name`` and ``pk``, on all 3 located reels of the answers kept at
     19:12 on 2026-09-27, reads as no location, since :class:`~dumpstagram.models.Location`
     requires its coordinates; the post's ``tagged_place`` still names it (W120). A location
     with both coordinates is read whole.
   - An original sound carried no ``should_mute_audio`` on any of the 8 read, which
     :class:`~dumpstagram.models.MediaAudio` requires, so such a reel's ``audio`` is ``None``
     rather than a guessed flag, W63's rule for the post read by media pk. A song carries the flag
     and is read.
   """

   if not isinstance(media, dict):
      return media

   filled = {key: None for key in REEL_KEYS_ABSENT_AS_NULL if key not in media}
   node = {**media, **filled}
   node.setdefault("is_paid_partnership", False)
   node.pop("coauthor_producers", None)
   author = node.get("user")

   if isinstance(author, dict):
      node["user"] = {"hd_profile_pic_url_info": None, **author}

   place = node.get("location")
   is_a_place_without_coordinates = isinstance(place, dict) and not {"lat", "lng"} <= set(place)

   if is_a_place_without_coordinates:
      node["location"] = None

   metadata = node.get("clips_metadata") or {}
   original = metadata.get("original_sound_info") if isinstance(metadata, dict) else None
   lacks_the_mute_flag = isinstance(original, dict) and "should_mute_audio" not in original

   if lacks_the_mute_flag:
      node["clips_metadata"] = {**metadata, "original_sound_info": None}

   return node


def _reel(edge: Any, path: str) -> Post:
   node = _object_at(edge, ("node",))
   node_path = f"{path}.node"
   media = _required(node, "media", node_path)

   return parse_post(_reel_feed_node(media), f"{node_path}.media", null_is_unseen=True)


def _reel_naming_its_audio(edge: Any, path: str) -> Post:
   """One reel of the feed with ``audio_id`` and ``tagged_place`` read off the media as sent,
   before an original sound without its mute flag or a place without coordinates is set aside, so
   a reel with no ``audio`` or ``location`` still names its audio page and its place (W118,
   W120)."""

   post = _reel(edge, path)
   media = _required(_object_at(edge, ("node",)), "media", f"{path}.node")

   media_path = f"{path}.node.media"

   return replace(
      post,
      audio_id=audio_page_id(media, media_path),
      tagged_place=tagged_place(media, media_path),
   )


def parse_reels_feed_page(payload: Any) -> Page[Post]:
   """One reels feed page, first or later, the reels in the upstream's order.

   ``end_cursor`` is the upstream's own cursor, which the capability joins with the page's reels
   before handing it out (W101).

   Findings: ``read-the-reels-tab-first-page`` and ``read-the-reels-tab-next-page``.
   """

   connection = _object_at(payload, REELS_FEED_PATH)
   connection_path = ".".join(REELS_FEED_PATH)
   edges = _list_of(connection, "edges", connection_path)
   reels = tuple(
      _reel_naming_its_audio(edge, f"{connection_path}.edges[{edge_index}]")
      for edge_index, edge in enumerate(edges)
   )
   page_info_path = f"{connection_path}.page_info"
   page_info = _object_at(connection, ("page_info",))

   return Page(
      items=reels,
      has_next_page=_required_flag(page_info, "has_next_page", page_info_path),
      end_cursor=_optional_string(page_info, "end_cursor", page_info_path),
   )


_AUDIO_PAGE = "<audio page>"


def _audio_clip_node(media: Any) -> Any:
   """``media`` as the post mapper reads it, with what an audio page's reel leaves out or sends in
   another shape made explicit (W116). Anything but an object is returned untouched, for the post
   mapper to refuse.

   - :data:`REST_KEYS_ABSENT_AS_NULL` read as null when absent, as on the explore grid's REST
     media: ``accessibility_caption`` was absent on all 75 reels of the 11 answers read.
   - The author's ``hd_profile_pic_url_info``, absent on all 75, reads as null, so the author's
     ``hd_profile_pic_url`` is ``None``.
   - ``coauthor_producers`` rows sent ``pk`` as a number and a relationship without the two
     request flags :class:`~dumpstagram.models.ListFriendshipStatus` requires, on both reels that
     had one, so they are not read and ``collaborators`` is ``None``, not carried.
   """

   if not isinstance(media, dict):
      return media

   node = {
      key: value for key, value in _absent_as_null(media).items() if key != "coauthor_producers"
   }
   author = node.get("user")

   if isinstance(author, dict):
      node["user"] = {"hd_profile_pic_url_info": None, **author}

   return node


def _audio_clip(item: Any, path: str) -> Post:
   media = _required(item, "media", path)

   return parse_post(_audio_clip_node(media), f"{path}.media", null_is_unseen=True)


def _page_audio(metadata: dict[str, Any], path: str) -> MediaAudio | None:
   """The track the page describes, read as a reel's ``clips_metadata`` is: a song from
   ``music_info``, an original sound from ``original_sound_info``, ``None`` when both are null,
   and both filled raises. ``additional_audio_info`` was null on all 11 answers and is not read."""

   music = _required(metadata, "music_info", path)
   original = _required(metadata, "original_sound_info", path)
   has_music = music is not None
   has_original = original is not None

   if has_music and has_original:
      raise SchemaChanged(f"{path} filled both music_info and original_sound_info", path=path)

   if has_music:
      return _music(music, f"{path}.music_info")

   if has_original:
      return _original_sound(original, f"{path}.original_sound_info")

   return None


def parse_audio_page(payload: Any) -> AudioPage:
   """One page of an audio's page, first or later, the reels in the upstream's order.

   The answer arrives inside the ``for (;;);`` wrapper the classifier strips, as ``payload``
   beside ``__ar``, ``rid`` and ``lid``. ``end_cursor`` is ``paging_info.max_id``, absent on the
   last page read. Dropped: ``audio_page_reporting_id``, ``music_canonical_id``,
   ``formatted_media_count``, the count as display text, ``media_count.photos_count``, 0 on every
   answer, ``audio_ranking_info``, ``auto_created_reels_preview_metadata`` and
   ``audio_page_segments``, empty lists on every answer, ``available_tabs``, the page's tab bar,
   ``spotify_track_metadata``, a link to the song on another service, and on the track everything
   :class:`~dumpstagram.models.MediaAudio` does not carry.

   Findings: ``read-an-audio-page`` and ``read-an-audio-page-next-page``.
   """

   page = _object_at(payload, AUDIO_PAGE_PATH)
   metadata_path = f"{_AUDIO_PAGE}.metadata"
   metadata = _object_at(page, ("metadata",))
   counts = _object_at(page, ("media_count",))
   paging = _object_at(page, ("paging_info",))
   items = _list_of(page, "items", _AUDIO_PAGE)

   return AudioPage(
      audio=_page_audio(metadata, metadata_path),
      clips_count=_required_integer(counts, "clips_count", f"{_AUDIO_PAGE}.media_count"),
      is_restricted=_required_flag(page, "is_music_page_restricted", _AUDIO_PAGE),
      clips=tuple(
         _audio_clip(item, f"{_AUDIO_PAGE}.items[{index}]") for index, item in enumerate(items)
      ),
      more_available=_required_flag(paging, "more_available", f"{_AUDIO_PAGE}.paging_info"),
      end_cursor=_cursor_if_carried(paging, f"{_AUDIO_PAGE}.paging_info"),
   )
