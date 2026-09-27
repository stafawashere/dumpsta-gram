"""Read only. Ran 2026-09-27, 7 requests. The E2 batch 11b reads through the dumpsta command. Seven requests,
nine at most.

The live acceptance of ``client.feeds.reels``, ``search.top``, ``search.accounts`` on both routes
and ``search.keyword``: the installed console script run as ``uv run dumpsta --json``
subprocesses, never the library imported, as ``e2_search_cli_acceptance.py`` does.

   reels --pages 2                     2 requests, the reels feed's first page and the next,
                                       which names the first page's reels as seen
   search-top QUERY                    1 request, the personalised typeahead
   search QUERY                        1 request, its accounts, the personalised route by default
   search --non-personalised QUERY     1 request, the non-profiled typeahead, the departure
   keyword QUERY                       1 request, the keyword grid's first page
   keyword #QUERY                      1 request, the same grid for the tag, a hashtag's page

QUERY comes from ``IG_E2_SEARCH_QUERY`` in the root ``.env``, ``instagram`` when absent, as
``e2_capture_replays.py`` sent it, and is never logged. The hashtag step prefixes it with ``#``,
which the browser sent from ``/explore/tags/<tag>/`` and no engine replay has sent yet, so that
step is the first live check of W103's pairing.

Seven when the stored tokens are accepted, and one more for each bootstrap or stale token
envelope (W57), so the counter in ``cli_request_counter/`` refuses the tenth. Each process has its
own pacer, so the probe spaces commands itself, 2.85 s after the previous one ended. It stops on
any nonzero exit.

Nothing here is visible to another person: no reel is played, so no view is reported and no ads
pool asked for (W101), and nothing is opened, so no recent search is added. The probe checks
from the counter's log that each step sent exactly its own query and that none sent the search
box's container query, an ads pool or anything outside the API's named paths, where a view
report would go. Recorded: exit codes, error class names, the requests
each command sent, counts and booleans. No username, full name, caption, keyword, query, code, id
or cursor leaves the subprocess's output into the log.

Run it from ``engine/`` with:

   uv run python probes/e2_discovery_search_cli_acceptance.py
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

REQUEST_CAP = 9
READ_GAP_SECONDS = 2.85
COUNTER_DIRECTORY = Path(__file__).resolve().parent / "cli_request_counter"
ENVIRONMENT_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE", "IG_E2_SEARCH_QUERY")
DEFAULT_TERM = "instagram"
PERSONALISED = "PolarisSearchBoxRefetchableQuery"
NON_PERSONALISED = "PolarisSearchBoxNonProfiledRefetchableQuery"
KEYWORD_GRID = "PolarisKeywordSearchExplorePageRelayQuery"
EXPECTED_QUERIES = {
   "reels": ["PolarisClipsTabDesktopContainerQuery", "PolarisClipsTabDesktopPaginationQuery"],
   "top results": [PERSONALISED],
   "accounts, personalised": [PERSONALISED],
   "accounts, non-personalised": [NON_PERSONALISED],
   "keyword grid": [KEYWORD_GRID],
   "hashtag grid": [KEYWORD_GRID],
}
NEVER_SENT = (
   "PolarisSearchBoxContainerQuery",
   "PolarisClipsAdsPoolQuery",
   "PolarisClipsHomeRootQuery",
)
OUTSIDE_THE_NAMED_PATHS = "/other"
"""The counter's name for a request outside the API's named path segments, which a view report to
``/video/unified_cvc/`` would be."""


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


def summarise_reels(payload: dict[str, Any]) -> dict[str, Any]:
   reels = payload["reels"]
   pks = [reel["pk"] for reel in reels]
   cursor = payload["end_cursor"]

   return {
      "pages_read": payload["pages_read"],
      "reel_count": payload["reel_count"],
      "distinct_reels": len(set(pks)),
      "more_available": payload["more_available"],
      "product_types": sorted({reel["product_type"] for reel in reels}),
      "media_types": sorted({reel["media_type"] for reel in reels}),
      "every_reel_unseen": all(reel["is_seen"] is False for reel in reels),
      "with_caption": sum(reel["caption"] is not None for reel in reels),
      "with_user_tags": sum(bool(reel["user_tags"]) for reel in reels),
      "collaborators_never_carried": all(reel["collaborators"] is None for reel in reels),
      "end_cursor_carries_the_last_reel": isinstance(cursor, str) and pks[-1] in cursor
      if pks
      else False,
   }


def summarise_top(payload: dict[str, Any]) -> dict[str, Any]:
   results = payload["results"]
   positions = [row["position"] for row in results if row["position"] is not None]

   return {
      "result_count": payload["result_count"],
      "kinds": payload["kinds"],
      "positions_in_order": positions == sorted(positions),
      "every_account_row_has_an_account": all(
         row["account"] is not None for row in results if row["kind"] == "user"
      ),
      "every_keyword_row_has_text": all(
         bool(row["keyword"]) for row in results if row["kind"] == "keyword"
      ),
   }


def summarise_accounts(payload: dict[str, Any]) -> dict[str, Any]:
   accounts = payload["accounts"]

   return {
      "accounts": payload["account_count"],
      "accounts_counted_match": len(accounts) == payload["account_count"],
      "every_id_is_digits": all(account["id"].isdigit() for account in accounts),
   }


def summarise_grid(payload: dict[str, Any]) -> dict[str, Any]:
   posts = payload["posts"]

   return {
      "post_count": payload["post_count"],
      "distinct_posts": len({post["pk"] for post in posts}),
      "more_available": payload["more_available"],
      "media_types": sorted({post["media_type"] for post in posts}),
      "videos_with_a_duration": sum(post["video_duration"] is not None for post in posts),
      "with_view_count": sum(post["view_count"] is not None for post in posts),
   }


def each_step_sent_its_own_queries(steps: list[dict[str, Any]]) -> bool:
   for step in steps:
      api_names = [sent.get("name") for sent in step["sent"] if sent.get("name")]
      expected = EXPECTED_QUERIES.get(step["label"], [])
      sent_each = all(name in api_names for name in expected)

      if not sent_each:
         return False

   return True


def nothing_unobserved_was_sent(steps: list[dict[str, Any]]) -> bool:
   names = {str(sent.get("name")) for step in steps for sent in step["sent"]}
   left_the_named_paths = OUTSIDE_THE_NAMED_PATHS in names

   return names.isdisjoint(NEVER_SENT) and not left_the_named_paths


def main() -> int:
   parser = argparse.ArgumentParser(description=__doc__)
   parser.parse_args()

   environment = {key: value for key, value in load_env().items() if key in ENVIRONMENT_KEYS}
   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT")
   query = environment.get("IG_E2_SEARCH_QUERY") or DEFAULT_TERM
   report: dict[str, Any] = {
      "request_cap": REQUEST_CAP,
      "inputs": {"query_length": len(query)},
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
         ("reels", ["reels", "--pages", "2"], summarise_reels),
         ("top results", ["search-top", query], summarise_top),
         ("accounts, personalised", ["search", query], summarise_accounts),
         (
            "accounts, non-personalised",
            ["search", "--non-personalised", query],
            summarise_accounts,
         ),
         ("keyword grid", ["keyword", query], summarise_grid),
         ("hashtag grid", ["keyword", f"#{query.lstrip('#')}"], summarise_grid),
      ):
         if run(label, arguments, summarise) is None:
            outcome = "stopped"
            break

      report["requests_spent"] = len(requests_sent(request_log))
      report["each_step_sent_its_own_queries"] = each_step_sent_its_own_queries(report["steps"])
      report["nothing_unobserved_was_sent"] = nothing_unobserved_was_sent(report["steps"])

   report["outcome"] = outcome
   report_run(
      "e2-discovery-search-cli" if outcome == "done" else "e2-discovery-search-cli-stopped",
      report,
   )

   return 0 if outcome == "done" else 3


if __name__ == "__main__":
   sys.exit(main())
