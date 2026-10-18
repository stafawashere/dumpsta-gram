"""The awaitable surface: the same capabilities and models as the blocking client, awaited.

Live requests: 1 for the own profile, the feed's first page (about 6 under parity, 1 with
--quick), and 1 more when the iterator crosses into a second page.

   uv run python docs/demo/async_surface.py --quick
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from _common import Demo, build_parser, line, run, show_profile

from dumpstagram import FeedItemKind


async def read(demo: Demo, limit: int) -> None:
   async with demo.async_client() as client:
      demo.tour.section(
         "Awaited read",
         "async with AsyncClient(session) as client:",
         "...     await client.profiles.by_id(client.session.ds_user_id)",
      )

      show_profile(await client.profiles.by_id(client.session.ds_user_id))

      demo.tour.section(
         "Async iterator",
         f"async for item in client.feeds.iter_home(limit={limit}): ...",
      )

      post_count = 0
      item_count = 0

      async for item in client.feeds.iter_home(limit=limit):
         item_count += 1
         is_post = item.kind is FeedItemKind.POST

         if is_post and item.post is not None:
            post_count += 1

      line(f"{item_count} feed items, {post_count} of them posts")
      demo.report["async_feed_items"] = item_count


def tour(demo: Demo, arguments: argparse.Namespace) -> None:
   asyncio.run(read(demo, arguments.limit))


if __name__ == "__main__":
   parser = build_parser("The same reads through AsyncClient.")
   parser.add_argument("--limit", type=int, default=10, help="feed items the iterator walks")

   sys.exit(run("async", parser, tour))
