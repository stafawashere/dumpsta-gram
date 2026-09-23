"""Writes twice: one direct text message, with the text in IG_DM_TEXT, into the thread with the
account the owner named, who is notified and can read it before the unsend, then the unsend.
Five live requests, six with a bootstrap.

The owner named the account and approved direct messages to it on 2026-09-23 (ruling 30 in the
build plan). The thread is passed with ``--thread-fbid``, the one the Step 18 discovery run
created with that account. The text is read from ``IG_DM_TEXT`` and never written here or to a
log.

Step 18's live acceptance run. Everything goes through the public ``AsyncClient`` under the
default behavior: ``send_message``, ``thread_messages`` with ``newer_than_message_id`` set to
``--base-message-id``, ``unsend_message``, which opens the thread and then unsends, and
``thread_messages`` for the newest page confirming the message is gone. It answers:

- whether the newer-than read returns exactly the new message, the first live use of
  ``newer_than_message_id`` with a value, which Phase 4 needs
- whether that read finds the message by the ``offline_threading_id`` the send returned
- whether the unsend applies and the newest page no longer lists the message

No read goes before the send. The thread was left with nothing listed by the discovery run, whose
last message was unsent, so the base id is that message's id, passed in, and the step's live
budget had five requests left. That makes the newer-than read one whose base is an unsent
message, and the log says so. A failure of that read is recorded and the unsend still goes.

The only thing the probe adds is a counter around ``HttpxTransport.send``, which also refuses a
sixth request. Recorded: ids, counts, lengths, timings and each request's friendly name, status
and length. No text, no username, no name.

It sends nothing without ``--approve send-message``. Run it from `engine/` with:

   uv run python probes/direct_send_cycle.py --approve send-message --thread-fbid FBID \\
      --base-message-id MESSAGE_ID
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from _probe_support import SESSION_PATH, load_env, report_run

from dumpstagram._core.direct import find_sent_message
from dumpstagram._private.transport import HttpxTransport, Request, Response
from dumpstagram.aio import AsyncClient
from dumpstagram.errors import DumpstagramError
from dumpstagram.models import Message, Page
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE", "IG_DM_TEXT")

REQUEST_CAP = 5


def describe(page: Page[Message]) -> list[dict[str, object]]:
   return [
      {
         "id": message.id,
         "offline_threading_id": message.offline_threading_id,
         "sender_fbid": message.sender.fbid,
         "content_type": message.content_type,
         "sent_at": message.sent_at.isoformat(),
         "text_length": len(message.text) if message.text is not None else None,
      }
      for message in page.items
   ]


async def run(arguments: argparse.Namespace) -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}

   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT")
   text = environment.get("IG_DM_TEXT", "")
   approved = arguments.approve == "send-message"

   report: dict[str, object] = {
      "session_path": str(session_path),
      "approved": approved,
      "thread_fbid": arguments.thread_fbid,
      "newer_than_base": arguments.base_message_id,
      "newer_than_base_is": "the discovery run's message, unsent before this run",
   }

   if not approved:
      report["failed_with"] = "not approved, pass --approve send-message"
      report_run("direct-send-cycle-refused", report)

      return 2

   if not text:
      report["failed_with"] = "no IG_DM_TEXT in .env"
      report_run("direct-send-cycle-failed", report)

      return 2

   session = Session.load(session_path)
   sent: list[dict[str, object]] = []
   started_at = time.monotonic()
   original_send = HttpxTransport.send

   async def counted_send(transport: HttpxTransport, request: Request) -> Response:
      if len(sent) >= REQUEST_CAP:
         raise RuntimeError(f"refusing request {len(sent) + 1}, the cap is {REQUEST_CAP}")

      entry: dict[str, object] = {
         "name": request.headers.get("x-fb-friendly-name", "document"),
         "offset_ms": int((time.monotonic() - started_at) * 1000),
      }
      sent.append(entry)

      response = await original_send(transport, request)
      entry["status"] = response.status_code
      entry["length"] = len(response.content)

      return response

   HttpxTransport.send = counted_send  # type: ignore[method-assign]
   report["requests"] = sent
   report["text_length"] = len(text)

   try:
      async with AsyncClient(session, user_agent=user_agent) as client:
         created = await client.send_message(arguments.thread_fbid, text)
         report["sent"] = {
            "id": created.id,
            "sent_at": created.sent_at.isoformat(),
            "offline_threading_id": created.offline_threading_id,
         }

         try:
            newer = await client.thread_messages(
               arguments.thread_fbid, newer_than_message_id=arguments.base_message_id
            )
         except DumpstagramError as failure:
            report["newer_than_failed_with"] = type(failure).__name__
            report["newer_than_failure_text"] = str(failure)[:200]
         else:
            found = find_sent_message(newer.items, created.offline_threading_id)
            report["newer_than_page"] = describe(newer)
            report["newer_than_has_next_page"] = newer.has_next_page
            report["newer_than_is_exactly_the_new_message"] = [
               message.id for message in newer.items
            ] == [created.id]
            report["found_by_offline_threading_id"] = found is not None and found.id == created.id

         await client.unsend_message(arguments.thread_fbid, created.id)
         report["unsend_answered"] = "applied"

         after = await client.thread_messages(arguments.thread_fbid)
         report["newest_after_unsend"] = describe(after)
         report["gone_after_unsend"] = all(message.id != created.id for message in after.items)
   except DumpstagramError as failure:
      report["failed_with"] = type(failure).__name__
      report["failure_text"] = str(failure)[:200]
      report_run("direct-send-cycle-failed", report)

      return 3
   finally:
      HttpxTransport.send = original_send  # type: ignore[method-assign]

   session.save(session_path)

   report["requests_spent"] = len(sent)
   report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)

   report_run("direct-send-cycle", report)

   return 0


if __name__ == "__main__":
   parser = argparse.ArgumentParser()
   parser.add_argument("--approve", default="")
   parser.add_argument("--thread-fbid", required=True)
   parser.add_argument("--base-message-id", required=True)
   parsed = parser.parse_args()

   sys.exit(asyncio.run(run(parsed)))
