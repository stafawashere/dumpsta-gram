"""Read only. Not yet run. Eight requests, and up to three more, conditional.

E2 batch 1, the direct read side: the inbox listing made public with its pagination, the
message requests, and a thread's details panel. Each hypothesis read is replayed twice, the
standing rule for a read entering the package.

   1  the inbox document, for fresh tokens (the bootstrap)
   2  the inbox listing, a verified read, for the mailbox id and the first page's cursor
   3  the thread list's next page, IGDThreadListOffMsysPaginationQuery, twice
   5  the message requests, IGDMessageRequestLeftRailStandaloneQuery, twice
   7  the details panel of the ruling 30 thread, IGDInboxInfoOffMsysQuery, twice

Conditional: each hypothesis query's first replay is sent once more on the other GraphQL path
when it answers with every root null, three at most. Steps 3 and 4 are skipped when the inbox
has one page only, which spends two fewer.

Nothing here opens a thread or a request thread, so nothing is marked seen, and nothing is
visible to another person. Findings: ``direct-inbox-thread-list`` (verified),
``direct-inbox-thread-list-next-page``, ``direct-message-requests`` and
``direct-thread-details-panel`` (hypotheses). The session comes from the session file and the
thread from ``IG_THREAD_FBID`` in the root ``.env``, falling back to the measured thread.
Only key unions, counts and lengths are logged.

Run it from `engine/` with:

   uv run python probes/e2_direct_read.py
"""

from __future__ import annotations

import asyncio
import sys
import time

from _e2_support import E2Replay, dig, id_prefix, page_info_of, run_probe
from _probe_support import THREAD_FBID

from dumpstagram._private.web.bootstrap import ORIGIN
from dumpstagram._private.web.requests.direct import build_inbox_listing_request, thread_url

PLANNED = 8
CONDITIONAL = 3
INBOX = f"{ORIGIN}/direct/inbox/"
PROVIDERS = {
   "__relay_internal__pv__IGDPinnedThreadsRenderEnabledGKrelayprovider": True,
   "__relay_internal__pv__IGDMaxUnreadMessagesCountrelayprovider": 5,
   "__relay_internal__pv__IGDThreadListActionsEnabledGKrelayprovider": True,
}
THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000


async def body(replay: E2Replay) -> None:
   await replay.bootstrap()

   listing = await replay.engine_read(
      "inbox listing", build_inbox_listing_request(replay.session, device_id=replay.device_id)
   )
   mailbox = dig(listing, "data", "get_slide_mailbox_for_iris_subscription")
   connection = dig(mailbox, "threads_by_folder")
   first_page = page_info_of(connection)
   cursor = dig(connection, "page_info", "end_cursor")
   mailbox_id = dig(mailbox, "id")
   replay.record("first_page", first_page | {"mailbox_id_present": mailbox_id is not None})

   can_page = bool(first_page["has_next_page"]) and cursor and mailbox_id

   if can_page:
      variables = {
         "count": 15,
         "cursor": cursor,
         "folder": "INBOX",
         "newer_than_timestamp_ms": None,
         "id": mailbox_id,
         **PROVIDERS,
      }

      for attempt in (1, 2):
         page = await replay.graphql(
            "direct-inbox-thread-list-next-page",
            variables,
            referer=INBOX,
            label=f"thread list next page {attempt}",
            try_other_path_on_null=attempt == 1,
         )
         next_connection = dig(page, "data", "fetch__SlideMailbox", "threads_by_folder")
         first_node = dig(next_connection, "edges", 0, "node")
         replay.record(
            f"next_page_{attempt}",
            page_info_of(next_connection)
            | {"first_thread_prefix": id_prefix(dig(first_node, "id"))},
         )

         if page is not None:
            replay.shape("thread_list_next_page", next_connection)

   thirty_days_ago = int(time.time() * 1000) - THIRTY_DAYS_MS
   request_variables = {
      "device_id_for_iris_subscription": replay.device_id,
      "__relay_internal__pv__IGD30DayAgoTimestampMsrelayprovider": thirty_days_ago,
      **PROVIDERS,
   }

   for attempt in (1, 2):
      requests_page = await replay.graphql(
         "direct-message-requests",
         request_variables,
         referer=INBOX,
         label=f"message requests {attempt}",
         try_other_path_on_null=attempt == 1,
      )

      if requests_page is not None:
         replay.shape("message_requests", dig(requests_page, "data"))

   thread_fbid = replay.environment.get("IG_THREAD_FBID") or THREAD_FBID
   detail_variables = {
      "thread_fbid": thread_fbid,
      "__relay_internal__pv__IGDGroupLinksEnabledGKrelayprovider": False,
      "__relay_internal__pv__IGDEnableOffMsysChatThemesQErelayprovider": False,
   }

   for attempt in (1, 2):
      details = await replay.graphql(
         "direct-thread-details-panel",
         detail_variables,
         referer=thread_url(thread_fbid),
         label=f"thread details {attempt}",
         try_other_path_on_null=attempt == 1,
      )

      if details is not None:
         replay.shape("thread_details", dig(details, "data"))


if __name__ == "__main__":
   sys.exit(asyncio.run(run_probe("e2-direct-read", PLANNED, CONDITIONAL, body)))
