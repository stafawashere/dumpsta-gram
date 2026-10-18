"""Read only. One live thread open, two requests at most, three if the tokens are stale.

The read state the default client maps from the same answer, to decide on a mark read, is
mapped offline from the body kept in memory, and its failure path recorded too.

Release phase 4 found that the app's first page read of the owner-approved write thread raised
``SchemaChanged`` whenever the thread listed no message, before the write check's send and after
its unsend, while the read between them, with one message listed, mapped. This probe opens that
thread once through ``IGDThreadDetailQuery``, the default first page, and records where the
mapping gave up and the shape of the answer: keys and value types along the thread path, the
length of ``slide_messages.edges``, and the ``page_info`` keys. No text, name or id is written.

It drives ``_core.direct.read_thread_messages``, so the builders, the classifier and the mappers
are the library's own. A transport wrapper keeps the answer body in memory for the census and
refuses a fourth request.

Run it from `engine/` with:

   uv run python probes/empty_thread_shape.py --thread-fbid FBID [--session-file PATH]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

from _probe_support import SESSION_PATH, load_env, report_run

from dumpstagram._core.direct import read_thread_messages
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import HttpxTransport, Request, Response, cookies_for
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT
from dumpstagram._private.web.parse.direct import parse_thread_read_state
from dumpstagram.behavior import ThreadFirstPage
from dumpstagram.errors import DumpstagramError
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE")

REQUEST_CAP = 3


class CensusTransport:
   def __init__(self, inner: HttpxTransport) -> None:
      self.inner = inner
      self.friendly_names: list[str] = []
      self.detail_body: bytes | None = None

   async def send(self, request: Request) -> Response:
      if len(self.friendly_names) >= REQUEST_CAP:
         raise RuntimeError(f"request cap {REQUEST_CAP} reached")

      name = request.headers.get("x-fb-friendly-name", "document")
      self.friendly_names.append(name)
      response = await self.inner.send(request)

      if name == "IGDThreadDetailQuery":
         self.detail_body = response.content

      return response

   async def aclose(self) -> None:
      await self.inner.aclose()


def shape(value: Any, depth: int = 0) -> Any:
   """Keys and value types only, two levels below the node it starts at."""

   if isinstance(value, dict):
      if depth >= 2:
         return f"object({len(value)} keys)"

      return {key: shape(item, depth + 1) for key, item in sorted(value.items())}

   if isinstance(value, list):
      return f"list({len(value)})"

   return type(value).__name__


def census(body: bytes) -> dict[str, object]:
   payload = json.loads(body)
   data = payload.get("data") if isinstance(payload, dict) else None

   if not isinstance(data, dict):
      return {"data_keys": None, "has_errors": isinstance(payload, dict) and "errors" in payload}

   result: dict[str, object] = {"data_keys": sorted(data), "has_errors": "errors" in payload}

   for root, node in sorted(data.items()):
      result[root] = shape(node)

      if isinstance(node, dict):
         thread = node.get("as_ig_direct_thread")

         if isinstance(thread, dict):
            result["thread_shape"] = shape(thread)
            messages = thread.get("slide_messages")

            if isinstance(messages, dict):
               result["slide_messages_shape"] = shape(messages, 0)

            # The form of the last activity value with every digit written as 9, so a value
            # that is not a string of digits shows what it is instead, and no time is kept.
            last_activity = thread.get("last_activity_timestamp_ms")
            result["last_activity_form"] = re.sub(r"\d", "9", repr(last_activity))[:32]

            receipts = thread.get("slide_read_receipts")

            if isinstance(receipts, list):
               result["read_receipts_shape"] = [shape(receipt, 1) for receipt in receipts]

   return result


async def run(thread_fbid: str, session_file: str | None) -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}
   session_path = Path(session_file or environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT") or DEFAULT_USER_AGENT
   report: dict[str, object] = {"credentials_read_from_env": False}

   if not session_path.exists():
      report["failed_with"] = "no session file, run probes/adopt_and_save.py first"
      report_run("empty-thread-shape-failed", report)

      return 2

   session = Session.load(session_path)
   transport = CensusTransport(HttpxTransport(cookies=cookies_for(session), proxy=session.proxy))

   try:
      async with PacedSender(transport, Pacer()) as sender:
         page = await read_thread_messages(
            sender, session, thread_fbid, first_page=ThreadFirstPage.DETAIL, user_agent=user_agent
         )
         report["message_count"] = len(page.items)
         report["has_next_page"] = page.has_next_page
   except DumpstagramError as failure:
      report["failed_with"] = type(failure).__name__
      report["failure_path"] = getattr(failure, "path", None)

   report["friendly_names_sent"] = transport.friendly_names

   if transport.detail_body is not None:
      report["answer"] = census(transport.detail_body)

      # The thread open's read state, which the default client reads to decide on a mark read,
      # mapped offline from the same answer.
      try:
         state = parse_thread_read_state(json.loads(transport.detail_body))
         report["read_state"] = {
            "is_unread": state.is_unread,
            "has_newest_message": state.newest_message_id is not None,
         }
      except DumpstagramError as failure:
         report["read_state_failed_with"] = type(failure).__name__
         report["read_state_failure_path"] = getattr(failure, "path", None)

   report_run("empty-thread-shape", report)

   return 0


def main() -> int:
   parser = argparse.ArgumentParser()
   parser.add_argument("--thread-fbid", required=True)
   parser.add_argument(
      "--session-file", help="a session file Session.save wrote, such as the app's"
   )
   arguments = parser.parse_args()

   return asyncio.run(run(arguments.thread_fbid, arguments.session_file))


if __name__ == "__main__":
   sys.exit(main())
