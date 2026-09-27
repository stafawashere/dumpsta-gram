"""Read only. Ran 2026-09-27, 9 requests. The E2 batch 11e reads through the dumpsta command. Ten requests,
eleven at most.

The live acceptance of ``client.feeds.explore`` past its first page, ``feeds.audio`` and
``profiles.mutual_followers``: the installed console script run as ``uv run dumpsta --json``
subprocesses, never the library imported, as ``e2_discovery_search_cli_acceptance.py`` does.

   explore --pages 2                   2 requests, the grid's first page and the next, on the
                                       first page's root max_id
   reels --pages 2                     2 requests, the reels feed's two pages, for an audio id
   audio AUDIO_ID --pages 2            1 or 2 requests, the audio's page and, when it says more
                                       exist, its next page
   following OWNER_ID                  2 requests, the owner's following page one and its
                                       statuses, for a public account
   mutual-followers ACCOUNT_ID         1 or 2 requests, the list and, when it holds anyone, the
                                       statuses of its accounts

AUDIO_ID is the ``audio_id`` of the last reel read that names one, a second page reel when the
feed gave two pages, which is the W118 accessor used as a caller would. OWNER_ID is the
session's own account id. ACCOUNT_ID is the first account on the owner's following page that
is public, whatever its mutual followers count; an empty list is still the read.

Ten when the stored tokens are accepted and each paged read goes on, and one more for a
bootstrap or a stale token envelope (W57), so the counter in ``cli_request_counter/`` refuses the
twelfth. Each process has its own pacer, so the probe spaces commands itself, 2.85 s after the
previous one ended. It stops on any nonzero exit.

Nothing here is visible to another person: no reel is played, nothing is liked or followed, and
no page is opened that tells its owner who looked. The probe checks from the counter's log that
each step sent its own path and nothing else. Recorded: exit codes, error class names, the
requests each command sent, counts and booleans. No username, full name, caption, title, code,
id or cursor leaves the subprocess's output into the log.

Run it from ``engine/`` with:

   uv run python probes/e2_last_reads_cli_acceptance.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from _probe_support import ENGINE_ROOT, SESSION_PATH, load_env, report_run

from dumpstagram.session import Session

REQUEST_CAP = 11
READ_GAP_SECONDS = 2.85
COUNTER_DIRECTORY = Path(__file__).resolve().parent / "cli_request_counter"
ENVIRONMENT_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE")
EXPLORE_PATH = "/api/v1/discover/web/explore_grid/"
AUDIO_PATH = "/api/v1/clips/music/"
EXPECTED_PATHS = {
   "explore": [EXPLORE_PATH, EXPLORE_PATH],
   "audio": [AUDIO_PATH],
}
EXPECTED_QUERIES = {
   "reels": ["PolarisClipsTabDesktopContainerQuery", "PolarisClipsTabDesktopPaginationQuery"],
}


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
         {key: entry.get(key) for key in ("host", "method", "name", "path", "status")}
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


def summarise_explore(payload: dict[str, Any]) -> dict[str, Any]:
   posts = [
      post for section in payload["sections"] for post in (*section["featured"], *section["posts"])
   ]

   return {
      "pages_read": payload["pages_read"],
      "section_count": payload["section_count"],
      "post_count": payload["post_count"],
      "distinct_posts": len({post["pk"] for post in posts}),
      "more_available": payload["more_available"],
      "carries_a_cursor": isinstance(payload["end_cursor"], str),
      "with_audio_id": sum(post["audio_id"] is not None for post in posts),
   }


def summarise_reels(payload: dict[str, Any]) -> dict[str, Any]:
   reels = payload["reels"]

   return {
      "pages_read": payload["pages_read"],
      "reel_count": payload["reel_count"],
      "with_audio_id": sum(reel["audio_id"] is not None for reel in reels),
   }


def summarise_audio(payload: dict[str, Any]) -> dict[str, Any]:
   clips = payload["clips"]
   audio = payload["audio"]

   return {
      "kind": audio["kind"] if audio is not None else None,
      "track_is_the_one_asked_for": audio is not None and audio["audio_id"] == payload["audio_id"],
      "clips_count": payload["clips_count"],
      "pages_read": payload["pages_read"],
      "clip_count": payload["clip_count"],
      "distinct_clips": len({clip["id"] for clip in clips}),
      "every_clip_names_this_audio": all(clip["audio_id"] == payload["audio_id"] for clip in clips),
      "more_available": payload["more_available"],
      "carries_a_cursor": isinstance(payload["end_cursor"], str),
   }


def summarise_following(payload: dict[str, Any]) -> dict[str, Any]:
   accounts = payload["accounts"]

   return {
      "accounts": payload["account_count"],
      "public_accounts": sum(account["is_private"] is False for account in accounts),
   }


def summarise_mutual(payload: dict[str, Any]) -> dict[str, Any]:
   accounts = payload["accounts"]

   return {
      "accounts": payload["account_count"],
      "more_available": payload["more_available"],
      "every_id_is_digits": all(account["id"].isdigit() for account in accounts),
      "every_account_has_a_status": all(
         account["friendship_status"] is not None for account in accounts
      ),
   }


def last_audio_id(payload: dict[str, Any]) -> str | None:
   named = [reel["audio_id"] for reel in payload["reels"] if reel["audio_id"]]

   return named[-1] if named else None


def first_public_account(payload: dict[str, Any]) -> str | None:
   public = [account["id"] for account in payload["accounts"] if account["is_private"] is False]

   return public[0] if public else None


def each_step_sent_its_own_requests(steps: list[dict[str, Any]]) -> bool:
   for step in steps:
      paths = [sent.get("path") for sent in step["sent"] if sent.get("path")]
      names = [sent.get("name") for sent in step["sent"] if sent.get("name")]
      expected_paths = EXPECTED_PATHS.get(step["label"], [])
      expected_names = EXPECTED_QUERIES.get(step["label"], [])
      sent_every_expected_path = all(
         paths.count(path) >= expected_paths.count(path) for path in expected_paths
      )
      sent_every_expected_name = all(name in names for name in expected_names)

      if not (sent_every_expected_path and sent_every_expected_name):
         return False

   return True


def main() -> int:
   parser = argparse.ArgumentParser(description=__doc__)
   parser.parse_args()

   environment = {key: value for key, value in load_env().items() if key in ENVIRONMENT_KEYS}
   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT")
   owner_id = Session.load(session_path).ds_user_id
   report: dict[str, Any] = {"request_cap": REQUEST_CAP, "steps": [], "results": {}}
   outcome = "done"

   with tempfile.TemporaryDirectory() as scratch:
      request_log = Path(scratch) / "requests.jsonl"
      step_number = 0

      def run(label: str, arguments: list[str]) -> dict[str, Any] | None:
         nonlocal step_number

         if step_number > 0:
            time.sleep(READ_GAP_SECONDS)

         step_number += 1
         step, payload = dumpsta(step_number, arguments, session_path, user_agent, request_log)
         step["label"] = label
         report["steps"].append(step)
         print(f"step {step_number} {label}: exit {step['exit']}, {step['requests']} requests")

         if step["exit"] != 0:
            return None

         return payload

      explore = run("explore", ["explore", "--pages", "2"])
      reels = run("reels", ["reels", "--pages", "2"]) if explore is not None else None
      audio_id = last_audio_id(reels) if reels is not None else None
      audio = run("audio", ["audio", audio_id, "--pages", "2"]) if audio_id else None
      following = run("following", ["following", owner_id]) if audio is not None else None
      account_id = first_public_account(following) if following is not None else None
      mutual = run("mutual", ["mutual-followers", account_id]) if account_id else None

      readings = (
         ("explore", explore, summarise_explore),
         ("reels", reels, summarise_reels),
         ("audio", audio, summarise_audio),
         ("following", following, summarise_following),
         ("mutual", mutual, summarise_mutual),
      )

      for label, payload, summarise in readings:
         if payload is None:
            outcome = "stopped"
            report["stopped_before"] = label

            break

         report["results"][label] = summarise(payload)

      report["inputs"] = {
         "audio_id_found": audio_id is not None,
         "public_account_found": account_id is not None,
      }
      report["requests_spent"] = len(requests_sent(request_log))
      report["each_step_sent_its_own_requests"] = each_step_sent_its_own_requests(report["steps"])

   report["outcome"] = outcome
   report_run("e2-last-reads-cli" if outcome == "done" else "e2-last-reads-cli-stopped", report)

   return 0 if outcome == "done" else 3


if __name__ == "__main__":
   sys.exit(main())
