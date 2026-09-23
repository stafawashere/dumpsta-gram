"""Read only. Two live requests, or three if the stored tokens are stale and re-bootstrap fires.

The live acceptance for the thread route of 2026-09-23. It opens one thread the way the default
client now does, through ``IGDThreadDetailQuery``, then reads the next older page through
``IGDMessageListOffMsysQuery`` with the detail answer's ``end_cursor``, which is the chain a
browser was captured walking. It answers whether the engine's own requests for both queries are
accepted, and whether the detail cursor leads to the page that follows it.

It drives ``_core.direct.read_thread_messages``, so the builders, the classifier and both mappers
are the library's own. A transport wrapper records the friendly name each request carried.

Recorded: the friendly names sent, message counts, ``has_next_page``, the ``end_cursor`` length,
whether the two pages share any message id, and whether every message on the older page was
sent no later than the oldest on the newest page. No text, name or id is written.

Run it from `engine/` with:

   uv run python probes/thread_route_live.py
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
from dumpstagram.behavior import ThreadFirstPage
from dumpstagram.errors import DumpstagramError
from dumpstagram.models import Message, Page
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_THREAD_FBID", "IG_USER_AGENT", "IG_SESSION_FILE")


class RecordingTransport:
   def __init__(self, inner: HttpxTransport) -> None:
      self.inner = inner
      self.friendly_names: list[str] = []

   async def send(self, request: Request) -> Response:
      self.friendly_names.append(request.headers.get("x-fb-friendly-name", "document"))

      return await self.inner.send(request)

   async def aclose(self) -> None:
      await self.inner.aclose()


def describe(page: Page[Message]) -> dict[str, object]:
   return {
      "message_count": len(page.items),
      "has_next_page": page.has_next_page,
      "end_cursor_length": len(page.end_cursor) if page.end_cursor else None,
   }


async def run() -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}

   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   thread_fbid = environment.get("IG_THREAD_FBID") or THREAD_FBID
   user_agent = environment.get("IG_USER_AGENT") or DEFAULT_USER_AGENT

   report: dict[str, object] = {
      "session_path": str(session_path),
      "credentials_read_from_env": False,
   }

   if not session_path.exists():
      report["failed_with"] = "no session file, run probes/adopt_and_save.py first"

      report_run("thread-route-live-failed", report)

      return 2

   session = Session.load(session_path)
   transport = RecordingTransport(HttpxTransport(cookies=cookies_for(session), proxy=session.proxy))
   started_at = time.monotonic()

   try:
      async with PacedSender(transport, Pacer()) as sender:
         newest = await read_thread_messages(
            sender,
            session,
            thread_fbid,
            first_page=ThreadFirstPage.DETAIL,
            user_agent=user_agent,
         )
         older = None

         if newest.end_cursor:
            older = await read_thread_messages(
               sender,
               session,
               thread_fbid,
               after=newest.end_cursor,
               first_page=ThreadFirstPage.DETAIL,
               user_agent=user_agent,
            )
   except DumpstagramError as failure:
      report["failed_with"] = type(failure).__name__
      report["failure_text"] = str(failure)[:200]
      report["friendly_names_sent"] = transport.friendly_names
      report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)

      report_run("thread-route-live-failed", report)

      return 3

   report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
   report["friendly_names_sent"] = transport.friendly_names
   report["requests_spent"] = len(transport.friendly_names)
   report["newest_page"] = describe(newest)

   if older is not None:
      newest_ids = {message.id for message in newest.items}
      shared_ids = [message for message in older.items if message.id in newest_ids]
      oldest_on_newest = min(message.sent_at for message in newest.items)
      older_is_older = all(message.sent_at <= oldest_on_newest for message in older.items)

      report["older_page"] = describe(older)
      report["messages_on_both_pages"] = len(shared_ids)
      report["older_page_is_entirely_older"] = older_is_older

   report_run("thread-route-live", report)

   return 0


if __name__ == "__main__":
   sys.exit(asyncio.run(run()))
