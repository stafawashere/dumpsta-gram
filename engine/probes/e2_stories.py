"""Read only. Not yet run. Eight requests, and up to four more, conditional.

E2 batch 5, stories, read without marking anything seen. The story reads are the owner's own:
his highlights, and his own reel, which is empty unless he has a live story. The stories tray
is read for its shape only.

   1  the inbox document, for fresh tokens (the bootstrap)
   2  the stories tray, the verified PolarisStoriesV3TrayContainerQuery
   3  the owner's highlights tray, the verified PolarisProfileStoryHighlightsTrayContentQuery
   4  the owner's first highlight, PolarisStoriesV3ReelPageStandaloneQuery with is_highlight,
      twice
   6  the owner's own reel, PolarisStoriesV3ReelPageStandaloneQuery, once
   7  the stories gallery over the owner's highlights, PolarisStoriesV3ReelPageGalleryQuery,
      twice

Steps 4, 5, 7 and 8 are skipped when the owner has no highlight. Conditional: each hypothesis
query's first replay sent once more on the other GraphQL path when every root is null, two at
most, and, only with ``--third-party-reel``, the first tray reel of another account read twice
with the standalone query.

No seen mutation is ever sent, here or behind the flag. PolarisStoriesV3SeenMutation is what
puts a viewer in a story's seen list, and the story reads themselves mark nothing (INFERENCE:
the browser sends that mutation separately for each item it shows, which would be redundant if
the read had marked it). Under W42 the flag is the only
way this probe reads another person's story, and it stays off unless the orchestrator names it
for a run. Nothing from a story is logged but key unions, counts and the reel type.

Run it from `engine/` with:

   uv run python probes/e2_stories.py
   uv run python probes/e2_stories.py --third-party-reel
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from _e2_support import E2Replay, dig, read_hypothesis, run_probe

from dumpstagram._private.web.bootstrap import ORIGIN

PLANNED = 8
CONDITIONAL = 4
COMMUNITY_NOTE = {
   "__relay_internal__pv__PolarisCommunityNoteStoriesLabelEnabledrelayprovider": True
}
REELS_MEDIA_ROOT = "xdt_api__v1__feed__reels_media"
GALLERY_ROOT = "xdt_api__v1__feed__reels_media__connection"


def describe_reels(answer: object) -> dict[str, object]:
   reels = dig(answer, "data", REELS_MEDIA_ROOT, "reels_media") or []

   return {
      "reels": len(reels),
      "items": [len(reel.get("items") or []) for reel in reels if isinstance(reel, dict)],
      "reel_types": sorted(
         {str(reel.get("reel_type")) for reel in reels if isinstance(reel, dict)}
      ),
   }


async def body(replay: E2Replay, third_party_reel: bool) -> None:
   await replay.bootstrap()

   tray_template = read_hypothesis("page-load-stories-tray").template or {}
   tray = await replay.graphql("page-load-stories-tray", tray_template, referer=f"{ORIGIN}/")
   tray_reels = dig(tray, "data", "xdt_api__v1__feed__reels_tray", "tray") or []
   replay.record("tray", {"reels": len(tray_reels)})

   if tray is not None:
      replay.shape("stories_tray_reel", tray_reels[:5])

   viewer_id = replay.viewer_id
   highlights = await replay.graphql(
      "profile-page-story-highlights", {"user_id": viewer_id}, referer=f"{ORIGIN}/"
   )
   highlight_edges = dig(highlights, "data", "highlights", "edges") or []
   highlight_ids = [
      str(dig(edge, "node", "id")) for edge in highlight_edges if dig(edge, "node", "id")
   ]
   replay.record("highlights", {"count": len(highlight_ids)})

   if highlight_ids:
      for attempt in (1, 2):
         answer = await replay.graphql(
            "read-one-account-s-stories-or-a-highlight",
            {"reel_ids_arr": [highlight_ids[0]], "is_highlight": True, **COMMUNITY_NOTE},
            referer=f"{ORIGIN}/",
            label=f"own highlight {attempt}",
            try_other_path_on_null=attempt == 1,
         )
         replay.record(f"own_highlight_{attempt}", describe_reels(answer))

         if answer is not None:
            replay.shape("highlight_reel", dig(answer, "data", REELS_MEDIA_ROOT))

   own_reel = await replay.graphql(
      "read-one-account-s-stories-or-a-highlight",
      {"reel_ids_arr": [viewer_id], **COMMUNITY_NOTE},
      referer=f"{ORIGIN}/",
      label="own reel",
   )
   replay.record("own_reel", describe_reels(own_reel))

   if highlight_ids:
      gallery_ids = highlight_ids[:3]

      for attempt in (1, 2):
         gallery = await replay.graphql(
            "read-the-stories-gallery",
            {
               "first": 3,
               "initial_reel_id": gallery_ids[0],
               "is_highlight": True,
               "last": 2,
               "reel_ids": gallery_ids,
               **COMMUNITY_NOTE,
            },
            referer=f"{ORIGIN}/",
            label=f"highlights gallery {attempt}",
            try_other_path_on_null=attempt == 1,
         )
         connection = dig(gallery, "data", GALLERY_ROOT)
         replay.record(f"gallery_{attempt}", {"edges": len(dig(connection, "edges") or [])})

         if gallery is not None:
            replay.shape("stories_gallery", connection)

   if not third_party_reel:
      replay.record("third_party_reel", "not read, the flag was not given")

      return

   owners = [str(dig(reel, "user", "pk") or dig(reel, "id") or "") for reel in tray_reels]
   others = [owner for owner in owners if owner and owner != viewer_id]

   if not others:
      replay.record("third_party_reel", "no other account's reel in the tray")

      return

   for attempt in (1, 2):
      answer = await replay.graphql(
         "read-one-account-s-stories-or-a-highlight",
         {"reel_ids_arr": [others[0]], **COMMUNITY_NOTE},
         referer=f"{ORIGIN}/",
         label=f"third party reel {attempt}, read only, no seen mutation",
      )
      replay.record(f"third_party_reel_{attempt}", describe_reels(answer))

      if answer is not None:
         replay.shape("third_party_reel", dig(answer, "data", REELS_MEDIA_ROOT))


if __name__ == "__main__":
   parser = argparse.ArgumentParser()
   parser.add_argument("--third-party-reel", action="store_true")
   arguments = parser.parse_args()

   async def selected(replay: E2Replay) -> None:
      await body(replay, arguments.third_party_reel)

   sys.exit(asyncio.run(run_probe("e2-stories", PLANNED, CONDITIONAL, selected)))
