"""Read only. Not yet run. Nine requests, and up to five more, conditional.

E2 batch 7, the discovery feeds whose variables are known: the explore grid over REST, a
location page's header and grid, and the home feed's new posts check. The reels feed carries a
``data`` object that was never observed, and the hashtag grid two session ids, so both wait for
the browser capture the execution list names.

   1  the inbox document, for fresh tokens (the bootstrap)
   2  GET /api/v1/discover/web/explore_grid/ with the five parameters observed once, twice
   4  a location's header, PolarisExploreLocationsContainerQuery, twice
   6  that location's ranked grid, PolarisLocationPageTabContentQuery, twice
   8  whether the home feed has new posts, PolarisAPICheckNewFeedPostsExistQuery, twice

Conditional: the location grid's next page, PolarisLocationPageTabContentQuery_connection,
twice, when the first page has more, and each GraphQL query's first replay sent once more on
the other path when every root is null, three at most. The location is the first one the
explore grid's media carry, or ``IG_E2_LOCATION_ID`` from the root ``.env`` when they carry
none, and steps 4 to 7 are skipped when neither gives one.

Explore, location pages and the new posts check are visible to nobody. No media, caption,
username, location name or id is logged.

Run it from `engine/` with:

   uv run python probes/e2_discovery_feeds.py
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from _e2_support import E2Replay, dig, page_info_of, run_probe
from _probe_support import load_env

from dumpstagram._private.web.bootstrap import ORIGIN

PLANNED = 9
CONDITIONAL = 5
EXPLORE_PARAMETERS = {
   "include_fixed_destinations": "true",
   "is_nonpersonalized_explore": "false",
   "is_prefetch": "false",
   "module": "explore_popular",
   "omit_cover_media": "false",
}
TAB_ROOT = "xdt_location_get_web_info_tab"
SHORT_DRAMA = {"__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": False}


def first_location_pk(value: Any) -> str | None:
   """The first ``location.pk`` anywhere under ``value``, walked in document order."""

   if isinstance(value, dict):
      location = value.get("location")
      is_a_location = isinstance(location, dict) and location.get("pk")

      if is_a_location:
         return str(location["pk"])

      for inner in value.values():
         found = first_location_pk(inner)

         if found:
            return found

   if isinstance(value, list):
      for inner in value:
         found = first_location_pk(inner)

         if found:
            return found

   return None


async def body(replay: E2Replay) -> None:
   await replay.bootstrap()

   explore_url = f"{ORIGIN}/api/v1/discover/web/explore_grid/"
   explore_page = None

   for attempt in (1, 2):
      grid = await replay.rest(
         f"explore grid {attempt}",
         explore_url,
         referer=f"{ORIGIN}/explore/",
         params=EXPLORE_PARAMETERS,
      )
      sections = (grid or {}).get("sectional_items") or []
      replay.record(
         f"explore_{attempt}",
         {"top_keys": sorted(grid or {}), "sections": len(sections)},
      )

      if grid is not None:
         replay.shape(
            "explore_grid", {key: value for key, value in grid.items() if key != "sectional_items"}
         )
         replay.shape("explore_section", sections[:3])
         explore_page = explore_page or grid

   location_pk = first_location_pk(explore_page) or load_env().get("IG_E2_LOCATION_ID")
   replay.record(
      "location_source", "explore grid" if first_location_pk(explore_page) else "env or none"
   )

   if location_pk:
      await location(replay, location_pk)
   else:
      replay.record("location", "skipped, no location id")

   for attempt in (1, 2):
      check = await replay.graphql(
         "check-for-new-feed-posts",
         {},
         referer=f"{ORIGIN}/",
         label=f"new feed posts check {attempt}",
         try_other_path_on_null=attempt == 1,
      )

      if check is not None:
         replay.shape("new_feed_posts", dig(check, "data"))


async def location(replay: E2Replay, location_pk: str) -> None:
   location_page = f"{ORIGIN}/explore/locations/{location_pk}/"

   for attempt in (1, 2):
      header = await replay.graphql(
         "read-a-location-s-info",
         {"location_id_str": location_pk, "show_nearby": False},
         referer=location_page,
         label=f"location header {attempt}",
         try_other_path_on_null=attempt == 1,
      )

      if header is not None:
         replay.shape("location_header", dig(header, "data"))

   tab_variables = {
      "location_id": location_pk,
      "first": 12,
      "after": None,
      "tab": "ranked",
      "page_size_override": None,
      **SHORT_DRAMA,
   }
   cursor = None
   more = None

   for attempt in (1, 2):
      tab = await replay.graphql(
         "read-a-location-page-tab",
         tab_variables,
         referer=location_page,
         label=f"location grid {attempt}",
         try_other_path_on_null=attempt == 1,
      )
      connection = dig(tab, "data", TAB_ROOT)
      replay.record(f"location_grid_{attempt}", page_info_of(connection))
      cursor = cursor or dig(connection, "page_info", "end_cursor")
      more = more or dig(connection, "page_info", "has_next_page")

      if tab is not None:
         replay.shape("location_grid", connection)

   has_next_page = bool(more) and bool(cursor)

   if not has_next_page:
      replay.record("location_grid_next_page", "skipped, one page only")

      return

   for attempt in (1, 2):
      page = await replay.graphql(
         "read-a-location-page-tab-next-page",
         {**tab_variables, "after": cursor},
         referer=location_page,
         label=f"location grid next page {attempt}",
      )
      replay.record(f"location_grid_next_page_{attempt}", page_info_of(dig(page, "data", TAB_ROOT)))


if __name__ == "__main__":
   sys.exit(asyncio.run(run_probe("e2-discovery-feeds", PLANNED, CONDITIONAL, body)))
