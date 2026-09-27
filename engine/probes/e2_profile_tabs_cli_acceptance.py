"""Read only. Ran 2026-09-27, 7 requests. The E2 batch 2 reads through the dumpsta command. Five requests, seven
with --next-page-account, twelve at most.

The live acceptance of ``client.profiles.posts``, ``highlights``, ``suggested`` and
``suggested_for_you``: the installed console script run as ``uv run dumpsta --json``
subprocesses, never the library imported, as ``e2_direct_read_cli_acceptance.py`` does.

   profile --by-id VIEWER      1 request, for the owner's username, the viewer id read from the
                               session file
   posts OWNER                 1 request, the owner's grid, which fits one page and answered
                               beside field errors on 2026-09-27, so it checks W52 live
   highlights VIEWER           1 request
   suggested VIEWER            1 request
   suggested-for-you           1 request
   posts ACCOUNT --pages 2     2 requests, only with --next-page-account, a public account the
                               owner's timeline shows (W43), for the grid's next page

Five when the stored tokens are accepted, and one more for each bootstrap, so the counter in
``cli_request_counter/`` refuses the thirteenth. Each process has its own pacer, so the probe
spaces commands itself, 2.85 s after the previous one ended. It stops on any nonzero exit.

Nothing here opens a story or marks anything seen. Recorded: exit codes, error class names, the
requests each command sent, counts, booleans, cursor lengths and timings. No username, name,
caption, title or reason leaves the subprocess's output into the log, and the account passed to
--next-page-account is not written either.

Run it from ``engine/`` with:

   uv run python probes/e2_profile_tabs_cli_acceptance.py
   uv run python probes/e2_profile_tabs_cli_acceptance.py --next-page-account USERNAME
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from _probe_support import ENGINE_ROOT, SESSION_PATH, load_env, report_run

from dumpstagram.session import Session

REQUEST_CAP = 12
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


def summarise_profile(payload: dict[str, Any]) -> dict[str, Any]:
   profile = payload["profile"]

   return {"media_count": profile["media_count"], "is_private": profile["is_private"]}


def summarise_grid(payload: dict[str, Any]) -> dict[str, Any]:
   posts = payload["posts"]
   cursor = payload["end_cursor"]

   return {
      "pages_read": payload["pages_read"],
      "post_count": payload["post_count"],
      "distinct_pks": len({post["pk"] for post in posts}),
      "more_available": payload["more_available"],
      "end_cursor_length": len(cursor) if cursor else None,
      "is_seen_values": sorted({str(post["is_seen"]) for post in posts}),
      "authors": len({post["author"]["id"] for post in posts}),
      "media_types": sorted({post["media_type"] for post in posts}),
   }


def summarise_highlights(payload: dict[str, Any]) -> dict[str, Any]:
   highlights = payload["highlights"]

   return {
      "highlights": len(highlights),
      "has_more": payload["has_more"],
      "ids_prefixed": all(highlight["id"].startswith("highlight:") for highlight in highlights),
   }


def summarise_accounts(payload: dict[str, Any]) -> dict[str, Any]:
   rows = [entry.get("account", entry) for entry in payload["accounts"]]

   return {
      "accounts": len(rows),
      "distinct_ids": len({row["id"] for row in rows}),
      "is_private_values": sorted({str(row["is_private"]) for row in rows}),
      "with_friendship_status": sum(row["friendship_status"] is not None for row in rows),
      "following": sum(
         bool(row["friendship_status"] and row["friendship_status"]["following"]) for row in rows
      ),
      "with_a_reason": sum(bool(entry.get("reason")) for entry in payload["accounts"]),
   }


def main() -> int:
   parser = argparse.ArgumentParser(description=__doc__)
   parser.add_argument(
      "--next-page-account",
      metavar="USERNAME",
      help="a public account the owner's timeline shows, whose grid has a second page",
   )
   options = parser.parse_args()

   environment = {key: value for key, value in load_env().items() if key in ENVIRONMENT_KEYS}
   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT")
   viewer_id = Session.load(session_path).ds_user_id
   report: dict[str, Any] = {
      "request_cap": REQUEST_CAP,
      "next_page_account_given": options.next_page_account is not None,
      "steps": [],
      "results": {},
   }
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

      profile = run("profile", ["profile", "--by-id", viewer_id], summarise_profile)
      username = profile["profile"]["username"] if profile is not None else None

      if username is None:
         outcome = "stopped"
         plan: list[tuple[str, list[str], Callable[..., Any]]] = []
      else:
         plan = [
            ("own posts", ["posts", username], summarise_grid),
            ("highlights", ["highlights", viewer_id], summarise_highlights),
            ("suggested", ["suggested", viewer_id], summarise_accounts),
            ("suggested-for-you", ["suggested-for-you"], summarise_accounts),
         ]

      wants_the_next_page = options.next_page_account is not None and username is not None

      if wants_the_next_page:
         plan.append(
            (
               "next page account posts",
               ["posts", str(options.next_page_account), "--pages", "2"],
               summarise_grid,
            )
         )

      for label, arguments, summarise in plan:
         if run(label, arguments, summarise) is None:
            outcome = "stopped"
            break

      report["requests_spent"] = len(requests_sent(request_log))

   report["outcome"] = outcome
   report_run("e2-profile-tabs-cli" if outcome == "done" else "e2-profile-tabs-cli-stopped", report)

   return 0 if outcome == "done" else 3


if __name__ == "__main__":
   sys.exit(main())
