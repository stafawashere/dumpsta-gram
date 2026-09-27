"""Typed representations of the discovery reads: the explore grid, a place's page and an
audio's page.

Every field below was observed on the answers ``probes/e2_discovery_feeds.py`` kept on
2026-09-27, run ``run-2026-09-27-014102``: the explore grid read twice with four sections each, a
place's header read twice, and its grid read twice.

Nothing here parses. Construction is done by the mappers in ``_private/web/parse/discovery.py``,
which read named keys and raise rather than filling a default, so an upstream rename is loud.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from dumpstagram.models.feed import MediaAudio, Post
from dumpstagram.models.posts import PostThumbnail

__all__ = [
   "AudioPage",
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
   """One page of the explore grid, the first or a later one.

   ``more_available`` is the upstream's own flag that the grid goes on, and the only thing that
   ends a walk (W115). It was true on all five answers read, first pages and later ones, so no
   last page has been seen. ``end_cursor`` is the cursor that reaches the next page, the answer's
   root ``max_id``, and ``None`` where the answer carries none.
   """

   sections: tuple[ExploreSection, ...]
   more_available: bool
   end_cursor: str | None = None

   @property
   def posts(self) -> tuple[Post, ...]:
      """Every post of every section, each section's featured posts before its others."""

      return tuple(
         post for section in self.sections for post in (*section.featured, *section.posts)
      )


@dataclass(frozen=True)
class AudioPage:
   """One page of an audio's page, the ``/reels/audio/<id>/`` page: the track and the reels that
   use it, in the upstream's order.

   ``audio`` is the track as :class:`~dumpstagram.models.MediaAudio` describes it on a reel, a
   song or an original sound. It is ``None`` where the upstream sends no description of the
   track, which every later page of the licensed song read did, while the original sound's later
   page repeated it. ``clips_count`` is the upstream's ``media_count.clips_count`` as sent: the
   number of reels using the track on a first page, and 0 on every later page of the song read,
   where the upstream no longer counts, so only a first page's is a count. ``is_restricted`` is
   the upstream's flag that the audio's page is restricted, false on every answer read.

   ``clips`` are the reels on the page, each a :class:`~dumpstagram.models.Post`. ``more_available``
   is the upstream's own flag and the only thing that ends a walk (W116). It can say true on a
   page whose next page is empty: a one-reel original sound said true and its next page carried
   no reels and said false, in the browser and on both engine replays. ``end_cursor`` is the
   cursor that reaches the next page, ``None`` where the answer carries none, as the last page
   did.
   """

   audio: MediaAudio | None
   clips_count: int
   is_restricted: bool
   clips: tuple[Post, ...]
   more_available: bool
   end_cursor: str | None = None


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
