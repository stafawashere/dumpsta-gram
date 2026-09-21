"""Read only. One live request, or two if the stored tokens are stale and re-bootstrap fires.

Build plan Step 9, the second half of the Phase 1 stop condition. It loads the session file
`adopt_and_save.py` wrote, in a process that never saw that one's memory, and makes an
authenticated GraphQL call without re-adopting. Phase 1 is done when this succeeds.

**No credential is read from `.env` here.** Every cookie and every token comes off the disk,
which is the whole claim. `.env` is consulted only for `IG_THREAD_FBID`, `IG_USER_AGENT` and
`IG_SESSION_FILE`, none of which identify an account, and the probe fails rather than
proceeding if the file carries no `fb_dtsg`, because a session that bootstraps on load proves
persistence of the cookies and nothing about the tokens.

A re-bootstrap is a result, not a failure. The stored `fb_dtsg` changing across the call is
the only measurement anyone has of the token-lifetime question, whose lower bound is 16
minutes with no upper bound. The refreshed token is deliberately not written back, so that a
later run still measures the age of the token the first probe saved.

The log records lengths, counts, ages and timings. It never records a token, a cookie, a
message body or a name.

Run it from `engine/` with:

   uv run python probes/reload_and_call.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from _probe_support import (
   SESSION_PATH,
   THREAD_FBID,
   describe_page,
   load_env,
   report_run,
)

from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.smoke import read_one_thread_page
from dumpstagram._private.transport import HttpxTransport, cookies_for
from dumpstagram.errors import DumpstagramError
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_THREAD_FBID", "IG_USER_AGENT", "IG_SESSION_FILE")


def stored_token_age_seconds(session: Session) -> float | None:
   if session.bootstrapped_at is None:
      return None

   bootstrapped_at = session.bootstrapped_at

   if bootstrapped_at.tzinfo is None:
      bootstrapped_at = bootstrapped_at.replace(tzinfo=UTC)

   return (datetime.now(UTC) - bootstrapped_at).total_seconds()


async def run() -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}

   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   thread_fbid = environment.get("IG_THREAD_FBID") or THREAD_FBID
   user_agent_override = environment.get("IG_USER_AGENT")

   report: dict[str, object] = {
      "session_path": str(session_path),
      "credentials_read_from_env": False,
      "thread_fbid_length": len(thread_fbid),
      "user_agent_from_env": user_agent_override is not None,
   }

   if not session_path.exists():
      report["failed_with"] = "no session file, run probes/adopt_and_save.py first"

      report_run("reload-and-call-failed", report)

      return 2

   try:
      session = Session.load(session_path)
   except DumpstagramError as failure:
      report["failed_with"] = type(failure).__name__

      report_run("reload-and-call-failed", report)

      return 2

   token_from_the_file = session.fb_dtsg

   report["loaded_fb_dtsg_length"] = len(token_from_the_file) if token_from_the_file else None
   report["loaded_lsd_length"] = len(session.lsd) if session.lsd else None
   report["loaded_app_id"] = session.app_id
   report["loaded_spin_revision"] = session.spin.revision if session.spin else None
   report["stored_token_age_seconds"] = stored_token_age_seconds(session)

   if not token_from_the_file:
      report["failed_with"] = "session file carries no fb_dtsg, so the call would re-bootstrap"

      report_run("reload-and-call-failed", report)

      return 4

   pacer = Pacer()
   read_arguments = {"user_agent": user_agent_override} if user_agent_override else {}

   transport = HttpxTransport(cookies=cookies_for(session), proxy=session.proxy)
   started_at = time.monotonic()

   try:
      async with PacedSender(transport, pacer) as sender:
         parsed = await read_one_thread_page(sender, session, thread_fbid, **read_arguments)
   except DumpstagramError as failure:
      report["failed_with"] = type(failure).__name__
      report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)

      report_run("reload-and-call-failed", report)

      return 3

   re_bootstrapped = session.fb_dtsg != token_from_the_file

   report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
   report["re_bootstrapped"] = re_bootstrapped
   report["requests_spent"] = 2 if re_bootstrapped else 1
   report["stored_tokens_were_accepted"] = not re_bootstrapped
   report["page"] = describe_page(parsed)

   report_run("reload-and-call", report)

   return 0


if __name__ == "__main__":
   sys.exit(asyncio.run(run()))
