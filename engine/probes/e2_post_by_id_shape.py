"""Read only. Four requests at most.

Why ``media.by_id`` raised ``SchemaChanged`` on a video post in the E2 batch 4 acceptance of
2026-09-27, when its fixtures were a carousel. Reads the home timeline's first page, a verified
read, then each of its first two video posts by media pk, and logs where the mapper refused, as a
path of field names, never a value. Each answer is kept under the skill's captures for fixtures.

   1  the inbox document, for fresh tokens (the bootstrap)
   2  the home timeline's first page, PolarisFeedRootPaginationCachedQuery
   3  up to two video posts by media pk, PolarisPostActionLoadPostQueryMediaIdQuery

Run it from `engine/` with:

   uv run python probes/e2_post_by_id_shape.py
"""

from __future__ import annotations

import asyncio
import sys

from _e2_support import E2Replay, dig, id_prefix, run_probe

from dumpstagram._private.web.parse.media import parse_post_by_media_id
from dumpstagram._private.web.requests.feed import build_feed_page_request
from dumpstagram._private.web.requests.media import build_post_by_id_request
from dumpstagram.errors import SchemaChanged

PLANNED = 4
VIDEO = 2


async def body(replay: E2Replay) -> None:
   await replay.bootstrap()

   feed = await replay.engine_read(
      "home timeline first page", build_feed_page_request(replay.session)
   )
   edges = dig(feed, "data", "xdt_api__v1__feed__timeline__connection", "edges") or []
   posts = [dig(edge, "node", "media") for edge in edges]
   videos = [post for post in posts if isinstance(post, dict) and post.get("media_type") == VIDEO]
   replay.record("videos_on_the_page", len(videos))

   for index, post in enumerate(videos[:2], start=1):
      answer = await replay.engine_read(
         f"video post by media pk {index}",
         build_post_by_id_request(replay.session, str(post["pk"])),
      )
      outcome: dict[str, object] = {"pk_prefix": id_prefix(post["pk"])}

      try:
         parse_post_by_media_id(answer)
         outcome["mapped"] = True
      except SchemaChanged as failure:
         outcome["mapped"] = False
         outcome["refused_at"] = failure.path

      replay.record(f"video_{index}", outcome)


if __name__ == "__main__":
   sys.exit(asyncio.run(run_probe("e2-post-by-id-shape", PLANNED, 0, body)))
