"""Read only. Not yet run. Ten requests, and up to four more, conditional.

E2 batch 9, the two page models: the post page and the inbox load. Most of the inbox load's
companions are verified findings already, and the post page document itself has never been
captured, so this replays only the companions of either load that no finding backs yet, each
twice. The page documents and the burst order are the browser capture this batch waits for.

   1  the inbox document, for fresh tokens (the bootstrap)
   2  the home timeline's first page, a verified read, for one post
   3  the post page's first comments, PolarisPostCommentsContainerQuery, twice
   5  the post page's liked by line, PolarisLikedByTextDaisyReduxQuery, twice
   7  whether the inbox shows the ad responses tab, useIGDShouldShowAdResponsesTabQuery, twice
   9  the suggested reels an empty threadline shows, IGDThreadlineContainerQuerySuggestedQuery,
      twice

Conditional: each hypothesis query's first replay sent once more on the other GraphQL path
when every root is null, four at most. Nothing here is visible to another person, and
``news/inbox_seen``, the one side effect of a real inbox load, is not sent.

Run it from `engine/` with:

   uv run python probes/e2_page_models.py
"""

from __future__ import annotations

import asyncio
import sys

from _e2_support import E2Replay, dig, page_info_of, run_probe

from dumpstagram._private.web.bootstrap import ORIGIN
from dumpstagram._private.web.requests.feed import build_feed_page_request

PLANNED = 10
CONDITIONAL = 4
INBOX = f"{ORIGIN}/direct/inbox/"


async def body(replay: E2Replay) -> None:
   await replay.bootstrap()

   feed = await replay.engine_read(
      "home timeline first page", build_feed_page_request(replay.session)
   )
   edges = dig(feed, "data", "xdt_api__v1__feed__timeline__connection", "edges") or []
   posts = [dig(edge, "node", "media") for edge in edges]
   posts = [
      post for post in posts if isinstance(post, dict) and post.get("pk") and post.get("code")
   ]

   if posts:
      post_pk = str(posts[0]["pk"])
      post_page = f"{ORIGIN}/p/{posts[0]['code']}/"

      for attempt in (1, 2):
         first_comments = await replay.graphql(
            "read-a-post-page-first-comments",
            {
               "after": None,
               "before": None,
               "media_id": post_pk,
               "first": 10,
               "last": None,
               "__relay_internal__pv__PolarisIsLoggedInrelayprovider": True,
            },
            referer=post_page,
            label=f"post page first comments {attempt}",
            try_other_path_on_null=attempt == 1,
         )
         connection = dig(
            first_comments, "data", "xdt_api__v1__media__media_id__comments__connection"
         )
         replay.record(f"first_comments_{attempt}", page_info_of(connection))

      for attempt in (1, 2):
         liked_by = await replay.graphql(
            "read-the-liked-by-line",
            {"mediaId": post_pk},
            referer=post_page,
            label=f"liked by line {attempt}",
            try_other_path_on_null=attempt == 1,
         )

         if liked_by is not None:
            replay.shape("liked_by_line", dig(liked_by, "data"))
   else:
      replay.record("post_page", "skipped, no post with a shortcode on the timeline's first page")

   for attempt in (1, 2):
      tab = await replay.graphql(
         "read-whether-the-ad-responses-tab-shows",
         {},
         referer=INBOX,
         label=f"ad responses tab {attempt}",
         try_other_path_on_null=attempt == 1,
      )

      if tab is not None:
         replay.shape("ad_responses_tab", dig(tab, "data"))

   for attempt in (1, 2):
      suggested = await replay.graphql(
         "read-suggested-threads-reels",
         {"__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": False},
         referer=INBOX,
         label=f"suggested threadline reels {attempt}",
         try_other_path_on_null=attempt == 1,
      )

      if suggested is not None:
         replay.shape("suggested_threadline_reels", dig(suggested, "data"))


if __name__ == "__main__":
   sys.exit(asyncio.run(run_probe("e2-page-models", PLANNED, CONDITIONAL, body)))
