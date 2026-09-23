"""Writes twice, on the owner's own post only. Five live requests, six at most.

One comment posted on the post the owner names with ``--pk`` and deleted again, approved by
the owner on 2026-09-23 for this one run. The comment is visible for about the 30 s write
spacing to anyone who can see the post, which on a private account is its approved followers.
The text is ``IG_COMMENT_TEXT`` from the root ``.env`` and never appears in this file or a log.

Step 16's live acceptance run. Everything goes through the public ``AsyncClient`` under the
default behavior: ``comments``, ``comment``, ``comments`` confirming the returned id is listed
with the same text and the viewer as its author, ``delete_comment``, and ``comments``
confirming the id is gone and the page is back to the ids it started with.

The account must end as it started. When ``comment`` raises, the page is read and a viewer
comment that was not there before is deleted. When ``delete_comment`` raises, the REST route
the bundle also compiles is tried once, and if that fails too the log names the comment id
still up. The only thing the probe adds to the library is a counter around
``HttpxTransport.send``, which refuses a seventh request.

Recorded: comment ids, counts, whether the text and the author match, whether ``created_at``
is within five minutes of the clock, each request's friendly name, status and length, and
timings. No comment text and no username.

It sends nothing without ``--approve comment``. Run it from `engine/` with:

   uv run python probes/comment_cycle.py --approve comment --pk <pk of the owner's own post>
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from _probe_support import SESSION_PATH, load_env, report_run
from comment_discovery import build_rest_delete

from dumpstagram._core.writing import send_write
from dumpstagram._private.transport import HttpxTransport, Request, Response, WriteRequest
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT
from dumpstagram.aio import AsyncClient
from dumpstagram.errors import DumpstagramError
from dumpstagram.models import Comment, Page
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE", "IG_COMMENT_TEXT")

REQUEST_CAP = 6

CLOCK_WINDOW_SECONDS = 300


def describe(page: Page[Comment], viewer_id: str) -> dict[str, object]:
   return {
      "comment_ids": [comment.id for comment in page],
      "viewer_comment_ids": [comment.id for comment in page if comment.author.id == viewer_id],
      "has_next_page": page.has_next_page,
   }


async def run(approved: bool, pk: str) -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}

   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT")
   comment_text = environment.get("IG_COMMENT_TEXT", "")

   report: dict[str, object] = {"post_pk": pk, "approved": approved}

   if not approved:
      report["failed_with"] = "not approved, pass --approve comment"
      report_run("comment-cycle-refused", report)

      return 2

   if not comment_text:
      report["failed_with"] = "no IG_COMMENT_TEXT in .env"
      report_run("comment-cycle-failed", report)

      return 2

   session = Session.load(session_path)
   viewer_id = session.ds_user_id
   sent: list[dict[str, object]] = []
   started_at = time.monotonic()
   original_send = HttpxTransport.send

   async def counted_send(transport: HttpxTransport, request: Request) -> Response:
      if len(sent) >= REQUEST_CAP:
         raise RuntimeError(f"refusing request {len(sent) + 1}, the cap is {REQUEST_CAP}")

      entry: dict[str, object] = {
         "name": request.headers.get("x-fb-friendly-name", request.url.split("?")[0][-60:]),
         "offset_ms": int((time.monotonic() - started_at) * 1000),
      }
      sent.append(entry)

      response = await original_send(transport, request)
      entry["status"] = response.status_code
      entry["length"] = len(response.content)

      return response

   HttpxTransport.send = counted_send  # type: ignore[method-assign]
   reads: list[dict[str, object]] = []
   left_up: list[str] = []
   report["reads"] = reads
   report["requests"] = sent
   report["comments_left_up"] = left_up

   try:
      async with AsyncClient(session, user_agent=user_agent) as client:
         before = await client.comments(pk)
         reads.append(describe(before, viewer_id))
         ids_before = {comment.id for comment in before}

         try:
            created = await client.comment(pk, comment_text)
         except Exception as failure:
            report["comment_failed_with"] = type(failure).__name__
            report["comment_failure_text"] = str(failure)[:200]
            after_failure = await client.comments(pk)
            reads.append(describe(after_failure, viewer_id))
            strays = [
               comment.id
               for comment in after_failure
               if comment.author.id == viewer_id and comment.id not in ids_before
            ]

            for stray_id in strays:
               await client.delete_comment(pk, stray_id)

            report_run("comment-cycle-failed", report)

            return 3

         created_at_offset = abs((datetime.now(UTC) - created.created_at).total_seconds())
         report["created"] = {
            "id": created.id,
            "text_matches": created.text == comment_text,
            "author_is_viewer": created.author.id == viewer_id,
            "created_at_offset_seconds": int(created_at_offset),
            "created_at_within_window": created_at_offset < CLOCK_WINDOW_SECONDS,
            "counts_absent": created.like_count is None and created.reply_count is None,
         }

         middle = await client.comments(pk)
         reads.append(describe(middle, viewer_id))
         listed = next((comment for comment in middle if comment.id == created.id), None)
         listed_text_matches = listed is not None and listed.text == comment_text
         listed_author_is_viewer = listed is not None and listed.author.id == viewer_id
         report["listed"] = listed is not None
         report["listed_with_same_text_and_viewer"] = (
            listed_text_matches and listed_author_is_viewer
         )

         try:
            await client.delete_comment(pk, created.id)
         except DumpstagramError as failure:
            report["delete_failed_with"] = type(failure).__name__
            report["delete_failure_code"] = getattr(failure, "code", None)
            fallback = build_rest_delete(session, pk, created.id, user_agent or DEFAULT_USER_AGENT)

            try:
               await send_write(
                  client._sender, session, WriteRequest(fallback, "rest_delete_fallback")
               )
               report["rest_fallback"] = "answered without an error"
            except DumpstagramError as fallback_failure:
               report["rest_fallback"] = type(fallback_failure).__name__

         after = await client.comments(pk)
         reads.append(describe(after, viewer_id))
         ids_after = {comment.id for comment in after}

         if created.id in ids_after:
            left_up.append(created.id)
   except DumpstagramError as failure:
      report["failed_with"] = type(failure).__name__
      report["failure_text"] = str(failure)[:200]
      report_run("comment-cycle-failed", report)

      return 3
   finally:
      HttpxTransport.send = original_send  # type: ignore[method-assign]

   session.save(session_path)

   report["requests_spent"] = len(sent)
   report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
   report["gone_after_delete"] = created.id not in ids_after
   report["ends_in_starting_state"] = ids_after == ids_before

   report_run("comment-cycle", report)

   return 0


if __name__ == "__main__":
   parser = argparse.ArgumentParser()
   parser.add_argument("--approve", default="")
   parser.add_argument("--pk", required=True)
   arguments = parser.parse_args()

   sys.exit(asyncio.run(run(arguments.approve == "comment", arguments.pk)))
