"""Writes twice, on the owner's own post only. Five live requests, six with a bootstrap.

One unlike and one like, or one like and one unlike, of the post the owner names with
``--code``, approved by the owner on 2026-09-23 for this one run. The post ends in the state it
started in. The change shows in the post's likers list to whoever can see the post for the
roughly half a minute between the two writes.

Step 15's live acceptance run. Everything goes through the public ``AsyncClient`` under the
default behavior: ``post``, then the write that moves the post away from its starting state,
``post`` confirming ``has_liked`` flipped and ``like_count`` moved by one, the reversing write,
and ``post`` confirming both are back. The build plan wrote it like first, which assumed a post
the owner had not liked. The owner's posts all read as liked, so the order follows the state.

The only thing the probe adds is a counter around ``HttpxTransport.send``, which also refuses a
seventh request. It refuses to write unless the post the first read returns is the viewer's
own. Recorded: the post's ``pk``, ``has_liked`` and ``like_count`` at each read, each request's
friendly name, status and length, and timings. No caption, no username, no text.

It sends nothing without ``--approve like``. Run it from `engine/` with:

   uv run python probes/like_cycle.py --approve like --code <shortcode of the owner's own post>
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from _probe_support import SESSION_PATH, load_env, report_run

from dumpstagram._private.transport import HttpxTransport, Request, Response
from dumpstagram.aio import AsyncClient
from dumpstagram.errors import DumpstagramError
from dumpstagram.models import PostDetail
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE")

REQUEST_CAP = 6


def describe(post: PostDetail) -> dict[str, object]:
   return {"pk": post.pk, "has_liked": post.has_liked, "like_count": post.like_count}


async def run(approved: bool, code: str) -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}

   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT")

   report: dict[str, object] = {"session_path": str(session_path), "approved": approved}

   if not approved:
      report["failed_with"] = "not approved, pass --approve like"
      report_run("like-cycle-refused", report)

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
   reads: list[dict[str, object]] = []
   report["reads"] = reads
   report["requests"] = sent

   try:
      async with AsyncClient(session, user_agent=user_agent) as client:
         before = await client.post(code)
         reads.append(describe(before))

         is_own_post = before.author.id == session.ds_user_id

         if not is_own_post:
            report["stopped_before_writing"] = "the post is not the viewer's own"
            report_run("like-cycle-stopped", report)

            return 4

         away, back = (
            (client.unlike, client.like) if before.has_liked else (client.like, client.unlike)
         )
         report["order"] = [away.__name__, back.__name__]

         await away(before.pk)
         middle = await client.post(code)
         reads.append(describe(middle))

         await back(before.pk)
         after = await client.post(code)
         reads.append(describe(after))
   except DumpstagramError as failure:
      report["failed_with"] = type(failure).__name__
      report["failure_text"] = str(failure)[:200]
      report_run("like-cycle-failed", report)

      return 3
   finally:
      HttpxTransport.send = original_send  # type: ignore[method-assign]

   session.save(session_path)

   flipped_in_the_middle = middle.has_liked is not before.has_liked
   moved_by_one = abs(middle.like_count - before.like_count) == 1
   restored = after.has_liked is before.has_liked and after.like_count == before.like_count

   report["requests_spent"] = len(sent)
   report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
   report["flipped_in_the_middle"] = flipped_in_the_middle
   report["like_count_moved_by_one"] = moved_by_one
   report["ends_in_starting_state"] = restored

   report_run("like-cycle", report)

   return 0


if __name__ == "__main__":
   parser = argparse.ArgumentParser()
   parser.add_argument("--approve", default="")
   parser.add_argument("--code", required=True)
   arguments = parser.parse_args()

   sys.exit(asyncio.run(run(arguments.approve == "like", arguments.code)))
