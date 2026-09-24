"""Read only. Not yet run. Twelve requests, and up to four more, conditional.

E2 batch 2, the profile tabs read over GraphQL, on the owner's own account: the posts grid past
its first page, the highlights tray past its first page, and the two suggested account lists.
Each hypothesis read is replayed twice.

   1  the inbox document, for fresh tokens (the bootstrap)
   2  the owner's profile by id, a verified read, for the username the grid is keyed on
   3  the posts grid's first page, the verified PolarisProfilePostsQuery at the page's twelve
   4  the posts grid's next page, PolarisProfilePostsTabContentQuery_connection, twice
   6  the highlights tray's first page, the verified PolarisProfileStoryHighlightsTrayContentQuery
   7  the highlights tray's next page, ProfileStoryHighlightsTrayContentQuery_connection, twice
   9  the accounts suggested beside the profile, PolarisProfileSuggestedUsersWithLazyQueryQuery,
      twice
  11  the suggested accounts list, PolarisSuggestedUserListQuery, twice

Steps 4 and 5 run only when the grid has a second page, and steps 7 and 8 only when the tray
does, so a small account spends up to four fewer. Conditional: each hypothesis query's first
replay is sent once more on the other GraphQL path when every root is null, four at most.

Everything read is the owner's own or offered to the owner, and nothing is visible to another
person. The username, ids and every item's content stay out of the log.

Run it from `engine/` with:

   uv run python probes/e2_profile_tabs.py
"""

from __future__ import annotations

import asyncio
import sys

from _e2_support import E2Replay, dig, id_prefix, page_info_of, run_probe

from dumpstagram._private.web.bootstrap import ORIGIN
from dumpstagram._private.web.documents.profiles import PROFILE_HIGHLIGHTS, PROFILE_POSTS
from dumpstagram._private.web.parse.profiles import parse_profile
from dumpstagram._private.web.requests.common import build_graphql_request
from dumpstagram._private.web.requests.profiles import (
   _profile_posts_variables,
   build_profile_request,
)

PLANNED = 12
CONDITIONAL = 4
GRID_PAGE_SIZE = 12


async def body(replay: E2Replay) -> None:
   await replay.bootstrap()

   viewer_id = replay.viewer_id
   profile_payload = await replay.engine_read(
      "own profile by id", build_profile_request(replay.session, viewer_id)
   )
   username = parse_profile(profile_payload).username if profile_payload else None

   if username is None:
      replay.record("skipped", "the own profile read gave no username, so no grid was read")

      return

   profile_page = f"{ORIGIN}/{username}/"
   first_grid = await replay.engine_read(
      "posts grid first page",
      build_graphql_request(
         replay.session,
         PROFILE_POSTS,
         _profile_posts_variables(username, GRID_PAGE_SIZE),
         referer=profile_page,
         user_agent=replay.user_agent,
      ),
   )
   grid = dig(first_grid, "data", "xdt_api__v1__feed__user_timeline_graphql_connection")
   replay.record("grid_first_page", page_info_of(grid))
   grid_cursor = dig(grid, "page_info", "end_cursor")
   grid_has_more = bool(dig(grid, "page_info", "has_next_page")) and grid_cursor

   if grid_has_more:
      grid_variables = dict(PROFILE_POSTS_TEMPLATE)
      grid_variables.update({"after": grid_cursor, "username": username})

      for attempt in (1, 2):
         page = await replay.graphql(
            "profile-posts-grid-next-page",
            grid_variables,
            referer=profile_page,
            label=f"posts grid next page {attempt}",
            try_other_path_on_null=attempt == 1,
         )
         connection = dig(page, "data", "xdt_api__v1__feed__user_timeline_graphql_connection")
         first_node = dig(connection, "edges", 0, "node")
         replay.record(
            f"grid_next_page_{attempt}",
            page_info_of(connection) | {"first_item_prefix": id_prefix(dig(first_node, "pk"))},
         )

         if page is not None:
            replay.shape("posts_grid_next_page", connection)

   first_tray = await replay.engine_read(
      "highlights tray first page",
      build_graphql_request(
         replay.session,
         PROFILE_HIGHLIGHTS,
         {"user_id": viewer_id},
         referer=profile_page,
         user_agent=replay.user_agent,
      ),
   )
   tray = dig(first_tray, "data", "highlights")
   replay.record(
      "tray_first_page", page_info_of(tray) | {"roots": sorted(dig(first_tray, "data") or {})}
   )
   tray_cursor = dig(tray, "page_info", "end_cursor")
   tray_has_more = bool(dig(tray, "page_info", "has_next_page")) and tray_cursor

   if tray_has_more:
      tray_variables = {
         "after": tray_cursor,
         "before": None,
         "first": 12,
         "last": None,
         "max_highlights_to_fetch_on_pagination": 12,
         "user_id": viewer_id,
      }

      for attempt in (1, 2):
         page = await replay.graphql(
            "profile-highlights-tray-next-page",
            tray_variables,
            referer=profile_page,
            label=f"highlights tray next page {attempt}",
            try_other_path_on_null=attempt == 1,
         )

         if page is not None:
            replay.shape("highlights_tray_next_page", dig(page, "data"))

   for attempt in (1, 2):
      chaining = await replay.graphql(
         "profile-suggested-users-on-demand",
         {"module": "profile", "target_id": viewer_id},
         referer=profile_page,
         label=f"suggested beside the profile {attempt}",
         try_other_path_on_null=attempt == 1,
      )
      users = dig(chaining, "data", "xdt_api__v1__discover__chaining", "users") or []
      replay.record(f"chaining_{attempt}", {"users": len(users)})

      if chaining is not None:
         replay.shape("suggested_beside_profile", dig(chaining, "data"))

   suggested_variables = {
      "data": {
         "max_id": "",
         "max_number_to_display": 5,
         "module": "discover_people",
         "paginate": True,
      }
   }

   for attempt in (1, 2):
      suggested = await replay.graphql(
         "home-suggested-accounts",
         suggested_variables,
         referer=f"{ORIGIN}/",
         label=f"suggested accounts {attempt}",
         try_other_path_on_null=attempt == 1,
      )

      if suggested is not None:
         replay.shape("suggested_accounts", dig(suggested, "data"))


PROFILE_POSTS_TEMPLATE = {
   "after": None,
   "before": None,
   "data": {
      "count": GRID_PAGE_SIZE,
      "include_reel_media_seen_timestamp": True,
      "include_relationship_info": True,
      "latest_besties_reel_media": True,
      "latest_reel_media": True,
   },
   "first": GRID_PAGE_SIZE,
   "include_multi_captions": True,
   "last": None,
   "username": None,
   "__relay_internal__pv__PolarisMultiCaptionCarouselEnabledrelayprovider": True,
   "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": False,
   "__relay_internal__pv__PolarisReelsRecoDebugOverlayEnabledrelayprovider": False,
}
"""The next page's variables, the verified first page's plus the connection arguments.

``first`` and ``include_multi_captions`` are not observed on this query, see the finding
``profile-posts-grid-next-page``.
"""


if __name__ == "__main__":
   sys.exit(asyncio.run(run_probe("e2-profile-tabs", PLANNED, CONDITIONAL, body)))
