"""The home feed: a first page, the next page by cursor, and the item iterator after it.

Live requests: about 7 under parity for the two pages, the first read out of the home document
with its page load companions, or 2 with --quick. The iterator adds 1 when a third page exists.

   uv run python docs/demo/feed.py
   uv run python docs/demo/feed.py --quick --limit 20
"""

from __future__ import annotations

import argparse
import sys

from _common import Demo, build_parser, line, preview, run, show_call

from dumpstagram import FeedItem, FeedItemKind, Page


def count_kinds(page: Page[FeedItem]) -> dict[str, int]:
   counts: dict[str, int] = {}

   for item in page:
      counts[item.kind.value] = counts.get(item.kind.value, 0) + 1

   return counts


def show_feed_page(page: Page[FeedItem]) -> None:
   line(f"Page[FeedItem], {len(page.items)} items, has_next_page={page.has_next_page}")

   for item in page:
      post = item.post
      is_post = item.kind is FeedItemKind.POST

      if is_post and post is not None:
         caption = preview(post.caption)
         line(f"@{post.author.username:<18} {post.like_count:>9,} likes  {caption}", depth=2)

   other_counts = {
      kind: count for kind, count in count_kinds(page).items() if kind != FeedItemKind.POST
   }

   if other_counts:
      others = ", ".join(f"{count} {kind}" for kind, count in other_counts.items())
      line(f"plus {others}", depth=2)


def tour(demo: Demo, arguments: argparse.Namespace) -> None:
   with demo.client() as client:
      demo.tour.section("Home feed", "page = client.feeds.home()")

      first_page = client.feeds.home()
      show_feed_page(first_page)
      demo.report["feed_page_one"] = count_kinds(first_page)

      if not first_page.has_next_page:
         return

      print()
      show_call("page = client.feed(after=page.end_cursor)")

      second_page = client.feed(after=first_page.end_cursor)
      show_feed_page(second_page)
      demo.report["feed_page_two"] = count_kinds(second_page)

      if not second_page.has_next_page:
         return

      demo.tour.section(
         "Item iterator",
         f"for item in client.feeds.iter_home(limit={arguments.limit}, after=page.end_cursor):",
      )

      walk = client.feeds.iter_home(limit=arguments.limit, after=second_page.end_cursor)
      walked_kinds = [item.kind.value for item in walk]

      line(f"{len(walked_kinds)} items walked one at a time, pages read only as needed")
      line(", ".join(walked_kinds), depth=2)
      demo.report["feed_iterated_items"] = len(walked_kinds)


if __name__ == "__main__":
   parser = build_parser("Read the home feed by page and by item.")
   parser.add_argument("--limit", type=int, default=5, help="items the iterator walks, default 5")

   sys.exit(run("feed", parser, tour))
