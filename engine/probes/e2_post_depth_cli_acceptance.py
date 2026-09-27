"""Read only. Ran 2026-09-27, 11 requests. The E2 batch 4 reads through the dumpsta command. Eleven requests, twelve
when the replies have a second page, fourteen at most.

The live acceptance of ``client.media.replies``, ``likers``, ``by_id`` and ``more_from_author``:
the installed console script run as ``uv run dumpsta --json`` subprocesses, never the library
imported, as ``e2_follow_lists_cli_acceptance.py`` does.

   feed --posts-only                 6 requests: the home document and its five page load
                                     companions, for the post with the most comments
   comments PK                       1 request, for the comment with the most replies
   replies PK COMMENT_ID --pages 2   1 request, 2 when the first page says more exist
   likers PK                         1 request
   post --by-id PK                   1 request
   more-from-author AUTHOR_ID        1 request

The brief asked for fewer than twelve. Under the default behavior ``dumpsta feed`` spends six on
its own, because it loads the home document as a browser does, so the run is eleven when the
replies fit one page and twelve when they do not. The counter in ``cli_request_counter/`` refuses
the fifteenth, which leaves room for one bootstrap in each of two commands and no more. Each
process has its own pacer, so the probe spaces commands itself, 2.85 s after the previous one
ended. It stops on any nonzero exit, and skips the replies when no comment on the first page has
any.

Every post, comment and account read here is one the owner's timeline already shows, and a read
of likers, replies or a post is visible to nobody (W43). Nothing is liked, commented or marked.

Recorded: exit codes, error class names, the requests each command sent, counts, booleans,
cursor lengths, id prefixes of three characters and timings. No caption, comment text, username,
full name or whole id leaves the subprocess's output into the log.

Run it from ``engine/`` with:

   uv run python probes/e2_post_depth_cli_acceptance.py
"""

from __future__ import annotations

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

REQUEST_CAP = 14
READ_GAP_SECONDS = 2.85
PREFIX_LENGTH = 3
COUNTER_DIRECTORY = Path(__file__).resolve().parent / "cli_request_counter"
ENVIRONMENT_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE")


def requests_sent(request_log: Path) -> list[dict[str, Any]]:
   if not request_log.exists():
      return []

   return [json.loads(line) for line in request_log.read_text(encoding="utf-8").splitlines()]


def prefix(value: object) -> str | None:
   return str(value)[:PREFIX_LENGTH] if value is not None else None


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
         {key: entry.get(key) for key in ("host", "method", "name", "status", "failed_with")}
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


def posts_of(feed: dict[str, Any]) -> list[dict[str, Any]]:
   return [item["post"] for item in feed["items"] if item.get("post")]


def most_commented(feed: dict[str, Any]) -> dict[str, Any] | None:
   posts = posts_of(feed)

   return max(posts, key=lambda post: post["comment_count"]) if posts else None


def summarise_feed(payload: dict[str, Any]) -> dict[str, Any]:
   posts = posts_of(payload)
   chosen = most_commented(payload)

   return {
      "post_count": len(posts),
      "posts_with_location": sum(post["location"] is not None for post in posts),
      "posts_with_tags": sum(bool(post["user_tags"]) for post in posts),
      "posts_with_collaborators": sum(bool(post["collaborators"]) for post in posts),
      "user_tags_null": sum(post["user_tags"] is None for post in posts),
      "chosen_pk_prefix": prefix(chosen["pk"]) if chosen else None,
      "chosen_comment_count": chosen["comment_count"] if chosen else None,
      "chosen_media_type": chosen["media_type"] if chosen else None,
   }


def most_replied(comments: dict[str, Any]) -> dict[str, Any] | None:
   with_replies = [comment for comment in comments["comments"] if comment["reply_count"]]

   return max(with_replies, key=lambda comment: comment["reply_count"]) if with_replies else None


def summarise_comments(payload: dict[str, Any]) -> dict[str, Any]:
   chosen = most_replied(payload)

   return {
      "comment_count": payload["comment_count"],
      "comments_with_replies": sum(bool(comment["reply_count"]) for comment in payload["comments"]),
      "chosen_reply_count": chosen["reply_count"] if chosen else None,
   }


def summarise_replies(payload: dict[str, Any]) -> dict[str, Any]:
   replies = payload["replies"]
   cursor = payload["end_cursor"]

   return {
      "pages_read": payload["pages_read"],
      "reply_count": payload["reply_count"],
      "distinct_ids": len({reply["id"] for reply in replies}),
      "every_parent_is_the_comment": all(
         reply["parent_comment_id"] == payload["comment_id"] for reply in replies
      ),
      "reply_count_values": sorted({str(reply["reply_count"]) for reply in replies}),
      "more_available": payload["more_available"],
      "end_cursor_length": len(cursor) if cursor else None,
   }


def summarise_likers(payload: dict[str, Any]) -> dict[str, Any]:
   accounts = payload["accounts"]

   return {
      "account_count": payload["account_count"],
      "distinct_ids": len({account["id"] for account in accounts}),
      "with_friendship_status": sum(
         account["friendship_status"] is not None for account in accounts
      ),
      "is_private_values": sorted({str(account["is_private"]) for account in accounts}),
   }


def summarise_post(payload: dict[str, Any]) -> dict[str, Any]:
   post = payload["post"]

   return {
      "by_id": payload["by_id"],
      "pk_prefix": prefix(post["pk"]),
      "media_type": post["media_type"],
      "carousel_media_count": post["carousel_media_count"],
      "has_location": post["location"] is not None,
      "user_tag_count": len(post["user_tags"]) if post["user_tags"] is not None else None,
      "collaborators_is_null": post["collaborators"] is None,
      "accessibility_caption_is_null": post["accessibility_caption"] is None,
   }


def summarise_strip(payload: dict[str, Any]) -> dict[str, Any]:
   posts = payload["posts"]

   return {
      "post_count": payload["post_count"],
      "distinct_pks": len({post["pk"] for post in posts}),
      "every_author_is_the_author": all(
         post["author_id"] == payload["author_id"] for post in posts
      ),
      "media_types": sorted({post["media_type"] for post in posts}),
   }


def main() -> int:
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

      feed = run("feed", ["feed", "--posts-only"], summarise_feed)
      post = most_commented(feed) if feed else None

      if post is None:
         outcome = "stopped" if feed is None else "no post on the first page"
      else:
         post_pk = post["pk"]
         author_id = post["author"]["id"]
         comments = run("comments", ["comments", post_pk], summarise_comments)
         comment = most_replied(comments) if comments else None

         if comments is None:
            outcome = "stopped"
         elif comment is None:
            report["results"]["replies"] = "skipped, no comment on the first page has replies"
         else:
            replies_arguments = ["replies", post_pk, comment["id"], "--pages", "2"]

            if run("replies", replies_arguments, summarise_replies) is None:
               outcome = "stopped"

         plan: list[tuple[str, list[str], Callable[..., Any]]] = [
            ("likers", ["likers", post_pk], summarise_likers),
            ("post by id", ["post", "--by-id", post_pk], summarise_post),
            ("more from author", ["more-from-author", author_id], summarise_strip),
         ]

         for label, arguments, summarise in plan:
            if outcome != "done":
               break

            if run(label, arguments, summarise) is None:
               outcome = "stopped"

      report["requests_spent"] = len(requests_sent(request_log))

   report["outcome"] = outcome
   report_run("e2-post-depth-cli" if outcome == "done" else "e2-post-depth-cli-stopped", report)

   return 0 if outcome == "done" else 3


if __name__ == "__main__":
   sys.exit(main())
