"""Read only. Three requests.

Why ``stories.reel`` raised ``SchemaChanged`` on 2026-09-27 at ``reels_media[0].title``: a live
reel of another account was read for the first time (W70 had assumed its items share a
highlight's shape). Reads the reel twice with the read query alone and never the seen mutation,
so nobody is shown a viewer (W42, W43), and keeps both answers under the skill's captures for a
fixture. The account id is the one argument, taken from the stories tray, and never the W30
partner. Only key unions and counts reach the log.

   1  the inbox document, for fresh tokens (the bootstrap)
   2  the account's live reel, PolarisStoriesV3ReelPageStandaloneQuery, twice

Run it from `engine/` with:

   uv run python probes/live_reel_shape.py USER_ID
"""

from __future__ import annotations

import asyncio
import sys

from _e2_support import E2Replay, dig, run_probe

from dumpstagram._private.web.requests.stories import build_story_reel_request

PLANNED = 3


def body_for(user_id: str):
   async def body(replay: E2Replay) -> None:
      await replay.bootstrap()

      for attempt in (1, 2):
         answer = await replay.engine_read(
            f"live reel {attempt}", build_story_reel_request(replay.session, user_id)
         )
         reel = dig(answer, "data", "xdt_api__v1__feed__reels_media", "reels_media", 0)
         items = dig(reel, "items") or []
         replay.record(
            f"reel_{attempt}",
            {"items": len(items), "title_type": type(dig(reel, "title")).__name__},
         )

         if reel is not None:
            replay.shape("live_reel", reel)

   return body


if __name__ == "__main__":
   sys.exit(asyncio.run(run_probe("live-reel-shape", PLANNED, 0, body_for(sys.argv[1]))))
