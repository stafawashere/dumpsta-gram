"""Read only. Two live requests: one bootstrap page load, one thread message page.

Build plan Step 8. Unlike `live_repro_bootstrap_page.py`, which reimplements the request shape
inline, this one drives the library: `Session`, `HttpxTransport`, `PacedSender`, `bootstrap`,
`build_thread_page_request` and `classify`, in that order, through
`dumpstagram._core.smoke.read_one_thread_page`. What it answers is whether the layers are wired
to each other, not whether the protocol still works, which the older probe already covers.

Pacing is the library's own default, 2500 ms plus a mean 350 ms of jitter, so the gap between
the two requests is the 2850 ms mean the probe rules ask for rather than a sleep written here.

Credentials come from `.env` at the repository root. The log records lengths, counts and
timings. It never records a token, a cookie, a message body or a name.

Run it from `engine/` with:

   uv run python probes/end_to_end_read.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.smoke import read_one_thread_page
from dumpstagram._private.transport import HttpxTransport, cookies_for
from dumpstagram.errors import DumpstagramError
from dumpstagram.session import Session

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

THREAD_FBID = "17945046917948992"
"""The thread the measured runs used, overridable with `IG_THREAD_FBID`.

This is the thread's `fbid`, which is one of three ids the same thread has. The other two
return an empty page rather than an error.
"""

REQUIRED_KEYS = ("IG_SESSIONID", "IG_DS_USER_ID", "IG_CSRFTOKEN")


def load_env(path: Path) -> dict[str, str]:
   values: dict[str, str] = {}

   for raw_line in path.read_text(encoding="utf-8").splitlines():
      line = raw_line.strip()

      is_comment = line.startswith("#")
      has_assignment = "=" in line

      if line and not is_comment and has_assignment:
         key, _, value = line.partition("=")
         values[key.strip()] = value.strip().strip('"').strip("'")

   return values


def write_log(kind: str, payload: dict[str, object]) -> Path:
   LOG_DIR.mkdir(parents=True, exist_ok=True)
   stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
   path = LOG_DIR / f"{kind}-{stamp}.json"

   path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")

   return path


def describe_page(parsed: object) -> dict[str, object]:
   """Count what came back without recording any of it.

   The traversal is written out here rather than imported, because no parser exists yet and
   Step 8 deliberately does not add one. A path that stops resolving is reported as absent
   rather than raising, so the probe still produces a log.
   """

   if not isinstance(parsed, dict):
      return {"payload_is_an_object": False}

   data = parsed.get("data")
   thread_field = data.get("fetch__SlideThread") if isinstance(data, dict) else None
   thread = thread_field.get("as_ig_direct_thread") if isinstance(thread_field, dict) else None
   messages = thread.get("slide_messages") if isinstance(thread, dict) else None

   if not isinstance(messages, dict):
      return {
         "payload_is_an_object": True,
         "top_level_keys": sorted(parsed.keys()),
         "canonical_path_present": False,
      }

   edges = messages.get("edges") or []
   page_info = messages.get("page_info") or {}
   end_cursor = page_info.get("end_cursor")

   return {
      "payload_is_an_object": True,
      "top_level_keys": sorted(parsed.keys()),
      "canonical_path_present": True,
      "edge_count": len(edges),
      "has_next_page": page_info.get("has_next_page"),
      "end_cursor_length": len(end_cursor) if end_cursor else None,
   }


async def run() -> int:
   environment = load_env(ENV_PATH)

   missing = [key for key in REQUIRED_KEYS if not environment.get(key)]
   if missing:
      write_log("end-to-end-read-failed", {"missing_env_keys": missing})
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

   pacer = Pacer()
   report: dict[str, object] = {
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

      log_path = write_log("end-to-end-read-failed", report)
      print(json.dumps(report, indent=2, default=str))
      print(f"log written to {log_path}")

      return 3

   report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
   report["requests_spent"] = 2
   report["fb_dtsg_length"] = len(session.fb_dtsg) if session.fb_dtsg else None
   report["lsd_length"] = len(session.lsd) if session.lsd else None
   report["app_id"] = session.app_id
   report["spin_revision"] = session.spin.revision if session.spin else None
   report["bootstrapped_at"] = session.bootstrapped_at
   report["page"] = describe_page(parsed)

   log_path = write_log("end-to-end-read", report)
   print(json.dumps(report, indent=2, default=str))
   print(f"log written to {log_path}")

   return 0


if __name__ == "__main__":
   sys.exit(asyncio.run(run()))
