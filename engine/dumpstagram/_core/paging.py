"""Walking a paged read one page at a time, for the ``iter_*`` methods on the namespaces.

Each page is read by the namespace's own page method, so it departs through the paced sender
exactly as a single read does, and the next page is not asked for until the caller has taken
every item of the one before it. Nothing is fetched ahead and nothing runs concurrently, per
ADR-0001, which is also why an iterator abandoned halfway leaves no request in flight.

``has_next_page`` is the only terminator. An empty or short page with ``has_next_page`` true
is followed like any other. ``limit`` counts items, ruling W23 in
``docs/web-parity-plan.md``: the walk ends once that many have been yielded, before asking for
a page it would not use, and ``None`` walks until the upstream says there is nothing more.

The decisions live in :class:`PageWalk`, which both surfaces share, so the awaitable walk and
the blocking one differ only in how a page is read.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

from dumpstagram.errors import SchemaChanged
from dumpstagram.models import Page

__all__ = ["PageWalk", "check_limit", "iterate_pages", "iterate_pages_blocking"]


def check_limit(limit: int | None) -> None:
   """Refuse a ``limit`` that is not a count of items, before anything is sent."""

   if limit is None:
      return

   is_a_count = isinstance(limit, int) and not isinstance(limit, bool)

   if not is_a_count:
      raise TypeError(f"limit is a number of items or None, not {type(limit).__name__}")

   if limit < 0:
      raise ValueError("limit cannot be negative, zero yields nothing and None reads to the end")


def cursor_after(page: Page[object]) -> str:
   """The cursor that reaches the page after ``page``, which has said one exists."""

   if page.end_cursor is None:
      raise SchemaChanged(
         "a page said more exist and carried no cursor to reach them",
         path="page_info.end_cursor",
      )

   return page.end_cursor


class PageWalk:
   """Where one walk stands: the cursor for the next page, the items it may still yield, and
   whether the upstream has said there is nothing more."""

   def __init__(self, *, limit: int | None, after: str | None) -> None:
      self.cursor = after
      self.remaining = limit
      self.finished = False

   @property
   def wants_a_page(self) -> bool:
      limit_reached = self.remaining == 0

      return not self.finished and not limit_reached

   def take[ItemT](self, page: Page[ItemT]) -> Iterator[ItemT]:
      for item in page.items:
         if self.remaining == 0:
            return

         if self.remaining is not None:
            self.remaining -= 1

         yield item

   def advance(self, page: Page[object]) -> None:
      limit_reached = self.remaining == 0
      has_no_next_page = not page.has_next_page

      if limit_reached or has_no_next_page:
         self.finished = True

         return

      self.cursor = cursor_after(page)


async def iterate_pages[ItemT](
   read_page: Callable[[str | None], Awaitable[Page[ItemT]]],
   *,
   limit: int | None,
   after: str | None,
) -> AsyncIterator[ItemT]:
   walk = PageWalk(limit=limit, after=after)

   while walk.wants_a_page:
      page = await read_page(walk.cursor)

      for item in walk.take(page):
         yield item

      walk.advance(page)


def iterate_pages_blocking[ItemT](
   read_page: Callable[[str | None], Page[ItemT]],
   *,
   limit: int | None,
   after: str | None,
) -> Iterator[ItemT]:
   walk = PageWalk(limit=limit, after=after)

   while walk.wants_a_page:
      page = read_page(walk.cursor)

      yield from walk.take(page)

      walk.advance(page)
