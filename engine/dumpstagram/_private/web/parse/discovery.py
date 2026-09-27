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
"""

from __future__ import annotations

from typing import Any

from dumpstagram._private.web.parse.common import (
   _object_at,
   _required,
   _required_flag,
   _required_integer,
   _required_string,
)
from dumpstagram._private.web.parse.media import _post_thumbnail, parse_post
from dumpstagram._private.web.parse.posting import _raise_unless_ok
from dumpstagram._private.web.parse.profiles import _list_of
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import (
   ExploreGrid,
   ExploreSection,
   LocationPosts,
   Place,
   Post,
)

__all__ = [
   "LOCATION_INFO_PATH",
   "LOCATION_POSTS_PATH",
   "NEW_FEED_POSTS_PATH",
   "REST_KEYS_ABSENT_AS_NULL",
   "parse_explore_grid",
   "parse_location_info",
   "parse_location_posts",
   "parse_new_feed_posts",
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

_EXPLORE = "<explore grid>"

_SECTION_CONTENT_KEYS = frozenset({"one_by_two_item", "fill_items"})


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


def parse_explore_grid(payload: Any) -> ExploreGrid:
   """The explore grid's first page, its sections in the upstream's order.

   Finding: ``read-the-explore-grid``.
   """

   _raise_unless_ok(payload, "explore grid")

   sections = _list_of(payload, "sectional_items", _EXPLORE)

   return ExploreGrid(
      sections=tuple(
         _explore_section(section, f"{_EXPLORE}.sectional_items[{index}]")
         for index, section in enumerate(sections)
      ),
      more_available=_required_flag(payload, "more_available", _EXPLORE),
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
