"""Read only. Ran 2026-09-27, 17 requests. The E2 batch 11d reads through the dumpsta command. Seventeen requests,
twenty at most.

The live acceptance of the post page route of ``client.media.by_code``, of ``media.page``, of
``media.comments`` on the same post, and of ``client.account.blocked``: the installed console
script run as ``uv run dumpsta --json`` subprocesses, never the library imported, as
``e2_own_account_more_cli_acceptance.py`` does, on the owner's own account and one post of the
owner's own grid, under the default behavior.

   profile --by-id VIEWER      1 request, the owner's profile, for the username the grid needs
   posts USERNAME              1 request, the owner's grid, its first post's code and pk
   post CODE                   6 requests, the post page document and its five companions, the
                               badge count, the stories tray, the chat tabs jewel and the omni
                               picker, and the login interstitial quick promotion, and no post
                               query (W111, W112)
   post-page CODE              6 requests, the same load, the post, its first comments and its
                               author's grid read out of the document
   comments PK                 1 request, the comment pagination query alone, the named
                               departure for a read keyed on a pk (W111)
   blocked                     2 requests, the blocked accounts screen then its reloader action,
                               in one action (W110)

Seventeen when the stored tokens are accepted; the grid read and the blocked list each spend a
bootstrap first when the session holds no page token, and the two page loads carry fresh tokens
of their own, so the counter in ``cli_request_counter/`` refuses the twenty-first. Each process
has its own pacer, so the probe spaces commands itself, 2.85 s after the previous one ended. It
stops on any nonzero exit. The CLI closes its client as soon as a read answers, which drops the
page's cookie sync tail before it is due, so none is expected here.

The checks: each page load sent exactly the document then the five companions in the recorded
order and no post, comments or grid query; ``post`` answered the pk the grid listed; the page's
comment count agrees with the first page of ``comments``; the blocked list sent exactly two
``/async`` fetches and nothing that unblocks. Nothing here changes the account: the post page's
preloads are reads, invisible to others (W43). Recorded: exit codes, error class names, the
requests each command sent, counts and booleans. No username, name, caption, code, id or URL
leaves the subprocess's output into the log, because the blocked accounts are other people.

Run it from ``engine/`` with:

   uv run python probes/e2_post_page_cli_acceptance.py
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
from pathlib import Path
from typing import Any

from _probe_support import ENGINE_ROOT, SESSION_PATH, load_env, report_run

from dumpstagram.session import Session

REQUEST_CAP = 20
READ_GAP_SECONDS = 2.85
COUNTER_DIRECTORY = Path(__file__).resolve().parent / "cli_request_counter"
ENVIRONMENT_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE")

POST_PAGE_LOAD = [
   "/p",
   "IGDBadgeCountOffMsysQuery",
   "PolarisStoriesV3TrayContainerQuery",
   "IGDChatTabsJewelOffMsysQuery",
   "IGDOmniPickerNullStateListQuery",
   "QuickPromotionSupportIGSchemaBatchFetchQuery",
]
"""The recorded post page load's requests, in its order (W112)."""

QUERIES_THE_DOCUMENT_CARRIES = (
   "PolarisPostRootQuery",
   "PolarisPostCommentsContainerQuery",
   "PolarisDesktopPostPageRelatedMediaGridQuery",
)


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


def names_after_any_bootstrap(step: dict[str, Any]) -> list[str]:
   return [str(sent.get("name")) for sent in step["sent"] if sent.get("name") != "/other"]


def check_page_load(step: dict[str, Any]) -> dict[str, Any]:
   names = names_after_any_bootstrap(step)

   return {
      "sent_the_recorded_load": names == POST_PAGE_LOAD,
      "sent_no_query_the_document_carries": not any(
         name in QUERIES_THE_DOCUMENT_CARRIES for name in names
      ),
      "every_request_answered_200": all(sent.get("status") == 200 for sent in step["sent"]),
   }


def summarise_post(payload: dict[str, Any], grid_pk: str) -> dict[str, Any]:
   post = payload["post"]

   return {
      "is_the_grids_first_post": post["pk"] == grid_pk,
      "media_type": post["media_type"],
      "comment_count": post["comment_count"],
      "has_liked_is_a_flag": isinstance(post["has_liked"], bool),
   }


def summarise_post_page(payload: dict[str, Any], grid_pk: str) -> dict[str, Any]:
   comments = payload["comments"]
   grid = payload["author_grid"]

   return {
      "is_the_grids_first_post": payload["post"]["pk"] == grid_pk,
      "first_comments": comments["comment_count"],
      "comments_more_available": comments["more_available"],
      "author_grid": len(grid),
      "grid_holds_the_post": grid_pk in [thumbnail["pk"] for thumbnail in grid],
   }


def summarise_comments(payload: dict[str, Any]) -> dict[str, Any]:
   return {
      "comments": payload["comment_count"],
      "more_available": payload["more_available"],
   }


def summarise_blocked(payload: dict[str, Any]) -> dict[str, Any]:
   accounts = payload["accounts"]

   return {
      "accounts": payload["account_count"],
      "listed": len(accounts),
      "automatic": sum(account["is_auto_blocked"] is True for account in accounts),
      "empty_secondary_text": sum(account["secondary_text"] == "" for account in accounts),
      "every_id_is_digits": all(account["id"].isdigit() for account in accounts),
      "distinct_ids": len({account["id"] for account in accounts}),
   }


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
         answered = step["exit"] == 0 and payload is not None

         return step, payload if answered else None

      def finish() -> int:
         report["requests_spent"] = len(requests_sent(request_log))
         report["outcome"] = outcome
         kind = "e2-post-page-cli" if outcome == "done" else "e2-post-page-cli-stopped"
         report_run(kind, report)

         return 0 if outcome == "done" else 3

      _, profile = run("own profile", ["profile", "--by-id", viewer_id])

      if profile is None:
         return finish()

      _, grid = run("own grid", ["posts", profile["profile"]["username"]])

      if grid is None or not grid["posts"]:
         report["stopped_because"] = "the owner's grid listed no post"

         return finish()

      code = grid["posts"][0]["code"]
      grid_pk = grid["posts"][0]["pk"]

      post_step, post = run("post by code", ["post", code])

      if post is None:
         return finish()

      report["results"]["post"] = {
         **summarise_post(post, grid_pk),
         **check_page_load(post_step),
      }

      page_step, page = run("post page", ["post-page", code])

      if page is None:
         return finish()

      report["results"]["post page"] = {
         **summarise_post_page(page, grid_pk),
         **check_page_load(page_step),
      }

      comments_step, comments = run("comments", ["comments", grid_pk])

      if comments is None:
         return finish()

      report["results"]["comments"] = {
         **summarise_comments(comments),
         "one_pagination_query": names_after_any_bootstrap(comments_step)
         == ["PolarisPostCommentsPaginationQuery"],
         "agrees_with_the_page": comments["comment_count"] == page["comments"]["comment_count"],
      }

      blocked_step, blocked = run("blocked", ["blocked"])

      if blocked is None:
         return finish()

      fetches = Counter(names_after_any_bootstrap(blocked_step))
      report["results"]["blocked"] = {
         **summarise_blocked(blocked),
         "two_bloks_fetches_and_nothing_else": fetches == Counter({"/async": 2}),
      }
      outcome = "done"

      return finish()


if __name__ == "__main__":
   sys.exit(main())
