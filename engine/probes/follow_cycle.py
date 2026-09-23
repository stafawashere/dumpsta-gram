"""Writes twice, on the one account the owner named only. Five live requests, six with a
bootstrap.

One follow and one unfollow, or one unfollow and one follow, of the account whose id is passed
with ``--user-id``, approved by the owner on 2026-09-23 (ruling 30 in the build plan). It writes
only if the first read shows that account's username is ``IG_FOLLOW_TARGET`` from the root
``.env``. The account is notified of the follow, and the relationship ends as it started.

Step 17's live acceptance run. Everything goes through the public ``AsyncClient`` under the
default behavior: ``profile_by_id``, the write that moves the relationship away from where it
started, ``profile_by_id`` confirming ``friendship_status`` moved, the reversing write, and
``profile_by_id`` confirming it is back. From not following that is follow then unfollow, and
from following or a pending request it is unfollow then follow. It refuses to start on a
private account the viewer follows, because the follow that would restore it creates a request
the account has to approve.

The only thing the probe adds is a counter around ``HttpxTransport.send``, which also refuses a
seventh request. Recorded: the account id, ``is_private``, ``following`` and
``outgoing_request`` at each read, each request's friendly name, status and length, and
timings. No username, no name, no text.

It sends nothing without ``--approve follow``. Run it from `engine/` with:

   uv run python probes/follow_cycle.py --approve follow --user-id <the named account's id>
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
from dumpstagram.models import Profile
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE", "IG_FOLLOW_TARGET")

REQUEST_CAP = 6


def describe(profile: Profile) -> dict[str, object]:
   status = profile.friendship_status

   return {
      "id": profile.id,
      "is_private": profile.is_private,
      "following": status.following if status is not None else None,
      "outgoing_request": status.outgoing_request if status is not None else None,
   }


def relationship(profile: Profile) -> tuple[bool, bool] | None:
   status = profile.friendship_status

   if status is None:
      return None

   return status.following, status.outgoing_request


async def run(approved: bool, user_id: str) -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}

   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT")
   named_target = environment.get("IG_FOLLOW_TARGET", "")

   report: dict[str, object] = {"session_path": str(session_path), "approved": approved}

   if not approved:
      report["failed_with"] = "not approved, pass --approve follow"
      report_run("follow-cycle-refused", report)

      return 2

   if not named_target:
      report["failed_with"] = "no IG_FOLLOW_TARGET in .env"
      report_run("follow-cycle-failed", report)

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
         before = await client.profile_by_id(user_id)
         reads.append(describe(before))

         is_the_named_account = before.username == named_target
         starting = relationship(before)

         if not is_the_named_account or starting is None:
            report["stopped_before_writing"] = "the account read is not the one the owner named"
            report_run("follow-cycle-stopped", report)

            return 4

         following, requested = starting
         cannot_be_restored = before.is_private and following

         if cannot_be_restored:
            report["stopped_before_writing"] = "private and followed, a refollow would be a request"
            report_run("follow-cycle-stopped", report)

            return 4

         starts_connected = following or requested
         away, back = (
            (client.unfollow, client.follow)
            if starts_connected
            else (client.follow, client.unfollow)
         )
         report["order"] = [away.__name__, back.__name__]

         await away(user_id)
         middle = await client.profile_by_id(user_id)
         reads.append(describe(middle))

         await back(user_id)
         after = await client.profile_by_id(user_id)
         reads.append(describe(after))
   except DumpstagramError as failure:
      report["failed_with"] = type(failure).__name__
      report["failure_text"] = str(failure)[:200]
      report_run("follow-cycle-failed", report)

      return 3
   finally:
      HttpxTransport.send = original_send  # type: ignore[method-assign]

   session.save(session_path)

   report["requests_spent"] = len(sent)
   report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
   report["moved_in_the_middle"] = relationship(middle) != starting
   report["ends_in_starting_state"] = relationship(after) == starting

   report_run("follow-cycle", report)

   return 0


if __name__ == "__main__":
   parser = argparse.ArgumentParser()
   parser.add_argument("--approve", default="")
   parser.add_argument("--user-id", required=True)
   arguments = parser.parse_args()

   sys.exit(asyncio.run(run(arguments.approve == "follow", arguments.user_id)))
