"""Typed representations of the search reads: the recent searches and a hashtag's header.

Every field below was observed on the answers ``probes/e2_search.py`` kept on 2026-09-27, run
``run-2026-09-27-014102``: the recent searches read twice with 15 entries each, the
non-personalised typeahead read twice with 18 accounts each, and a hashtag's header read twice.
The typeahead's rows are :class:`~dumpstagram.models.ProfileSummary` and need no model here.

Nothing here parses. Construction is done by the mappers in ``_private/web/parse/search.py``,
which read named keys and raise rather than filling a default, so an upstream rename is loud.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from dumpstagram.models.profiles import ProfileSummary

__all__ = [
   "Hashtag",
   "RecentSearch",
   "RecentSearchKind",
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
