"""Map a home timeline page, whose items are posts, advertisements and suggestions."""

from __future__ import annotations

from typing import Any

from dumpstagram._private.web.parse.common import (
   _object_at,
   _optional_string,
   _required,
   _required_flag,
)
from dumpstagram._private.web.parse.media import parse_post
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import (
   FeedItem,
   FeedItemKind,
   Page,
)

__all__ = [
   "FEED_PAGE_PATH",
   "parse_feed_page",
]

FEED_PAGE_PATH = ("data", "xdt_api__v1__feed__timeline__connection")
"""The path to the home timeline connection.

One character away from :data:`~dumpstagram._private.web.parse.profiles.TIMELINE_PATH`, which
is a different connection on a different query: that one is one account's posts keyed on a
username, this one is the signed-in account's home feed.
"""


def _feed_item(node: Any, path: str) -> FeedItem:
   """One timeline item, reduced to the one union slot the upstream filled.

   Exactly one slot was non-null on all fifteen measured items. Two filled slots, or none,
   raises rather than picking a winner, because both shapes would mean the union stopped being
   a union and neither has a measured meaning.
   """

   if not isinstance(node, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

   filled = [key for key, value in node.items() if key != "__typename" and value is not None]

   if len(filled) != 1:
      raise SchemaChanged(
         f"{path} filled {len(filled)} of its union slots rather than exactly one", path=path
      )

   slot = filled[0]

   try:
      kind = FeedItemKind(slot)
   except ValueError as failure:
      raise SchemaChanged(
         f"{path}.{slot} is a union slot this version does not know", path=path
      ) from failure

   if kind is not FeedItemKind.POST:
      return FeedItem(kind=kind)

   return FeedItem(kind=kind, post=parse_post(node["media"], f"{path}.media"))


def parse_feed_page(payload: Any) -> Page[FeedItem]:
   """One ``PolarisFeedRootPaginationCachedQuery_subscribe`` payload, mapped into feed items.

   Items keep the order the upstream sent them in, and no item is dropped. Six of fifteen
   measured items were posts, so filtering the rest out here would make a page's length
   unexplainable to the caller and would hide how much of a feed is not posts.

   The per-edge ``cursor`` is ignored, and on this connection it has to be: it was null on all
   fifteen edges measured, while ``page_info.end_cursor`` was populated on every page. The
   cursor in ``page_info`` is the only one that paginates this surface.

   What the upstream sends on a media node and this mapper drops, from the fifteen-item page
   recorded on 2026-09-21:

   - ``owner_id``, an object repeating the author's ``pk`` and ``id`` a third time.
   - ``message_id``-style second names aside, ``caption.pk`` and ``caption.has_translation``,
     which belong to a caption capability that does not exist yet.
   - ``carousel_media``, the slides themselves, for the same reason.
   - ``clips_metadata``, ``video_versions``, ``video_dash_manifest``, ``has_audio``,
     ``number_of_qualities`` and ``view_count``, all null across the measured page because
     every post on it was a photo or a photo carousel. Video is unmeasured on this surface.
   - ``facepile_top_likers``, ``top_likers``, ``social_context``, ``floating_context_items``
     and ``media_notes``, which are presentation the web client assembles.
   - ``logging_info_token``, ``organic_tracking_token``, ``inventory_source`` and
     ``crosspost_metadata``, which are telemetry.
   - ``comments_disabled``, ``commenting_disabled_for_viewer``, ``has_viewer_saved``,
     ``can_reshare``, ``usertags``, ``location``, ``sponsor_tags`` and thirty more, null on
     every measured node, so there is nothing measured to model.

   Finding: `skills/reverse-engineer/knowledge/endpoints/home-timeline-feed-page.md`.
   """

   connection = _object_at(payload, FEED_PAGE_PATH)
   connection_path = ".".join(FEED_PAGE_PATH)

   edges = _required(connection, "edges", connection_path)

   if not isinstance(edges, list):
      raise SchemaChanged(f"{connection_path}.edges is not a list", path=f"{connection_path}.edges")

   items = tuple(
      _feed_item(
         _required(edge, "node", f"{connection_path}.edges[{index}]"),
         f"{connection_path}.edges[{index}].node",
      )
      for index, edge in enumerate(edges)
   )

   page_info_path = f"{connection_path}.page_info"
   page_info = _required(connection, "page_info", connection_path)

   if not isinstance(page_info, dict):
      raise SchemaChanged(f"{page_info_path} is not an object", path=page_info_path)

   has_next_page = _required_flag(page_info, "has_next_page", page_info_path)
   end_cursor = _optional_string(page_info, "end_cursor", page_info_path)

   return Page(items=items, has_next_page=has_next_page, end_cursor=end_cursor)
