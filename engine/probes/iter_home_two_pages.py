"""Read only. At most four live requests: two or three pages of the home timeline through
``client.feeds.iter_home``, plus a bootstrap if the saved session needs one. The transport refuses
a fifth.

E1 item 5 of the web parity plan added the pagination iterators, gated offline on scripted pages.
This is the one live check the item allows: a walk whose ``limit`` is larger than a first page,
so the iterator has to hand the first page's end cursor to the second read, and has to stop the
moment the limit is reached without reading a page it does not use.

The client runs under the EXPORT spacing, a 2500 ms floor and 350 ms mean jitter, the 2850 ms the
probe rules ask for, with the first feed page read by the pagination query and the page load
companions and the cookie sync tail off, so every request it sends is a feed page or a bootstrap.

Recorded: each request's friendly name, status, length, offset, whether it carried a cursor and
the cursor's length, and how many items the walk had yielded when it left. Also the kinds of the
items yielded, counted. No caption, no author, no id of anyone else's content.

Credentials come from the saved session, which ``adopt_and_save.py`` wrote from the root ``.env``.

Run it from `engine/` with:

   uv run python probes/iter_home_two_pages.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs

from _probe_support import SESSION_PATH, load_env, report_run

from dumpstagram import AsyncClient
from dumpstagram._private.transport import Request, Response, Sender
from dumpstagram.behavior import EXPORT, FeedFirstPage
from dumpstagram.errors import DumpstagramError
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE")

REQUEST_CAP = 4

LIMIT = 16
"""Larger than every first page measured so far, 3 to 14 items, so a second page is needed."""


class CappedTransport:
   def __init__(self, inner: Sender, cap: int, yielded: list[int]) -> None:
      self.inner = inner
      self.cap = cap
      self.yielded = yielded
      self.sent: list[dict[str, object]] = []
      self.started_at = time.monotonic()

   async def send(self, request: Request) -> Response:
      if len(self.sent) >= self.cap:
         raise RuntimeError(f"refusing request {len(self.sent) + 1}, the cap is {self.cap}")

      entry: dict[str, object] = {
         "name": request.headers.get("x-fb-friendly-name", "document"),
         "offset_ms": int((time.monotonic() - self.started_at) * 1000),
         "items_yielded_before": self.yielded[0],
      }
      entry.update(cursor_sent(request))
      self.sent.append(entry)

      response = await self.inner.send(request)
      entry["status"] = response.status_code
      entry["length"] = len(response.content)

      return response

   async def aclose(self) -> None:
      closer = getattr(self.inner, "aclose", None)

      if closer is not None:
         await closer()


def cursor_sent(request: Request) -> dict[str, object]:
   if not request.content:
      return {"after_sent": False}

   body = parse_qs(request.content.decode("utf-8"))
   variables_field = body.get("variables")

   if not variables_field:
      return {"after_sent": False}

   after = json.loads(variables_field[0]).get("after")

   return {"after_sent": after is not None, "after_length": len(after) if after else 0}


async def run() -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}
   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   kind = "iter-home-two-pages"

   report: dict[str, object] = {"limit": LIMIT, "request_cap": REQUEST_CAP}

   if not session_path.exists():
      report["failed_with"] = "no session file, run probes/adopt_and_save.py first"
      report_run(f"{kind}-failed", report)

      return 2

   behavior = replace(
      EXPORT,
      feed_first_page=FeedFirstPage.QUERY,
      page_load_companions=False,
      cookie_sync=False,
   )
   yielded = [0]
   kinds: Counter[str] = Counter()
   user_agent = environment.get("IG_USER_AGENT")

   client = AsyncClient(Session.load(session_path), user_agent=user_agent, behavior=behavior)
   transport = CappedTransport(client._sender._sender, REQUEST_CAP, yielded)
   client._sender._sender = transport
   report["requests"] = transport.sent

   try:
      async for item in client.feeds.iter_home(limit=LIMIT):
         yielded[0] += 1
         kinds[item.kind.name] += 1
   except (DumpstagramError, RuntimeError) as failure:
      report["failed_with"] = type(failure).__name__
      report["failure_text"] = str(failure)[:200]
   finally:
      await client.aclose()

   feed_reads = [entry for entry in transport.sent if entry["name"] != "document"]

   report["items_yielded"] = yielded[0]
   report["item_kinds"] = dict(kinds)
   report["requests_spent"] = len(transport.sent)
   report["feed_reads"] = len(feed_reads)
   report["stopped_at_the_limit"] = yielded[0] == LIMIT
   report["every_read_after_the_first_carried_a_cursor"] = all(
      entry["after_sent"] for entry in feed_reads[1:]
   )
   report["first_read_carried_no_cursor"] = bool(feed_reads) and not feed_reads[0]["after_sent"]

   failed = "failed_with" in report
   report_run(f"{kind}-failed" if failed else kind, report)

   return 3 if failed else 0


def main() -> int:
   return asyncio.run(run())


if __name__ == "__main__":
   sys.exit(main())
