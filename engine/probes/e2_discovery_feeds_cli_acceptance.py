"""Read only. Ran 2026-09-27, 4 requests. The E2 batch 7 reads through the dumpsta command. Four requests, two
when neither the explore grid nor ``IG_E2_LOCATION_ID`` gives a place, eight at most.

The live acceptance of ``client.feeds.explore``, ``place``, ``location`` and ``has_new_posts``:
the installed console script run as ``uv run dumpsta --json`` subprocesses, never the library
imported, as ``e2_stories_cli_acceptance.py`` does.

   explore                     1 request, the explore grid's first page
   place LOCATION              1 request, the header of the first place a post on the grid is
                               tagged at, or of IG_E2_LOCATION_ID from the root .env when none is
   location LOCATION           1 request, the first page of that place's ranked grid
   new-posts                   1 request, whether the home feed has new posts

Four when the stored tokens are accepted, and one more for each bootstrap, so the counter in
``cli_request_counter/`` refuses the ninth. Each process has its own pacer, so the probe spaces
commands itself, 2.85 s after the previous one ended. It stops on any nonzero exit.

Nothing here is visible to another person. The probe checks from the counter's log that no
command sent the grid's next page query, ``PolarisLocationPageTabContentQuery_connection``
(W79). Recorded: exit codes, error class names, the requests each command sent, counts,
booleans and media types. No username, caption, place name, address or id leaves the
subprocess's output into the log.

Run it from ``engine/`` with:

   uv run python probes/e2_discovery_feeds_cli_acceptance.py
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

REQUEST_CAP = 8
READ_GAP_SECONDS = 2.85
COUNTER_DIRECTORY = Path(__file__).resolve().parent / "cli_request_counter"
ENVIRONMENT_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE", "IG_E2_LOCATION_ID")
NEXT_PAGE_QUERY = "PolarisLocationPageTabContentQuery_connection"


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


def explore_posts(payload: dict[str, Any]) -> list[dict[str, Any]]:
   return [
      post for section in payload["sections"] for post in (*section["featured"], *section["posts"])
   ]


def first_place_id(payload: dict[str, Any] | None) -> str | None:
   if payload is None:
      return None

   for post in explore_posts(payload):
      location = post.get("location")

      if location is not None:
         return str(location["id"])

   return None


def summarise_explore(payload: dict[str, Any]) -> dict[str, Any]:
   posts = explore_posts(payload)

   return {
      "sections": payload["section_count"],
      "posts": payload["post_count"],
      "posts_counted_match": len(posts) == payload["post_count"],
      "featured_per_section": sorted({len(section["featured"]) for section in payload["sections"]}),
      "feed_types": sorted({section["feed_type"] for section in payload["sections"]}),
      "media_types": sorted({post["media_type"] for post in posts}),
      "with_a_place": sum(post.get("location") is not None for post in posts),
      "more_available": payload["more_available"],
   }


def summarise_place(payload: dict[str, Any]) -> dict[str, Any]:
   place = payload["place"]

   return {
      "has_a_name": bool(place["name"]),
      "media_count_above_zero": place["media_count"] > 0,
      "has_an_address": bool(place["address"]),
      "has_a_city": bool(place["city"]),
   }


def summarise_location(payload: dict[str, Any]) -> dict[str, Any]:
   posts = payload["posts"]

   return {
      "posts": payload["post_count"],
      "media_types": sorted({post["media_type"] for post in posts}),
      "carousels": sum(post["carousel_media_count"] is not None for post in posts),
      "more_available": payload["more_available"],
   }


def summarise_new_posts(payload: dict[str, Any]) -> dict[str, Any]:
   return {"new_posts": payload["new_posts"]}


def no_next_page_sent(steps: list[dict[str, Any]]) -> bool:
   names = [str(sent.get("name")) for step in steps for sent in step["sent"]]

   return NEXT_PAGE_QUERY not in names


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

      explore = run("explore grid", ["explore"], summarise_explore)
      outcome = "done" if explore is not None else "stopped"
      from_the_grid = first_place_id(explore)
      place_id = from_the_grid or environment.get("IG_E2_LOCATION_ID")
      report["place_source"] = (
         "explore grid" if from_the_grid else "env" if place_id else "none, place steps skipped"
      )

      has_a_place = outcome == "done" and place_id is not None

      if has_a_place:
         for label, command, summarise in (
            ("place header", "place", summarise_place),
            ("place grid", "location", summarise_location),
         ):
            if run(label, [command, str(place_id)], summarise) is None:
               outcome = "stopped"
               break

      if outcome == "done":
         checked = run("new posts check", ["new-posts"], summarise_new_posts)
         outcome = "done" if checked is not None else "stopped"

      report["requests_spent"] = len(requests_sent(request_log))
      report["no_next_page_query_sent"] = no_next_page_sent(report["steps"])

   report["outcome"] = outcome
   report_run(
      "e2-discovery-feeds-cli" if outcome == "done" else "e2-discovery-feeds-cli-stopped", report
   )

   return 0 if outcome == "done" else 3


if __name__ == "__main__":
   sys.exit(main())
