"""Read only. Not run yet. The E2 batch 5 reads through the dumpsta command. Four requests, three
when the owner has no highlight, eight at most.

The live acceptance of ``client.stories.tray``, ``reel`` and ``highlight``: the installed console
script run as ``uv run dumpsta --json`` subprocesses, never the library imported, as
``e2_profile_tabs_cli_acceptance.py`` does.

   stories-tray                1 request, the tray, read for its counts only
   story VIEWER                1 request, the owner's own reel, the viewer id read from the
                               session file, which answers no reel unless he has a live story
   highlights VIEWER           1 request, the owner's highlights tray, for the first highlight id
   highlight FIRST             1 request, the owner's first highlight, skipped when he has none

Four when the stored tokens are accepted, and one more for each bootstrap, so the counter in
``cli_request_counter/`` refuses the ninth. Each process has its own pacer, so the probe spaces
commands itself, 2.85 s after the previous one ended. It stops on any nonzero exit.

No other account's reel is read, and no request marks anything seen: every story command sends
only its read query, which the probe checks from the counter's log (W42, W68). Recorded: exit
codes, error class names, the requests each command sent, counts, booleans and reel types. No
username, name, title, sticker text or URL leaves the subprocess's output into the log.

Run it from ``engine/`` with:

   uv run python probes/e2_stories_cli_acceptance.py
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

REQUEST_CAP = 8
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


STORY_QUERIES = frozenset(
   {"PolarisStoriesV3TrayContainerQuery", "PolarisStoriesV3ReelPageStandaloneQuery"}
)


def summarise_tray(payload: dict[str, Any]) -> dict[str, Any]:
   reels = payload["reels"]

   return {
      "reels": payload["reel_count"],
      "distinct_owners": len({reel["owner"]["id"] for reel in reels}),
      "reel_types": sorted({reel["reel_type"] for reel in reels}),
      "never_seen": sum(reel["seen_at"] is None for reel in reels),
      "positions_in_order": [reel["ranked_position"] for reel in reels]
      == list(range(1, len(reels) + 1)),
   }


def summarise_reel(payload: dict[str, Any]) -> dict[str, Any]:
   reel = payload["reel"]

   if reel is None:
      return {"reel": None, "items": 0}

   items = reel["items"]

   return {
      "reel_type": reel["reel_type"],
      "items": payload["item_count"],
      "media_types": sorted({item["media_type"] for item in items}),
      "product_types": sorted({item["product_type"] for item in items}),
      "videos_per_video_item": sorted(
         {len(item["videos"]) for item in items if item["media_type"] == 2}
      ),
      "with_mentions": sum(bool(item["mentions"]) for item in items),
      "with_music": sum(bool(item["music"]) for item in items),
      "audiences": sorted({str(item["audience"]) for item in items}),
      "has_title": reel["title"] is not None,
   }


def summarise_highlights(payload: dict[str, Any]) -> dict[str, Any]:
   highlights = payload["highlights"]

   return {"highlights": len(highlights), "has_more": payload["has_more"]}


def only_story_reads(steps: list[dict[str, Any]]) -> bool:
   """Whether every GraphQL request a story command sent was a story read query, and none a
   mutation. A bootstrap's document load is named by its path, which starts with a slash."""

   story_steps = [
      step for step in steps if step["command"] in ("stories-tray", "story", "highlight")
   ]
   names = [
      str(sent["name"])
      for step in story_steps
      for sent in step["sent"]
      if sent.get("name") is not None and not str(sent["name"]).startswith("/")
   ]
   no_mutation = not any(str(name).endswith("Mutation") for name in names)
   only_reads = set(names) <= STORY_QUERIES

   return no_mutation and only_reads


def main() -> int:
   parser = argparse.ArgumentParser(description=__doc__)
   parser.parse_args()

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
         ("stories tray", ["stories-tray"], summarise_tray),
         ("own reel", ["story", viewer_id], summarise_reel),
      ]

      for label, arguments, summarise in plan:
         if run(label, arguments, summarise) is None:
            outcome = "stopped"
            break

      highlights = None

      if outcome == "done":
         highlights = run("highlights", ["highlights", viewer_id], summarise_highlights)
         outcome = "done" if highlights is not None else "stopped"

      has_a_highlight = highlights is not None and bool(highlights["highlights"])

      if has_a_highlight:
         first_highlight = highlights["highlights"][0]["id"]
         read = run("own first highlight", ["highlight", first_highlight], summarise_reel)
         outcome = "done" if read is not None else "stopped"
      elif outcome == "done":
         report["results"]["own first highlight"] = "skipped, the owner has no highlight"

      report["requests_spent"] = len(requests_sent(request_log))
      report["only_story_reads_sent"] = only_story_reads(report["steps"])

   report["outcome"] = outcome
   report_run("e2-stories-cli" if outcome == "done" else "e2-stories-cli-stopped", report)

   return 0 if outcome == "done" else 3


if __name__ == "__main__":
   sys.exit(main())
