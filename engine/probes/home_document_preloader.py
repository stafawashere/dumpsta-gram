"""Read only. One live request, the home document, about 1.2 MB, or two with ``--follow``.

Answers whether the first feed page arrives inside the home document when the library loads
it, rather than when a browser does. Two browser cold loads on 2026-09-23 carried it as a
``PolarisFeedTimelineRootV2Query`` relay preloader. A plain HTTP client sending the same
navigation headers is a different client, and the server renders the document per request, so
the preload is not evidence until this client has received one.

It drives ``_core.feed.read_first_feed_page_from_document``, so the request, the token harvest,
the preload reader and the mapper are the library's own. It records the document size, the
item count, the kind of each item, ``has_next_page``, the length of ``end_cursor`` and whether
the page tokens changed. No caption, name, id or URL is written.

With ``--follow`` it then reads page two through the pagination query with the document's
``end_cursor``, which is what a browser does when the feed scrolls, and records the same
counts for that page. It answers whether a preloaded cursor is accepted by the query.

Run it from `engine/` with:

   uv run python probes/home_document_preloader.py
   uv run python probes/home_document_preloader.py --follow
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from _probe_support import SESSION_PATH, load_env, report_run

from dumpstagram._core.feed import read_feed_page, read_first_feed_page_from_document
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import HttpxTransport, cookies_for
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT
from dumpstagram.behavior import FeedFirstPage
from dumpstagram.errors import DumpstagramError
from dumpstagram.models import FeedItem, Page
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE")


def describe(page: Page[FeedItem]) -> dict[str, object]:
   return {
      "item_count": len(page.items),
      "item_kinds": [item.kind.name for item in page.items],
      "has_next_page": page.has_next_page,
      "end_cursor_length": len(page.end_cursor) if page.end_cursor else None,
   }


async def run(follow: bool) -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}

   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT") or DEFAULT_USER_AGENT

   report: dict[str, object] = {
      "session_path": str(session_path),
      "credentials_read_from_env": False,
      "requests_spent": 2 if follow else 1,
      "follow": follow,
   }

   if not session_path.exists():
      report["failed_with"] = "no session file, run probes/adopt_and_save.py first"
      report["requests_spent"] = 0

      report_run("home-document-preloader-failed", report)

      return 2

   try:
      session = Session.load(session_path)
   except DumpstagramError as failure:
      report["failed_with"] = type(failure).__name__
      report["requests_spent"] = 0

      report_run("home-document-preloader-failed", report)

      return 2

   token_before = session.fb_dtsg
   transport = HttpxTransport(cookies=cookies_for(session), proxy=session.proxy)
   started_at = time.monotonic()

   try:
      async with PacedSender(transport, Pacer()) as sender:
         page = await read_first_feed_page_from_document(sender, session, user_agent=user_agent)
         token_after_the_document = session.fb_dtsg
         page_two = None

         if follow and page.end_cursor:
            page_two = await read_feed_page(
               sender,
               session,
               after=page.end_cursor,
               first_page=FeedFirstPage.DOCUMENT,
               user_agent=user_agent,
            )
   except DumpstagramError as failure:
      report["failed_with"] = type(failure).__name__
      report["failure_text"] = str(failure)[:200]
      report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)

      report_run("home-document-preloader-failed", report)

      return 3

   report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
   report["document_page"] = describe(page)
   report["page_token_changed"] = token_after_the_document != token_before

   if page_two is not None:
      report["page_two"] = describe(page_two)

   report_run("home-document-preloader", report)

   return 0


if __name__ == "__main__":
   sys.exit(asyncio.run(run("--follow" in sys.argv[1:])))
