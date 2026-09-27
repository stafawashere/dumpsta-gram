"""Read only. The E2 batch 1 reads through the dumpsta command. Five requests, ten at most.

The live acceptance of ``client.direct.inbox``, ``message_requests`` and ``unread_counts``: the
installed console script run as ``uv run dumpsta --json`` subprocesses, never the library
imported, as ``posting_cli_acceptance.py`` does.

   inbox --pages 2       2 requests, the first page and the next one through the handed cursor
   message-requests      1 request
   unread                2 requests, the inbox folder and the pending folder

Five when the stored tokens are accepted, and one more for each bootstrap, so the counter in
``cli_request_counter/`` refuses the eleventh. Each process has its own pacer, so the probe
spaces commands itself, 2.85 s after the previous one ended. It stops on any nonzero exit.

Nothing here opens a thread or a request thread, so nothing is marked read or seen. Recorded:
exit codes, error class names, the requests each command sent, counts, booleans, cursor lengths
and timings. No title, username, name or snippet leaves the subprocess's output into the log.

Run it from ``engine/`` with:

   uv run python probes/e2_direct_read_cli_acceptance.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from _probe_support import ENGINE_ROOT, SESSION_PATH, load_env, report_run

REQUEST_CAP = 10
READ_GAP_SECONDS = 2.85
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
         {key: entry.get(key) for key in ("host", "name", "status", "failed_with")}
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


def summarise_inbox(payload: dict[str, Any]) -> dict[str, Any]:
   threads = payload["threads"]
   first_page_threads = threads[:15]
   cursor = payload["end_cursor"]
   activity = [thread["last_activity_at"] for thread in threads]
   is_newest_first = activity == sorted(activity, reverse=True)

   return {
      "pages_read": payload["pages_read"],
      "thread_count": payload["thread_count"],
      "distinct_thread_fbids": len({thread["thread_fbid"] for thread in threads}),
      "more_available": payload["more_available"],
      "end_cursor_length": len(cursor) if cursor else None,
      "unread_on_the_first_page": sum(thread["is_unread"] for thread in first_page_threads),
      "unread_in_all": sum(thread["is_unread"] for thread in threads),
      "pinned": sum(thread["is_pinned"] for thread in threads),
      "muted": sum(thread["is_muted"] for thread in threads),
      "groups": sum(thread["is_group"] for thread in threads),
      "participant_counts": sorted({len(thread["participants"]) for thread in threads}),
      "activity_descending": is_newest_first,
   }


def summarise_requests(payload: dict[str, Any]) -> dict[str, Any]:
   return {
      "pending": len(payload["pending"]),
      "spam": len(payload["spam"]),
      "pending_has_more": payload["pending_has_more"],
      "spam_has_more": payload["spam_has_more"],
   }


def summarise_unread(payload: dict[str, Any]) -> dict[str, Any]:
   return {key: payload[key] for key in ("inbox", "pending", "inbox_has_more", "pending_has_more")}


def main() -> int:
   environment = {key: value for key, value in load_env().items() if key in ENVIRONMENT_KEYS}
   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT")
   plan = [
      (["inbox", "--pages", "2"], summarise_inbox),
      (["message-requests"], summarise_requests),
      (["unread"], summarise_unread),
   ]
   report: dict[str, Any] = {"request_cap": REQUEST_CAP, "steps": [], "results": {}}
   outcome = "done"

   with tempfile.TemporaryDirectory() as scratch:
      request_log = Path(scratch) / "requests.jsonl"

      for step_number, (arguments, summarise) in enumerate(plan, start=1):
         if step_number > 1:
            time.sleep(READ_GAP_SECONDS)

         step, payload = dumpsta(step_number, arguments, session_path, user_agent, request_log)
         report["steps"].append(step)
         print(
            f"step {step_number} {arguments[0]}: exit {step['exit']}, {step['requests']} requests"
         )

         failed = step["exit"] != 0 or payload is None

         if failed:
            outcome = "stopped"
            break

         report["results"][arguments[0]] = summarise(payload)

      report["requests_spent"] = len(requests_sent(request_log))

   inbox = report["results"].get("inbox")
   unread = report["results"].get("unread")
   both_read = inbox is not None and unread is not None

   if both_read:
      report["first_page_unread_matches_the_inbox_count"] = (
         inbox["unread_on_the_first_page"] == unread["inbox"]
      )

   report["outcome"] = outcome
   report_run("e2-direct-read-cli" if outcome == "done" else "e2-direct-read-cli-stopped", report)

   return 0 if outcome == "done" else 3


if __name__ == "__main__":
   sys.exit(main())
