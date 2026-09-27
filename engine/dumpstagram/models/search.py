"""Typed representations of the search reads: the recent searches, a hashtag's header, the
search box's blended results and the keyword grid.

Every field below was observed on the answers ``probes/e2_search.py`` kept on 2026-09-27, run
``run-2026-09-27-014102``: the recent searches read twice with 15 entries each, the
non-personalised typeahead read twice with 18 accounts each, and a hashtag's header read twice.
The typeahead's rows are :class:`~dumpstagram.models.ProfileSummary` and need no model here.

The blended results and the keyword grid were added for E2 batch 11b from the answers
``probes/e2_capture_replays.py --stage search`` kept on 2026-09-27, run ``run-2026-09-27-151121``:
the personalised typeahead read twice, 5 accounts and 1 keyword each, and the keyword grid read
twice, 48 posts over 16 grid rows.

Nothing here parses. Construction is done by the mappers in ``_private/web/parse/search.py``,
which read named keys and raise rather than filling a default, so an upstream rename is loud.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from dumpstagram.models.feed import MediaImage, PostAuthor, VideoRendition
from dumpstagram.models.profiles import ProfileSummary

__all__ = [
   "Hashtag",
   "KeywordResults",
   "RecentSearch",
   "RecentSearchKind",
   "SearchPost",
   "SearchResult",
   "SearchResultKind",
   "SearchResults",
]


class RecentSearchKind(StrEnum):
   """Which of a recent search's four slots the upstream filled.

   The upstream sends every entry as one object with four sibling slots, of which exactly one
   was non-null on all 30 entries read. The values are the slot names. Accounts and keywords
   were seen filled; hashtags and places are declared by the upstream and were null on every
   entry read (W82).
   """

   ACCOUNT = "user"
   KEYWORD = "keyword"
   HASHTAG = "hashtag"
   PLACE = "place"


@dataclass(frozen=True)
class RecentSearch:
   """One entry of the viewer's recent searches, in the upstream's order.

   ``account`` is set when and only when :attr:`kind` is :attr:`RecentSearchKind.ACCOUNT`, and
   ``keyword`` when it is :attr:`RecentSearchKind.KEYWORD`, the text that was searched. A hashtag
   or a place entry is reported by its kind and carries no payload, because neither shape has
   been read (W82). An account row carries no relationship to the viewer and no ``is_private``.
   """

   kind: RecentSearchKind
   account: ProfileSummary | None = None
   keyword: str | None = None


@dataclass(frozen=True)
class Hashtag:
   """A hashtag's header.

   ``id`` is the upstream's id for the tag, the one field its answer carried. ``name`` is the tag
   the header was asked for, as it was sent, without the ``#`` (W84).
   """

   id: str
   name: str


class SearchResultKind(StrEnum):
   """Which of the search box's lists one result came from.

   The personalised typeahead answers four sibling lists, ``users``, ``hashtags``, ``places`` and
   the keyword suggestions under ``see_more``. Accounts and keywords were seen filled; hashtags
   and places were empty lists on both answers read (W102).
   """

   ACCOUNT = "user"
   KEYWORD = "keyword"
   HASHTAG = "hashtag"
   PLACE = "place"


@dataclass(frozen=True)
class SearchResult:
   """One row the search box shows for a query.

   ``account`` is set when and only when :attr:`kind` is :attr:`SearchResultKind.ACCOUNT`, and
   ``keyword`` when it is :attr:`SearchResultKind.KEYWORD`, the suggested search text, which
   :meth:`~dumpstagram.namespaces.search.AsyncSearch.keyword` reads the grid of. A hashtag or a
   place row is reported by its kind with no payload, because neither shape has been read.

   ``position`` is the upstream's own place for the row in the blended list, 0 for the keyword and
   1 to 5 for the accounts on both answers read. It is ``None`` on a hashtag or a place row, and on
   every row of the non-personalised route, which sends none. An account row carries no
   relationship to the viewer and no ``is_private``.
   """

   kind: SearchResultKind
   position: int | None = None
   account: ProfileSummary | None = None
   keyword: str | None = None


@dataclass(frozen=True)
class SearchResults:
   """What the search box offers for one query, in the order it shows them.

   ``results`` holds the rows that carry a ``position`` in that position's order, then any
   hashtag and place rows in the upstream's order. The list is whole as sent, with nothing to
   page on.
   """

   results: tuple[SearchResult, ...]


@dataclass(frozen=True)
class SearchPost:
   """One post of the keyword grid, as the grid carries it.

   The grid's post is lighter than a timeline :class:`~dumpstagram.models.Post`: it carries no
   ``product_type``, no viewer state such as ``has_liked`` or ``is_seen``, no audio, no location
   and no tags, and its slides carry no kind of their own, so it is its own model rather than a
   ``Post`` with guesses in it. :meth:`~dumpstagram.namespaces.media.AsyncMedia.by_code` with its
   ``code`` reads the whole post.

   ``id`` is ``"<pk>_<author id>"`` as on a ``Post``. ``author`` carries the account that posted it
   with ``hd_profile_pic_url``, ``is_following`` and ``is_favorite`` ``None``, since the grid
   sends none of them. ``media_type`` is the upstream's enumeration, ``1``, ``2`` and ``8`` seen
   for a photo, a video and a carousel. ``carousel_media_count`` is the number of slides and
   ``None`` on anything else; the slides themselves are not carried.

   ``videos`` and ``video_duration`` are a video's renditions and its length read from the DASH
   manifest, as on a ``Post``, and empty and ``None`` on anything else. ``has_audio`` is the
   upstream's flag on a video and ``None`` elsewhere. ``view_count`` was set on 4 of the 48
   posts read and null on the rest, and reads as ``None`` where null.
   """

   id: str
   pk: str
   code: str
   taken_at: datetime
   author: PostAuthor
   media_type: int
   like_count: int
   comment_count: int
   like_and_view_counts_disabled: bool
   caption: str | None = None
   accessibility_caption: str | None = None
   original_width: int | None = None
   original_height: int | None = None
   carousel_media_count: int | None = None
   images: tuple[MediaImage, ...] = ()
   videos: tuple[VideoRendition, ...] = ()
   video_duration: float | None = None
   has_audio: bool | None = None
   view_count: int | None = None


@dataclass(frozen=True)
class KeywordResults:
   """The first page of the grid a keyword search shows, which is also a hashtag's page.

   ``posts`` holds every post of the grid's rows in the upstream's order. The page's header rows
   and its accounts row carried nothing but their kind on every answer read, so they are not
   carried. ``has_more`` is the upstream's own flag that the grid goes on; no later page has been
   read, so there is no cursor (W103).
   """

   posts: tuple[SearchPost, ...]
   has_more: bool
