"""Read only. Ran 2026-09-27, 3 requests. The E2 batch 11c reads through the dumpsta command. Three requests,
five at most.

The live acceptance of ``client.account.saved``, ``collections`` and ``close_friends``: the
installed console script run as ``uv run dumpsta --json`` subprocesses, never the library
imported, as ``e2_own_account_cli_acceptance.py`` does, on the owner's own account.

   saved                       1 request, the owner's saved "All posts" view, no bootstrap
   collections                 1 request, the owner's saved tab, and a bootstrap first when the
                               stored session holds no page token
   close-friends               1 request, the close friends settings screen's Bloks fetch, and a
                               bootstrap first when the stored session holds no page token or no
                               Bloks version id

Three when the stored tokens are accepted, and one more for each bootstrap, so the counter in
``cli_request_counter/`` refuses the sixth. Each process has its own pacer, so the probe spaces
commands itself, 2.85 s after the previous one ended. It stops on any nonzero exit.

The close friends page also sends a ``close_friend_count_updater`` action whose effect is
UNRESOLVED. Each command must send exactly one request of its own kind, which the probe checks
from the counter's log, so neither that action nor a second fetch can have gone out (W107).
Nothing here changes the account. Recorded: exit codes, error class names, the requests each
command sent, counts and booleans. No username, name, caption, id or URL leaves the subprocess's
output into the log, because the saved posts are other accounts' posts and the close friends are
other people.

Run it from ``engine/`` with:

   uv run python probes/e2_own_account_more_cli_acceptance.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from _probe_support import ENGINE_ROOT, SESSION_PATH, load_env, report_run

REQUEST_CAP = 5
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


def summarise_saved(payload: dict[str, Any]) -> dict[str, Any]:
   posts = payload["posts"]

   return {
      "posts": payload["post_count"],
      "listed": len(posts),
      "more_available": payload["more_available"],
      "product_types": dict(sorted(Counter(post["product_type"] for post in posts).items())),
      "liked": sum(post["has_liked"] is True for post in posts),
      "counts_flag_absent": sum(post["like_and_view_counts_disabled"] is None for post in posts),
      "carries_a_comment_count": any("comment_count" in post for post in posts),
      "every_post_has_a_code": all(bool(post["code"]) for post in posts),
   }


def summarise_collections(payload: dict[str, Any]) -> dict[str, Any]:
   collections = payload["collections"]

   return {
      "collections": payload["collection_count"],
      "more_available": payload["more_available"],
      "kinds": [collection["kind"] for collection in collections],
      "counted": sum(collection["media_count"] is not None for collection in collections),
      "covers": [len(collection["covers"]) for collection in collections],
   }


def summarise_close_friends(payload: dict[str, Any]) -> dict[str, Any]:
   accounts = payload["accounts"]

   return {
      "accounts": payload["account_count"],
      "listed": len(accounts),
      "verified": sum(account["is_verified"] is True for account in accounts),
      "every_id_is_digits": all(account["id"].isdigit() for account in accounts),
      "distinct_ids": len({account["id"] for account in accounts}),
   }


def one_answering_request_each(steps: list[dict[str, Any]]) -> dict[str, bool]:
   """Whether each command sent exactly one request of its own kind. A bootstrap's document load
   is ``/other`` and is not counted, so a second saved GET, a second saved tab query, or the close
   friends page's second fetch or its ``close_friend_count_updater`` action, which share the
   ``/async`` path, would each show here."""

   expected_name = {
      "saved": "/api",
      "collections": "PolarisProfileSavedTabContentQuery",
      "close-friends": "/async",
   }

   return {
      step["command"]: sum(
         sent.get("name") == expected_name[step["command"]] for sent in step["sent"]
      )
      == 1
      for step in steps
   }


def main() -> int:
   parser = argparse.ArgumentParser(description=__doc__)
   parser.parse_args()

   environment = {key: value for key, value in load_env().items() if key in ENVIRONMENT_KEYS}
   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT")
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
         ("saved posts", ["saved"], summarise_saved),
         ("saved collections", ["collections"], summarise_collections),
         ("close friends", ["close-friends"], summarise_close_friends),
      ]

      for label, arguments, summarise in plan:
         if run(label, arguments, summarise) is None:
            outcome = "stopped"
            break

      report["requests_spent"] = len(requests_sent(request_log))
      report["one_answering_request_per_command"] = one_answering_request_each(report["steps"])

   report["outcome"] = outcome
   kind = "e2-own-account-more-cli" if outcome == "done" else "e2-own-account-more-cli-stopped"
   report_run(kind, report)

   return 0 if outcome == "done" else 3


if __name__ == "__main__":
   sys.exit(main())
