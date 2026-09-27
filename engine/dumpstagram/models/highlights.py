"""Typed representations of a profile's story highlights tray.

Every field below was observed on the tray ``PolarisProfileStoryHighlightsTrayContentQuery``
answered on 2026-09-27, the owner's tray with one highlight read five times and a public
account's with none, recorded under the finding ``profile-page-story-highlights``.

Nothing here parses. Construction is done by the mapper in ``_private/web/parse/profiles.py``,
which reads named keys and raises rather than filling a default, so an upstream rename is loud.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Highlight", "HighlightTray"]


@dataclass(frozen=True)
class Highlight:
   """One highlight in a profile's tray, as the tray shows it: its title and its cover.

   ``id`` is the upstream's own, which reads ``highlight:`` and a number. ``owner_id`` is the
   numeric account id of the profile the tray belongs to. Reading the stories inside a highlight
   is not part of this read.
   """

   id: str
   title: str
   cover_url: str
   owner_id: str
   owner_username: str


@dataclass(frozen=True)
class HighlightTray:
   """A profile's highlights, the tray's first page.

   ``has_more`` is the upstream's own ``has_next_page``. The query that reads further has never
   answered a replay, since no tray read so far had a second page, so a true ``has_more`` says
   ``highlights`` is not the whole tray and nothing here can read the rest.
   """

   highlights: tuple[Highlight, ...]
   has_more: bool
