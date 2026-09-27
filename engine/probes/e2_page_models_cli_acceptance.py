"""Read only. The E2 batch 9 inbox page load through the dumpsta command. 94 requests, 110 at most.

The live acceptance of the direct inbox's page load under the default behavior, which
``client.direct.notes``, ``inbox`` and ``unread_counts`` read from since E2 batch 9 (W87): the
installed console script run as ``uv run dumpsta --json`` subprocesses, never the library
imported, as ``e2_direct_read_cli_acceptance.py`` does.

   note list             31 requests, one inbox page load
   inbox --pages 2       32 requests, one inbox page load and the next page query
   unread                31 requests, one inbox page load

One inbox page load is the document, the ten queries of the direct block at once, the badge
count, the stories tray, one quick promotion call, one thread detail per row of the first page,
fifteen when the inbox has that many, and the pending follow requests with the activity feed:
31 with a full first page. The page load's cookie sync tail goes out 4 to 10 s after the
document, and a command ends before that, so it is ASSUMED to send none; the cap leaves room for
four per step in case one does. The counter in ``cli_request_counter/`` refuses the 111th. Each
process has its own pacer, so the probe spaces commands itself, 2.85 s after the previous one
ended. It stops on any nonzero exit.

What each step checks: that the ten block queries went out once each, that no request went to
``/api/v1/news/inbox_seen/``, which the counter records by path, and how many thread details went
out against the rows the inbox step listed. Nothing opens a thread, and no request marks
anything seen. Recorded: exit codes, error class names, the requests each command sent by
friendly name or recorded path, counts, booleans and timings. No note text, title, username,
name or snippet leaves the subprocess's output into the log.

Run it from ``engine/`` with:

   uv run python probes/e2_page_models_cli_acceptance.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

from _probe_support import ENGINE_ROOT, SESSION_PATH, load_env, report_run

REQUEST_CAP = 110
READ_GAP_SECONDS = 2.85
COUNTER_DIRECTORY = Path(__file__).resolve().parent / "cli_request_counter"
ENVIRONMENT_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE")

BLOCK_QUERIES = (
   "PolarisAutomaticPreviewsDisabledContextProviderQuery",
   "useFeatureLimitsOffMsysQuery",
   "useIGDSystemFolderUnreadThreadCountQuery",
   "PolarisDirectInboxQuery",
   "IGPresenceUnifiedSetupQuery",
   "PolarisDirectInboxQPInterstitialQuery",
   "IGDThreadListHeaderAccountSwitcherOffMsysQuery",
   "PolarisViewerSettingsQuery",
   "IGDInboxTrayQuery",
)
"""The direct block by friendly name. The unread rows query goes out twice, once per folder."""

THREAD_DETAIL = "IGDThreadDetailQuery"
NEXT_PAGE = "IGDThreadListOffMsysPaginationQuery"
INBOX_SEEN_PATH = "/api/v1/news/inbox_seen/"
ACCOUNT_READ_PATHS = ("/api/v1/friendships/pending/", "/api/v1/news/inbox/")


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
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
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
      "command": " ".join(arguments[:2]) if arguments[0] == "note" else arguments[0],
      "exit": completed.returncode,
      "requests": len(sent),
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

   return step, sent, payload


def summarise_burst(sent: list[dict[str, Any]]) -> dict[str, Any]:
   names = Counter(str(entry.get("path") or entry.get("name")) for entry in sent)
   hosts = Counter(str(entry.get("host")) for entry in sent)
   block_counts = {name: names[name] for name in BLOCK_QUERIES}
   unread_rows_twice = block_counts["useIGDSystemFolderUnreadThreadCountQuery"] == 2
   every_other_once = all(
      count == 1
      for name, count in block_counts.items()
      if name != "useIGDSystemFolderUnreadThreadCountQuery"
   )

   return {
      "sent_by_name": dict(sorted(names.items())),
      "hosts": dict(sorted(hosts.items())),
      "block_complete": unread_rows_twice and every_other_once,
      "thread_details": names[THREAD_DETAIL],
      "account_reads": sum(names[path] for path in ACCOUNT_READ_PATHS),
      "inbox_seen_sent": names[INBOX_SEEN_PATH],
      "next_pages": names[NEXT_PAGE],
      "failed": sum(1 for entry in sent if entry.get("failed_with")),
      "not_200": sum(1 for entry in sent if entry.get("status") not in (200, None)),
   }


def summarise_notes(payload: dict[str, Any]) -> dict[str, Any]:
   return {"note_count": payload["note_count"], "has_own_note": payload["own_note_id"] is not None}


def summarise_inbox(payload: dict[str, Any]) -> dict[str, Any]:
   threads = payload["threads"]

   return {
      "pages_read": payload["pages_read"],
      "thread_count": payload["thread_count"],
      "first_page_rows": min(len(threads), 15),
      "distinct_thread_fbids": len({thread["thread_fbid"] for thread in threads}),
      "more_available": payload["more_available"],
   }


def summarise_unread(payload: dict[str, Any]) -> dict[str, Any]:
   return {key: payload[key] for key in ("inbox", "pending", "inbox_has_more", "pending_has_more")}


def main() -> int:
   environment = {key: value for key, value in load_env().items() if key in ENVIRONMENT_KEYS}
   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT")
   plan = [
      (["note", "list"], summarise_notes),
      (["inbox", "--pages", "2"], summarise_inbox),
      (["unread"], summarise_unread),
   ]
   report: dict[str, Any] = {"request_cap": REQUEST_CAP, "steps": [], "results": {}}
   outcome = "done"

   with tempfile.TemporaryDirectory() as scratch:
      request_log = Path(scratch) / "requests.jsonl"

      for step_number, (arguments, summarise) in enumerate(plan, start=1):
         if step_number > 1:
            time.sleep(READ_GAP_SECONDS)

         step, sent, payload = dumpsta(
            step_number, arguments, session_path, user_agent, request_log
         )
         step["burst"] = summarise_burst(sent)
         report["steps"].append(step)
         print(
            f"step {step_number} {step['command']}: exit {step['exit']}, "
            f"{step['requests']} requests, {step['burst']['thread_details']} thread details, "
            f"inbox_seen {step['burst']['inbox_seen_sent']}"
         )

         failed = step["exit"] != 0 or payload is None

         if failed:
            outcome = "stopped"
            break

         report["results"][step["command"]] = summarise(payload)

      report["requests_spent"] = len(requests_sent(request_log))

   steps = report["steps"]
   inbox = report["results"].get("inbox")
   report["no_inbox_seen_anywhere"] = all(step["burst"]["inbox_seen_sent"] == 0 for step in steps)
   report["every_block_complete"] = all(step["burst"]["block_complete"] for step in steps)

   if inbox is not None:
      report["details_match_the_first_page"] = all(
         step["burst"]["thread_details"] == inbox["first_page_rows"] for step in steps
      )

   checks_held = report["no_inbox_seen_anywhere"] and report["every_block_complete"]

   if outcome == "done" and not checks_held:
      outcome = "checks-failed"

   report["outcome"] = outcome
   report_run(
      "e2-page-models-cli" if outcome == "done" else f"e2-page-models-cli-{outcome}", report
   )

   return 0 if outcome == "done" else 3


if __name__ == "__main__":
   sys.exit(main())
