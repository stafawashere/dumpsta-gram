"""Read only. Ran 2026-09-27, 3 requests. The E2 batch 8 reads through the dumpsta command. Three requests, six
at most.

The live acceptance of ``client.search.recent``, ``accounts`` and ``hashtag``: the installed
console script run as ``uv run dumpsta --json`` subprocesses, never the library imported, as
``e2_discovery_feeds_cli_acceptance.py`` does.

   recent-searches             1 request, the viewer's recent searches
   search QUERY                1 request, the accounts QUERY matches, non-personalised, sent
                               with --non-personalised since batch 11b made the personalised
                               query the default (W102)
   hashtag TAG                 1 request, the header of the hashtag TAG

QUERY and TAG come from ``IG_E2_SEARCH_QUERY`` and ``IG_E2_HASHTAG`` in the root ``.env``, both
``instagram`` when absent, as ``e2_search.py`` sent them, and neither is logged. A leading ``#`` on
the tag is dropped before the command sees it, since the command refuses one.

Three when the stored tokens are accepted, and one more for each bootstrap, so the counter in
``cli_request_counter/`` refuses the seventh. Each process has its own pacer, so the probe spaces
commands itself, 2.85 s after the previous one ended. It stops on any nonzero exit.

Nothing here is visible to another person, and nothing is opened, so no recent search is added.
The probe checks from the counter's log that each command sent exactly its own query and that
none sent the search box's container query, which no browser was observed to send (W83, W102).
Recorded: exit codes, error class names, the requests each command sent, counts and booleans.
No username, full name, keyword, query, tag or id leaves the subprocess's output into the log.

Run it from ``engine/`` with:

   uv run python probes/e2_search_cli_acceptance.py
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

REQUEST_CAP = 6
READ_GAP_SECONDS = 2.85
COUNTER_DIRECTORY = Path(__file__).resolve().parent / "cli_request_counter"
ENVIRONMENT_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE", "IG_E2_SEARCH_QUERY", "IG_E2_HASHTAG")
DEFAULT_TERM = "instagram"
EXPECTED_QUERY = {
   "recent-searches": "PolarisSearchNullStateQuery",
   "search": "PolarisSearchBoxNonProfiledRefetchableQuery",
   "hashtag": "PolarisHashtagHeaderActionButtonsQuery",
}
UNOBSERVED_QUERIES = ("PolarisSearchBoxContainerQuery",)


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


def summarise_recent(payload: dict[str, Any]) -> dict[str, Any]:
   entries = payload["entries"]
   kinds = [entry["kind"] for entry in entries]

   return {
      "entries": payload["entry_count"],
      "entries_counted_match": len(entries) == payload["entry_count"],
      "kinds": {kind: kinds.count(kind) for kind in sorted(set(kinds))},
      "every_account_entry_has_an_account": all(
         entry["account"] is not None for entry in entries if entry["kind"] == "user"
      ),
      "every_keyword_entry_has_text": all(
         bool(entry["keyword"]) for entry in entries if entry["kind"] == "keyword"
      ),
   }


def summarise_accounts(payload: dict[str, Any]) -> dict[str, Any]:
   accounts = payload["accounts"]

   return {
      "accounts": payload["account_count"],
      "accounts_counted_match": len(accounts) == payload["account_count"],
      "verified": sum(account["is_verified"] for account in accounts),
      "every_id_is_digits": all(account["id"].isdigit() for account in accounts),
      "any_privacy_flag": any(account["is_private"] is not None for account in accounts),
   }


def summarise_hashtag(payload: dict[str, Any]) -> dict[str, Any]:
   return {"id_is_digits": payload["hashtag"]["id"].isdigit()}


def each_command_sent_its_own_query(steps: list[dict[str, Any]]) -> bool:
   for step in steps:
      api_names = [sent.get("name") for sent in step["sent"] if sent.get("name")]
      expected = EXPECTED_QUERY.get(step["command"])

      if expected not in api_names:
         return False

   return True


def no_unobserved_query_sent(steps: list[dict[str, Any]]) -> bool:
   names = {str(sent.get("name")) for step in steps for sent in step["sent"]}

   return names.isdisjoint(UNOBSERVED_QUERIES)


def main() -> int:
   parser = argparse.ArgumentParser(description=__doc__)
   parser.parse_args()

   environment = {key: value for key, value in load_env().items() if key in ENVIRONMENT_KEYS}
   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT")
   query = environment.get("IG_E2_SEARCH_QUERY") or DEFAULT_TERM
   tag = (environment.get("IG_E2_HASHTAG") or DEFAULT_TERM).lstrip("#")
   report: dict[str, Any] = {
      "request_cap": REQUEST_CAP,
      "inputs": {"query_length": len(query), "tag_length": len(tag)},
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

      for label, arguments, summarise in (
         ("recent searches", ["recent-searches"], summarise_recent),
         ("accounts search", ["search", "--non-personalised", query], summarise_accounts),
         ("hashtag header", ["hashtag", tag], summarise_hashtag),
      ):
         if run(label, arguments, summarise) is None:
            outcome = "stopped"
            break

      report["requests_spent"] = len(requests_sent(request_log))
      report["each_command_sent_its_own_query"] = each_command_sent_its_own_query(report["steps"])
      report["no_unobserved_search_query_sent"] = no_unobserved_query_sent(report["steps"])

   report["outcome"] = outcome
   report_run("e2-search-cli" if outcome == "done" else "e2-search-cli-stopped", report)

   return 0 if outcome == "done" else 3


if __name__ == "__main__":
   sys.exit(main())
