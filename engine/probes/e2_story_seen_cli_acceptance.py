"""WRITE. Not run yet. E2 batch 12 live acceptance through the dumpsta command, on the owner's
own highlight only. Five requests, two of them seen mutations, eight at most.

The live acceptance of ``client.stories.mark_seen`` and of the W94 default, run as
``uv run dumpsta --json`` subprocesses, never the library imported, as
``e2_stories_cli_acceptance.py`` does, whose ``dumpsta`` helper and cap of eight it shares.

   highlights VIEWER             1 request, the owner's highlights tray, for the first highlight
   highlight FIRST               2 requests, the highlight read and, under the default behavior,
                                 the seen mutation for its first item (W94)
   story-seen FIRST SECOND       2 requests, the highlight read with marking off and the seen
                                 mutation for its second item (W93, W95)

Both writes land on content only the owner sees a viewer list for, so no other person is shown
as a viewer (W42). The highlight is the first of the session's own highlights tray, the second
write is sent only when the read reports the session's own account as its owner, and the probe
never names another account's reel or highlight. A highlight read carries no
seen state, so each mutation's answer, checked by the command, is the only confirmation.

It checks from the counter's log that each marking step sent exactly the highlight read and one
``PolarisStoriesV3SeenMutation``, in that order. Recorded: exit codes, error class names, the
requests each command sent, counts and booleans. No title, username, id or URL is logged.

Run it from ``engine/`` with:

   uv run python probes/e2_story_seen_cli_acceptance.py
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from _probe_support import SESSION_PATH, load_env, report_run
from e2_stories_cli_acceptance import (
   ENVIRONMENT_KEYS,
   READ_GAP_SECONDS,
   REQUEST_CAP,
   dumpsta,
   requests_sent,
)

from dumpstagram.session import Session

READ_THEN_MARK = ["PolarisStoriesV3ReelPageStandaloneQuery", "PolarisStoriesV3SeenMutation"]


def graphql_names(step: dict[str, Any]) -> list[str]:
   """The friendly names a step sent, a bootstrap's document load, named by its path, left out."""

   return [
      str(sent["name"])
      for sent in step["sent"]
      if sent.get("name") is not None and not str(sent["name"]).startswith("/")
   ]


def main() -> int:
   parser = argparse.ArgumentParser(description=__doc__)
   parser.parse_args()

   environment = {key: value for key, value in load_env().items() if key in ENVIRONMENT_KEYS}
   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT")
   viewer_id = Session.load(session_path).ds_user_id
   report: dict[str, Any] = {"request_cap": REQUEST_CAP, "steps": [], "results": {}}
   outcome = "stopped"

   with tempfile.TemporaryDirectory() as scratch:
      request_log = Path(scratch) / "requests.jsonl"
      step_number = 0

      def run(label: str, arguments: list[str]) -> tuple[dict[str, Any], Any]:
         nonlocal step_number

         if step_number > 0:
            time.sleep(READ_GAP_SECONDS)

         step_number += 1
         step, payload = dumpsta(step_number, arguments, session_path, user_agent, request_log)
         step["label"] = label
         report["steps"].append(step)
         print(f"step {step_number} {label}: exit {step['exit']}, {step['requests']} requests")

         return step, payload

      _, highlights = run("highlights", ["highlights", viewer_id])
      has_a_highlight = highlights is not None and bool(highlights["highlights"])

      if not has_a_highlight:
         report["results"]["highlight"] = "skipped, the owner has no highlight"
      else:
         first = highlights["highlights"][0]["id"]
         read_step, read = run("own highlight, default marking", ["highlight", first])
         reel = read["reel"] if read is not None else None
         items = reel["items"] if reel is not None else []
         owner_is_viewer = reel is not None and reel["owner"]["id"] == viewer_id
         has_a_second_item = len(items) > 1
         can_mark_a_second_item = owner_is_viewer and has_a_second_item
         marked_first = read is not None and read["marked_first_item_seen"] is True

         report["results"]["default marking"] = {
            "exit": read_step["exit"],
            "items": len(items),
            "owner_is_viewer": owner_is_viewer,
            "marked_first_item_seen": marked_first,
            "read_then_one_mark": graphql_names(read_step) == READ_THEN_MARK,
         }

         if can_mark_a_second_item:
            second = items[1]["pk"]
            seen_step, seen = run("own highlight, second item", ["story-seen", first, second])
            marked_second = seen is not None and seen["marked_seen"] is True
            report["results"]["story-seen"] = {
               "exit": seen_step["exit"],
               "marked_seen": marked_second,
               "read_then_one_mark": graphql_names(seen_step) == READ_THEN_MARK,
            }
            both_exited_clean = seen_step["exit"] == 0 and read_step["exit"] == 0
            outcome = "done" if both_exited_clean else "stopped"
         else:
            report["results"]["story-seen"] = "skipped, not the owner's or fewer than two items"

      report["requests_spent"] = len(requests_sent(request_log))

   report["outcome"] = outcome
   report_run("e2-story-seen-cli" if outcome == "done" else "e2-story-seen-cli-stopped", report)

   return 0 if outcome == "done" else 3


if __name__ == "__main__":
   sys.exit(main())
