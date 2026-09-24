"""Read only. Not yet run. Seven requests, and up to three more, conditional.

E2 batch 6, the owner's own account, the parts whose requests are known: pending follow
requests and the activity feed over REST, as an inbox load sends them, and the saved
collections list. Saved posts, the activity feed's GraphQL view, the notifications badge, the
archive, the close friends list and the blocked list wait for the browser capture the
execution list names.

   1  the inbox document, for fresh tokens (the bootstrap)
   2  GET /api/v1/friendships/pending/, twice
   4  POST /api/v1/news/inbox/ with only fb_dtsg and jazoest in the body, as observed, twice
   6  the saved collections list, PolarisSavedCollectionPickerQuery, twice

Conditional: the collections list's next page, PolarisSavedCollectionPickerPaginationQuery,
twice when the first page has more, and the collections query's first replay sent once more on
the other GraphQL path when every root is null.

``news/inbox`` is a POST that reads. A real inbox load follows it with ``news/inbox_seen``,
which marks the viewer's own activity seen; that one is not sent here, so the owner's
notifications badge is left as it was. None of this is visible to another person. The activity
feed's entries name other accounts, so only its key union and counts are logged.

Findings: ``pending-follow-requests`` and ``activity-feed-inbox``, hypotheses from one inbox
load each, and ``read-saved-collections`` and ``read-saved-collections-next-page``.

Run it from `engine/` with:

   uv run python probes/e2_own_account.py
"""

from __future__ import annotations

import asyncio
import sys

from _e2_support import E2Replay, dig, page_info_of, run_probe

from dumpstagram._private.web.bootstrap import ORIGIN

PLANNED = 7
CONDITIONAL = 3
INBOX = f"{ORIGIN}/direct/inbox/"


async def body(replay: E2Replay) -> None:
   await replay.bootstrap()

   for attempt in (1, 2):
      pending = await replay.rest(
         f"pending follow requests {attempt}",
         f"{ORIGIN}/api/v1/friendships/pending/",
         referer=INBOX,
      )
      users = (pending or {}).get("users") or []
      replay.record(
         f"pending_{attempt}", {"users": len(users), "status": (pending or {}).get("status")}
      )

      if pending is not None:
         replay.shape("pending_follow_requests", pending)

   for attempt in (1, 2):
      activity = await replay.rest(
         f"activity feed {attempt}",
         f"{ORIGIN}/api/v1/news/inbox/",
         referer=INBOX,
         form={},
      )
      replay.record(
         f"activity_{attempt}",
         {
            "top_keys": sorted(activity or {}),
            "new_stories": len((activity or {}).get("new_stories") or []),
            "old_stories": len((activity or {}).get("old_stories") or []),
         },
      )

      if activity is not None:
         replay.shape("activity_feed", activity)

   collections_variables = {"first": 12, "after": None}
   cursor = None
   more = None

   for attempt in (1, 2):
      collections = await replay.graphql(
         "read-saved-collections",
         collections_variables,
         referer=f"{ORIGIN}/",
         label=f"saved collections {attempt}",
         try_other_path_on_null=attempt == 1,
      )
      connection = dig(collections, "data", "viewer", "media_collections")
      replay.record(f"collections_{attempt}", page_info_of(connection))
      cursor = cursor or dig(connection, "page_info", "end_cursor")
      more = more or dig(connection, "page_info", "has_next_page")

      if collections is not None:
         replay.shape("saved_collections", connection)

   has_next_page = bool(more) and bool(cursor)

   if not has_next_page:
      replay.record("collections_next_page", "skipped, one page only")

      return

   for attempt in (1, 2):
      page = await replay.graphql(
         "read-saved-collections-next-page",
         {"first": 12, "after": cursor},
         referer=f"{ORIGIN}/",
         label=f"saved collections next page {attempt}",
      )
      replay.record(
         f"collections_next_page_{attempt}",
         page_info_of(dig(page, "data", "viewer", "media_collections")),
      )


if __name__ == "__main__":
   sys.exit(asyncio.run(run_probe("e2-own-account", PLANNED, CONDITIONAL, body)))
