"""Read only. Four live requests, five with a bootstrap, all on one thread through
``IGDMessageListOffMsysQuery``, the scrolling query the inbox poller sends.

E1 item 1 of the web parity plan moves the poller onto ``newer_than_message_id``. Step 21 saw it
filter once, with one message newer than a live base. What a poller also needs is how it behaves
when more than one page of messages is newer than the base, which nothing has observed:

- how many messages one filtered read returns when more than twenty are newer
- whether those are the newest ones or the ones just after the base
- what ``has_next_page`` says, and whether the cursor it gives, sent with the same base, reaches
  the rest without passing the base

It reads the newest page and the page before it with no base, picks as the base the message 25
places from the newest, so 24 are newer, then reads with that base and, when the answer says
there is more, reads once more by its cursor with the same base.

Nothing is opened and nothing is marked seen: every read is the scrolling query. Recorded: ids,
counts, positions, times and each request's friendly name, status and length. No text, no
sender, no name. Paced by the default ``Pacer``, whose mean spacing is the 2850 ms the probe
rules ask for. Credentials come from the saved session, which ``adopt_and_save.py`` wrote from
the root ``.env``.

Run it from `engine/` with:

   uv run python probes/newer_than_pages.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from _probe_support import SESSION_PATH, THREAD_FBID, load_env, report_run

from dumpstagram._core.direct import read_thread_messages
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import HttpxTransport, Request, Response, cookies_for
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT
from dumpstagram.errors import DumpstagramError
from dumpstagram.models import Message, Page
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_THREAD_FBID", "IG_USER_AGENT", "IG_SESSION_FILE")

REQUEST_CAP = 5

BASE_POSITION = 24
"""Zero-based position of the base in the thread, newest first, so 24 messages are newer."""


class CappedTransport:
   def __init__(self, inner: HttpxTransport, cap: int) -> None:
      self.inner = inner
      self.cap = cap
      self.sent: list[dict[str, object]] = []
      self.started_at = time.monotonic()

   async def send(self, request: Request) -> Response:
      if len(self.sent) >= self.cap:
         raise RuntimeError(f"refusing request {len(self.sent) + 1}, the cap is {self.cap}")

      entry: dict[str, object] = {
         "name": request.headers.get("x-fb-friendly-name", "document"),
         "offset_ms": int((time.monotonic() - self.started_at) * 1000),
      }
      self.sent.append(entry)

      response = await self.inner.send(request)
      entry["status"] = response.status_code
      entry["length"] = len(response.content)

      return response

   async def aclose(self) -> None:
      await self.inner.aclose()


def newest_first(messages: list[Message]) -> list[Message]:
   return sorted(messages, key=lambda message: message.sent_at, reverse=True)


def describe(page: Page[Message], positions: dict[str, int]) -> dict[str, object]:
   """Where each returned message sits in the thread, newest first, and in what order it came."""

   returned = [message.id for message in page.items]
   ordered = [positions.get(message_id) for message_id in returned]
   known = [position for position in ordered if position is not None]

   return {
      "message_count": len(returned),
      "has_next_page": page.has_next_page,
      "has_end_cursor": page.end_cursor is not None,
      "end_cursor_length": len(page.end_cursor) if page.end_cursor else 0,
      "positions_in_listed_order": ordered,
      "unknown_ids": sum(1 for position in ordered if position is None),
      "newest_position": min(known, default=None),
      "oldest_position": max(known, default=None),
      "any_at_or_past_the_base": any(position >= BASE_POSITION for position in known),
      "ids": returned,
   }


async def run() -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}
   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   thread_fbid = environment.get("IG_THREAD_FBID") or THREAD_FBID
   user_agent = environment.get("IG_USER_AGENT") or DEFAULT_USER_AGENT
   kind = "newer-than-pages"

   report: dict[str, object] = {
      "thread_fbid": thread_fbid,
      "base_position": BASE_POSITION,
      "request_cap": REQUEST_CAP,
   }

   if not session_path.exists():
      report["failed_with"] = "no session file, run probes/adopt_and_save.py first"
      report_run(f"{kind}-failed", report)

      return 2

   session = Session.load(session_path)
   transport = CappedTransport(
      HttpxTransport(cookies=cookies_for(session), proxy=session.proxy), REQUEST_CAP
   )
   report["requests"] = transport.sent

   async with PacedSender(transport, Pacer()) as sender:

      async def read(after: str | None, newer_than: str | None) -> Page[Message]:
         return await read_thread_messages(
            sender,
            session,
            thread_fbid,
            after=after,
            newer_than_message_id=newer_than,
            user_agent=user_agent,
         )

      try:
         newest = await read(None, None)
         older = await read(newest.end_cursor, None)
         thread = newest_first([*newest.items, *older.items])
         positions = {message.id: position for position, message in enumerate(thread)}

         report["unfiltered"] = {
            "newest_page_count": len(newest.items),
            "older_page_count": len(older.items),
            "distinct_messages": len(positions),
            "newest_page_has_next_page": newest.has_next_page,
         }

         if len(thread) <= BASE_POSITION:
            report["failed_with"] = "the thread has too few messages for a base 25 back"
            report_run(f"{kind}-failed", report)

            return 3

         base = thread[BASE_POSITION]
         report["base"] = {"id": base.id, "sent_at": base.sent_at.isoformat()}

         filtered = await read(None, base.id)
         report["filtered_first"] = describe(filtered, positions)

         covered = {message.id for message in filtered.items}
         can_follow = filtered.has_next_page and filtered.end_cursor is not None

         if can_follow:
            following = await read(filtered.end_cursor, base.id)
            described = describe(following, positions)
            described["overlap_with_first"] = sum(
               1 for message in following.items if message.id in covered
            )
            report["filtered_second"] = described
            covered |= {message.id for message in following.items}

         newer_ids = {message.id for message in thread[:BASE_POSITION]}
         report["newer_than_base_expected"] = len(newer_ids)
         report["newer_than_base_covered"] = len(newer_ids & covered)
         report["covered_outside_the_newer_set"] = len(covered - newer_ids)
      except (DumpstagramError, RuntimeError) as failure:
         report["failed_with"] = type(failure).__name__
         report["failure_text"] = str(failure)[:200]
         report["requests_spent"] = len(transport.sent)
         report_run(f"{kind}-failed", report)

         return 3

   report["requests_spent"] = len(transport.sent)
   report_run(kind, report)

   return 0


def main() -> int:
   return asyncio.run(run())


if __name__ == "__main__":
   sys.exit(main())
