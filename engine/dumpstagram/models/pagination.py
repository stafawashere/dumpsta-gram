"""The paged result every read capability returns.

One shape for every connection the upstream exposes, because they all page the same way:
a list of items, a boolean saying whether more exist, and an opaque cursor to pass back.

The boolean is the only terminator. A short page is not the end of a connection, an empty
page is not the end of a connection, and a count the upstream reports elsewhere is a claim
rather than a fact. That rule is inherited from a measured defect and is restated in
`engine/docs/architecture.md` as an invariant.

``end_cursor`` is opaque. It was 132 characters on every measured run, and nothing may depend
on that, on its alphabet, or on it being comparable to another cursor.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

__all__ = ["Page"]


@dataclass(frozen=True)
class Page[ItemT]:
   """One page of a connection, with the cursor that reaches the next one.

   ``items`` is a tuple rather than a list because the model is frozen and a frozen
   dataclass holding a list is immutable in name only.
   """

   items: tuple[ItemT, ...]
   has_next_page: bool
   end_cursor: str | None = None

   def __iter__(self) -> Iterator[ItemT]:
      return iter(self.items)
