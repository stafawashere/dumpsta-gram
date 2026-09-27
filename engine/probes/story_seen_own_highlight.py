"""WRITE. Marks one item of the owner's own highlight seen. Four requests.

The engine replay of PolarisStoriesV3SeenMutation that W42 wanted before any story is marked
seen, on content only the owner can see a viewer list for, so no other person is shown as a
viewer (W68). The variables are the five the browser sent on 2026-09-27 when the owner opened
his own highlight, run-2026-09-27-135628: reelId, reelMediaId, reelMediaOwnerId,
reelMediaTakenAt and viewSeenAt, the last in seconds. Every value comes from the highlight read
except viewSeenAt, the time of viewing.

   1  the inbox document, for fresh tokens (the bootstrap)
   2  the owner's highlights tray, for the first highlight's id
   3  that highlight, PolarisStoriesV3ReelPageStandaloneQuery, for its second item
   4  PolarisStoriesV3SeenMutation on that item, once

A highlight's read carries no seen field (W70), so the mutation's answer, a non-null
xdt_mark_story_reel_seen of type XDTMarkSeenResponse, is the only confirmation there is. Only
counts, types and four character id prefixes reach the log.

Run it from `engine/` with:

   uv run python probes/story_seen_own_highlight.py
"""

from __future__ import annotations

import asyncio
import sys
import time

from _e2_support import E2Replay, dig, id_prefix, run_probe

from dumpstagram._private.web.bootstrap import ORIGIN
from dumpstagram._private.web.requests.profiles import build_highlight_tray_request
from dumpstagram._private.web.requests.stories import build_highlight_request

PLANNED = 4


async def body(replay: E2Replay) -> None:
   await replay.bootstrap()

   tray = await replay.engine_read(
      "own highlights tray", build_highlight_tray_request(replay.session, replay.viewer_id)
   )
   first = dig(tray, "data", "highlights", "edges", 0, "node", "id")

   if not first:
      replay.record("skipped", "the owner has no highlight")

      return

   highlight_id = str(first)
   answer = await replay.engine_read(
      "own highlight", build_highlight_request(replay.session, highlight_id)
   )
   reel = dig(answer, "data", "xdt_api__v1__feed__reels_media", "reels_media", 0)
   items = dig(reel, "items") or []
   has_a_second_item = len(items) > 1

   if not has_a_second_item:
      replay.record("skipped", "the highlight has fewer than two items")

      return

   item = items[1]
   variables = {
      "reelId": str(dig(reel, "id")),
      "reelMediaId": str(dig(item, "pk")),
      "reelMediaOwnerId": str(dig(item, "user", "pk") or replay.viewer_id),
      "reelMediaTakenAt": int(dig(item, "taken_at")),
      "viewSeenAt": int(time.time()),
   }
   replay.record(
      "variables",
      {key: (type(value).__name__, id_prefix(value)) for key, value in variables.items()},
   )
   seen = await replay.graphql(
      "mark-a-story-seen",
      variables,
      referer=f"{ORIGIN}/stories/highlights/{highlight_id.removeprefix('highlight:')}/",
      label="seen mutation",
   )
   replay.record(
      "answer",
      {"typename": dig(seen, "data", "xdt_mark_story_reel_seen", "__typename")},
   )


if __name__ == "__main__":
   sys.exit(asyncio.run(run_probe("story-seen-own-highlight", PLANNED, 0, body)))
