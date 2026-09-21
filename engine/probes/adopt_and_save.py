"""Read only. Two live requests: one bootstrap page load, one thread message page.

Build plan Step 9, the first half of the Phase 1 stop condition. It adopts a browser session
from `.env` per ADR-0008, bootstraps it, proves the adopted session can actually read
something, writes the session to disk and exits. `reload_and_call.py` is the other half, and
it must run in a process that never saw this one's memory.

The read is not decoration. Without it, a failure in the second probe cannot be told apart
from credentials that were already dead when they were pasted into `.env`, which is the one
explanation that has nothing to do with persistence.

The session file holds a `sessionid`, which is a full account takeover token with no second
factor. It goes to `engine/state/session.json`, which the root `.gitignore` excludes, and
`Session.save` creates it owner-only. The probe reports the mode it observes rather than
trusting that.

Credentials come from `.env` at the repository root. The log records lengths, counts, modes
and timings. It never records a token, a cookie, a message body or a name.

Run it from `engine/` with:

   uv run python probes/adopt_and_save.py
"""

from __future__ import annotations

import asyncio
import stat
import sys
import time
from pathlib import Path

from _probe_support import (
   REQUIRED_CREDENTIAL_KEYS,
   SESSION_PATH,
   THREAD_FBID,
   describe_page,
   load_env,
   report_run,
   write_log,
)

from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.smoke import read_one_thread_page
from dumpstagram._private.transport import HttpxTransport, cookies_for
from dumpstagram.errors import DumpstagramError
from dumpstagram.session import Session


async def run() -> int:
   environment = load_env()

   missing = [key for key in REQUIRED_CREDENTIAL_KEYS if not environment.get(key)]
   if missing:
      write_log("adopt-and-save-failed", {"missing_env_keys": missing})
      print(f"missing required keys in .env: {', '.join(missing)}")

      return 2

   extra_cookies = {"mid": environment["IG_MID"]} if environment.get("IG_MID") else {}

   session = Session(
      sessionid=environment["IG_SESSIONID"],
      ds_user_id=environment["IG_DS_USER_ID"],
      csrftoken=environment["IG_CSRFTOKEN"],
      extra_cookies=extra_cookies,
   )

   thread_fbid = environment.get("IG_THREAD_FBID") or THREAD_FBID
   user_agent_override = environment.get("IG_USER_AGENT")
   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)

   pacer = Pacer()
   report: dict[str, object] = {
      "session_path": str(session_path),
      "thread_fbid_length": len(thread_fbid),
      "pacing_floor_seconds": pacer.pacing.floor_seconds,
      "pacing_mean_jitter_seconds": pacer.pacing.mean_jitter_seconds,
      "user_agent_from_env": user_agent_override is not None,
      "session_was_bootstrapped_before_the_call": session.fb_dtsg is not None,
   }

   read_arguments = {"user_agent": user_agent_override} if user_agent_override else {}

   transport = HttpxTransport(cookies=cookies_for(session), proxy=session.proxy)
   started_at = time.monotonic()

   try:
      async with PacedSender(transport, pacer) as sender:
         parsed = await read_one_thread_page(sender, session, thread_fbid, **read_arguments)
   except DumpstagramError as failure:
      report["failed_with"] = type(failure).__name__
      report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)

      report_run("adopt-and-save-failed", report)

      return 3

   report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
   report["requests_spent"] = 2
   report["page"] = describe_page(parsed)

   session.save(session_path)

   reloaded = Session.load(session_path)

   report["fb_dtsg_length"] = len(session.fb_dtsg) if session.fb_dtsg else None
   report["lsd_length"] = len(session.lsd) if session.lsd else None
   report["app_id"] = session.app_id
   report["spin_revision"] = session.spin.revision if session.spin else None
   report["bootstrapped_at"] = session.bootstrapped_at
   report["session_file_bytes"] = session_path.stat().st_size
   report["session_file_mode"] = stat.filemode(session_path.stat().st_mode)
   report["saved_session_reloads_equal"] = reloaded.to_dict() == session.to_dict()

   report_run("adopt-and-save", report)

   return 0


if __name__ == "__main__":
   sys.exit(asyncio.run(run()))
