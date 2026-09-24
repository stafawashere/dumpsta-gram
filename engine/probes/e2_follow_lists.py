"""Read only. Not yet run. Six requests, and one more, conditional.

E2 batch 3, the relationship lists, on the owner's own account: one page of the owner's
followers over REST, twice, and the relationship statuses the list page asks for beside it,
twice. The following and mutual lists have no observed request yet and are not replayed here.

   1  the inbox document, for fresh tokens (the bootstrap)
   2  the owner's profile by id, a verified read, for the username the referer needs
   3  GET /api/v1/friendships/<own id>/followers/ with count 12 and search_surface
      follow_list_page, as observed once, twice
   5  POST /api/v1/friendships/show_many/ for the ids that page returned, twice

Conditional: one further followers page with ``max_id`` set to the first page's
``next_max_id``. That parameter name is an INFERENCE, never observed, so its answer is recorded
as evidence for or against it and nothing else.

``show_many`` is a POST but a read: it asks for statuses and changes none. Reading one's own
followers is visible to nobody. Findings: ``read-an-account-s-followers`` and
``friendship-statuses-for-many-accounts``, both hypotheses from one sighting each. The ids the
list returns are sent to show_many and never written to the log.

Run it from `engine/` with:

   uv run python probes/e2_follow_lists.py
"""

from __future__ import annotations

import asyncio
import sys

from _e2_support import E2Replay, id_prefix, run_probe

from dumpstagram._private.web.bootstrap import ORIGIN
from dumpstagram._private.web.parse.profiles import parse_profile
from dumpstagram._private.web.requests.profiles import build_profile_request

PLANNED = 6
CONDITIONAL = 1
FOLLOWERS_PAGE = {"count": "12", "search_surface": "follow_list_page"}
RELATIONSHIP_BATCH = 11


async def body(replay: E2Replay) -> None:
   await replay.bootstrap()

   viewer_id = replay.viewer_id
   profile_payload = await replay.engine_read(
      "own profile by id", build_profile_request(replay.session, viewer_id)
   )
   username = parse_profile(profile_payload).username if profile_payload else None

   if username is None:
      replay.record("skipped", "the own profile read gave no username")

      return

   profile_page = f"{ORIGIN}/{username}/"
   followers_url = f"{ORIGIN}/api/v1/friendships/{viewer_id}/followers/"
   first_page = None

   for attempt in (1, 2):
      page = await replay.rest(
         f"followers page {attempt}", followers_url, referer=profile_page, params=FOLLOWERS_PAGE
      )
      users = (page or {}).get("users") or []
      next_max_id = (page or {}).get("next_max_id")
      replay.record(
         f"followers_{attempt}",
         {
            "users": len(users),
            "first_user_prefix": id_prefix(users[0].get("pk")) if users else None,
            "next_max_id_length": len(next_max_id) if isinstance(next_max_id, str) else None,
            "has_more": (page or {}).get("has_more"),
         },
      )

      if page is not None:
         replay.shape("followers_page", page)
         first_page = first_page or page

   next_max_id = (first_page or {}).get("next_max_id")
   has_second_page = isinstance(next_max_id, str) and bool(next_max_id)

   if has_second_page:
      second = await replay.rest(
         "followers page two, max_id INFERENCE",
         followers_url,
         referer=profile_page,
         params={**FOLLOWERS_PAGE, "max_id": next_max_id},
      )
      second_users = (second or {}).get("users") or []
      first_ids = {user.get("pk") for user in (first_page or {}).get("users") or []}
      overlap = sum(1 for user in second_users if user.get("pk") in first_ids)
      replay.record(
         "followers_page_two", {"users": len(second_users), "overlap_with_page_one": overlap}
      )

   user_ids = [
      str(user.get("pk")) for user in ((first_page or {}).get("users") or []) if user.get("pk")
   ][:RELATIONSHIP_BATCH]

   if not user_ids:
      replay.record("show_many", "skipped, no follower ids to ask about")

      return

   for attempt in (1, 2):
      statuses = await replay.rest(
         f"show_many {attempt}",
         f"{ORIGIN}/api/v1/friendships/show_many/",
         referer=profile_page,
         form={"user_ids": ",".join(user_ids)},
      )
      answered = (statuses or {}).get("friendship_statuses") or {}
      replay.record(f"show_many_{attempt}", {"asked": len(user_ids), "answered": len(answered)})

      if statuses is not None:
         first_status = next(iter(answered.values()), None)
         replay.shape("friendship_status", first_status)


if __name__ == "__main__":
   sys.exit(asyncio.run(run_probe("e2-follow-lists", PLANNED, CONDITIONAL, body)))
