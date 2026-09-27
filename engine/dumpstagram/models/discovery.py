"""Typed representations of the discovery reads: the explore grid and a place's page.

Every field below was observed on the answers ``probes/e2_discovery_feeds.py`` kept on
2026-09-27, run ``run-2026-09-27-014102``: the explore grid read twice with four sections each, a
place's header read twice, and its grid read twice.

Nothing here parses. Construction is done by the mappers in ``_private/web/parse/discovery.py``,
which read named keys and raise rather than filling a default, so an upstream rename is loud.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from dumpstagram.models.feed import Post
from dumpstagram.models.posts import PostThumbnail

__all__ = [
   "ExploreGrid",
   "ExploreSection",
   "LocationPosts",
   "LocationTab",
   "Place",
]


@dataclass(frozen=True)
class ExploreSection:
   """One block of the explore grid, its posts in the upstream's order.

   ``featured`` holds the posts of the block's large tile and ``posts`` the smaller tiles beside
   it. Every section read carried exactly one featured post, a reel, and four others. How the
   tiles are laid out, which side the large one sits on, and its column counts are presentation
   and are not modelled. ``feed_type`` is the upstream's name for the block's kind, ``clips`` on
   all eight sections read.
   """

   feed_type: str
   featured: tuple[Post, ...]
   posts: tuple[Post, ...]


@dataclass(frozen=True)
class ExploreGrid:
   """The first page of the explore grid.

   ``more_available`` is the upstream's own flag that the grid goes on. It was true on both
   answers read, but no next page has been asked for, so nothing here reads one (W77).
   """

   sections: tuple[ExploreSection, ...]
   more_available: bool

   @property
   def posts(self) -> tuple[Post, ...]:
      """Every post of every section, each section's featured posts before its others."""

      return tuple(
         post for section in self.sections for post in (*section.featured, *section.posts)
      )


class LocationTab(StrEnum):
   """Which of a place's grids to read.

   Only ``ranked`` has been sent and answered. The page's compiled query also names a ``recent``
   tab, which is not a member until a read of it is verified (W79).
   """

   RANKED = "ranked"


@dataclass(frozen=True)
class LocationPosts:
   """The first page of the posts tagged at a place, in the upstream's order.

   ``has_more`` is the page's own ``has_next_page``, true on both answers read. The query that
   pages the grid answered, but on the first page's cursor it answered that same cursor again and
   20 of its 24 posts were already on the first page, so following it is not shown to read further
   and nothing here reads a later page (W79).

   Each post is a :class:`~dumpstagram.models.PostThumbnail`, because the grid sends its author
   without a full name.
   """

   posts: tuple[PostThumbnail, ...]
   has_more: bool


@dataclass(frozen=True)
class Place:
   """The header of a place's page.

   ``id`` is the place's ``pk``, the same value :attr:`~dumpstagram.models.Location.id` carries
   on a post tagged there. ``media_count`` is how many posts are tagged there. ``slug`` is the
   name the page's address carries. ``address``, ``city``, ``zip_code`` and ``phone`` are
   strings as the upstream sends them, and it sent an empty string for each one the place
   lacked. ``price_range`` is the upstream's number, ``0`` on the one place read.
   """

   id: str
   name: str
   category: str
   lat: float
   lng: float
   media_count: int
   slug: str
   address: str
   city: str
   zip_code: str
   phone: str
   price_range: int
