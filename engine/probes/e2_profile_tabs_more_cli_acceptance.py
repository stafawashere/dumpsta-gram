"""Read only. Ran 2026-09-27, 6 requests. The E2 batch 11a reads through the dumpsta command. Six requests, nine
at most.

The live acceptance of ``client.profiles.reels``, ``tagged`` and ``following``: the installed
console script run as ``uv run dumpsta --json`` subprocesses, never the library imported, as
``e2_follow_lists_cli_acceptance.py`` does. Every read is of the owner's own account, the viewer
id read from the session file.

   profile-reels VIEWER              1 request, the owner's reels tab, its first page
   tagged VIEWER                     1 request, the owner's tagged tab, its first page
   following VIEWER --pages 2        4 requests, two pages of the accounts the owner follows,
                                     each page followed by the relationship statuses of the
                                     accounts on it

Six when the stored tokens are accepted, and one more for each bootstrap or stale token
envelope (W57), so the counter in ``cli_request_counter/`` refuses the tenth. Each process has
its own pacer, so the probe spaces commands itself, 2.85 s after the previous one ended. It stops
on any nonzero exit.

All three reads send the site root as their referer where the browser sent the profile page, and
the two tabs go out without the suggested accounts query a tab click sends beside them, the
departures of W97 and W99, so this is their live check. Reading one's own tabs and list is
visible to nobody, and the statuses request changes nothing.

Recorded: exit codes, error class names, the requests each command sent, counts, the overlap
between the two following pages, booleans, cursor values that are numeric offsets, and timings.
No id, code, username or name leaves the subprocess's output into the log.

Run it from ``engine/`` with:

   uv run python probes/e2_profile_tabs_more_cli_acceptance.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

from _probe_support import ENGINE_ROOT, SESSION_PATH, load_env, report_run

from dumpstagram.session import Session

REQUEST_CAP = 9
READ_GAP_SECONDS = 2.85
FOLLOWING_PAGE_SIZE = 12
COUNTER_DIRECTORY = Path(__file__).resolve().parent / "cli_request_counter"
ENVIRONMENT_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE")


def requests_sent(request_log: Path) -> list[dict[str, Any]]:
   if not request_log.exists():
      return []

   return [json.loads(line) for line in request_log.read_text(encoding="utf-8").splitlines()]


def dumpsta(
   step_number: int,
   arguments: list[str],
   session_path: Path,
   user_agent: str | None,
   request_log: Path,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
   command = ["uv", "run", "dumpsta", "--session", str(session_path), "--json", *arguments]

   if user_agent:
      command += ["--user-agent", user_agent]

   child_environment = {
      **os.environ,
      "PYTHONPATH": str(COUNTER_DIRECTORY),
      "DUMPSTA_PROBE_REQUEST_LOG": str(request_log),
      "DUMPSTA_PROBE_REQUEST_CAP": str(REQUEST_CAP),
      "DUMPSTA_PROBE_STEP": str(step_number),
   }
   launched_at = time.monotonic()
   completed = subprocess.run(
      command, cwd=ENGINE_ROOT, env=child_environment, capture_output=True, text=True
   )
   sent = [entry for entry in requests_sent(request_log) if entry["step"] == str(step_number)]
   step: dict[str, Any] = {
      "step": step_number,
      "command": arguments[0],
      "exit": completed.returncode,
      "requests": len(sent),
      "sent": [
         {key: entry.get(key) for key in ("host", "method", "name", "status", "failed_with")}
         for entry in sent
      ],
      "elapsed_ms": int((time.monotonic() - launched_at) * 1000),
   }

   if completed.returncode != 0:
      lines = [line for line in completed.stderr.splitlines() if line.strip()]
      step["error_class"] = lines[0].split(":")[0] if lines else None

   payload = None

   if completed.stdout.strip():
      try:
         payload = json.loads(completed.stdout)
      except json.JSONDecodeError:
         step["stdout_was_not_json"] = True

   return step, payload


def summarise_reels(payload: dict[str, Any], viewer_id: str) -> dict[str, Any]:
   reels = payload["reels"]

   return {
      "reel_count": payload["reel_count"],
      "more_available": payload["more_available"],
      "product_types": sorted({reel["product_type"] for reel in reels}),
      "with_play_count": sum(reel["play_count"] is not None for reel in reels),
      "authored_by_the_viewer": sum(reel["author_id"] == viewer_id for reel in reels),
      "with_images": sum(bool(reel["images"]) for reel in reels),
   }


def summarise_tagged(payload: dict[str, Any], viewer_id: str) -> dict[str, Any]:
   posts = payload["posts"]

   return {
      "post_count": payload["post_count"],
      "more_available": payload["more_available"],
      "media_types": sorted({post["media_type"] for post in posts}),
      "authored_by_the_viewer": sum(post["author_id"] == viewer_id for post in posts),
      "distinct_authors": len({post["author_id"] for post in posts}),
      "with_caption": sum(post["caption"] is not None for post in posts),
   }


def summarise_following(payload: dict[str, Any]) -> dict[str, Any]:
   accounts = payload["accounts"]
   first_page_ids = {account["id"] for account in accounts[:FOLLOWING_PAGE_SIZE]}
   later_ids = [account["id"] for account in accounts[FOLLOWING_PAGE_SIZE:]]
   statuses = [account["friendship_status"] for account in accounts]
   cursor = payload["end_cursor"]
   cursor_is_an_offset = isinstance(cursor, str) and cursor.isdigit()

   return {
      "pages_read": payload["pages_read"],
      "account_count": payload["account_count"],
      "distinct_ids": len({account["id"] for account in accounts}),
      "second_page_accounts": len(later_ids),
      "overlap_with_first_page": sum(1 for account_id in later_ids if account_id in first_page_ids),
      "more_available": payload["more_available"],
      "end_cursor_is_a_numeric_offset": cursor_is_an_offset,
      "end_cursor": cursor if cursor_is_an_offset else None,
      "with_friendship_status": sum(status is not None for status in statuses),
      "following": sum(bool(status and status["following"]) for status in statuses),
   }


def main() -> int:
   environment = {key: value for key, value in load_env().items() if key in ENVIRONMENT_KEYS}
   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT")
   viewer_id = Session.load(session_path).ds_user_id
   report: dict[str, Any] = {"request_cap": REQUEST_CAP, "steps": [], "results": {}}
   outcome = "done"

   with tempfile.TemporaryDirectory() as scratch:
      request_log = Path(scratch) / "requests.jsonl"
      step_number = 0

      def run(label: str, arguments: list[str], summarise: Callable[..., Any]) -> Any:
         nonlocal step_number

         if step_number > 0:
            time.sleep(READ_GAP_SECONDS)

         step_number += 1
         step, payload = dumpsta(step_number, arguments, session_path, user_agent, request_log)
         step["label"] = label
         report["steps"].append(step)
         print(f"step {step_number} {label}: exit {step['exit']}, {step['requests']} requests")

         if step["exit"] != 0 or payload is None:
            return None

         report["results"][label] = summarise(payload)

         return payload

      plan: list[tuple[str, list[str], Callable[..., Any]]] = [
         (
            "profile-reels",
            ["profile-reels", viewer_id],
            partial(summarise_reels, viewer_id=viewer_id),
         ),
         ("tagged", ["tagged", viewer_id], partial(summarise_tagged, viewer_id=viewer_id)),
         ("following", ["following", viewer_id, "--pages", "2"], summarise_following),
      ]

      for label, arguments, summarise in plan:
         if run(label, arguments, summarise) is None:
            outcome = "stopped"
            break

      report["requests_spent"] = len(requests_sent(request_log))

   report["outcome"] = outcome
   report_run(
      "e2-profile-tabs-more-cli" if outcome == "done" else "e2-profile-tabs-more-cli-stopped",
      report,
   )

   return 0 if outcome == "done" else 3


if __name__ == "__main__":
   sys.exit(main())
