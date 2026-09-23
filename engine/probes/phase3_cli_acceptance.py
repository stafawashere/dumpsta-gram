"""Writes ten times through the dumpsta command, reversing each. 26 live requests, 40 at most.

Phase 3's stop condition asks for every Phase 3 capability run once live from the ``dumpsta``
command, its effect confirmed by a read in the same run and reversed in the same run. The
earlier acceptance runs drove ``AsyncClient`` from probes, so this one drives the installed
console script instead, as ``uv run dumpsta --json ...`` subprocesses, and never imports the
library. Approved by the owner on 2026-09-23, on the owner's own account, own post and own note,
with the follow and the message going to the account the owner named.

Five cycles, each a read, a write, a confirming read, the reversal and a read confirming the
start is back, in order of exposure:

   note      note list, note set --audience close-friends, note list, note delete, note list
   like      post, unlike or like, post, the reverse, post, on the owner's own post
   comment   comments, comment, comments, delete-comment, comments, on the same post
   follow    profile --by-id, follow, profile --by-id, unfollow, profile --by-id
   direct    thread, send-message, thread, unsend-message (two requests), thread

26 requests when the stored tokens are accepted, and two more for each re-bootstrap. Every
command runs with ``cli_request_counter/`` on ``PYTHONPATH``, whose ``sitecustomize`` records
each request that leaves the process and refuses the 41st across the whole run.

Each process has its own pacer, so the spacing between processes is the probe's: 2.85 s after
the previous command, and before a write 30 s plus a mean 5 s of jitter from the previous
write's end, the default write spacing. A process holds no write stop either, so the probe
keeps one: after any failure no forward write goes out, only the reversal of one that applied.
A ``CheckpointRequired`` or ``RateLimited`` exit stops all traffic at once.

Refused before writing: a note already up, since a set replaces it; a post that is not the
named pk or not the viewer's own; a follow target whose username is not ``IG_FOLLOW_TARGET``,
or which the viewer already follows or has requested.

The texts are ``IG_NOTE_TEXT``, ``IG_COMMENT_TEXT`` and ``IG_DM_TEXT`` from the root ``.env``.
Recorded: exit codes, error class names, ids, counts, booleans, the requests each command sent
and timings. No text, no username, nothing a command printed.

It sends nothing without ``--approve phase3``. Run it from `engine/` with:

   uv run python probes/phase3_cli_acceptance.py --approve phase3
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from _probe_support import ENGINE_ROOT, SESSION_PATH, load_env, report_run

POST_PK = "3879825181007222959"
POST_CODE = "DXX6HIojRiv"
FOLLOW_TARGET_ID = "6722711538"
THREAD_FBID = "1071167815895546"

REQUEST_CAP = 40
READ_GAP_SECONDS = 2.85
WRITE_FLOOR_SECONDS = 30.0
WRITE_MEAN_JITTER_SECONDS = 5.0

HALTING_EXITS = {4: "CheckpointRequired", 5: "RateLimited"}

COUNTER_DIRECTORY = Path(__file__).resolve().parent / "cli_request_counter"

ENVIRONMENT_KEYS = (
   "IG_USER_AGENT",
   "IG_SESSION_FILE",
   "IG_NOTE_TEXT",
   "IG_COMMENT_TEXT",
   "IG_DM_TEXT",
   "IG_FOLLOW_TARGET",
)

Payload = dict[str, Any]


class Halted(Exception):
   """A checkpoint, a throttle, a spent budget or a blind counter. Nothing more goes out."""


class Run:
   def __init__(self, session_path: Path, user_agent: str | None, request_log: Path) -> None:
      self.session_path = session_path
      self.user_agent = user_agent
      self.request_log = request_log
      self.steps: list[dict[str, object]] = []
      self.started_at = time.monotonic()
      self.last_command_ended_at: float | None = None
      self.last_write_ended_at: float | None = None
      self.writes_stopped_by: str | None = None

   def requests_sent(self) -> list[dict[str, object]]:
      if not self.request_log.exists():
         return []

      lines = self.request_log.read_text(encoding="utf-8").splitlines()

      return [json.loads(line) for line in lines]

   def wait_for_turn(self, is_write: bool) -> None:
      now = time.monotonic()
      ready_at = now

      if self.last_command_ended_at is not None:
         ready_at = max(ready_at, self.last_command_ended_at + READ_GAP_SECONDS)

      follows_an_earlier_write = is_write and self.last_write_ended_at is not None

      if follows_an_earlier_write:
         assert self.last_write_ended_at is not None
         jitter = random.random() * 2.0 * WRITE_MEAN_JITTER_SECONDS
         ready_at = max(ready_at, self.last_write_ended_at + WRITE_FLOOR_SECONDS + jitter)

      time.sleep(max(0.0, ready_at - now))

   def dumpsta(
      self,
      label: str,
      arguments: list[str],
      *,
      cost: int = 1,
      is_write: bool = False,
      takes_request_options: bool = True,
   ) -> Payload | None:
      spent = len(self.requests_sent())
      would_pass_the_cap = spent + cost > REQUEST_CAP

      if would_pass_the_cap:
         raise Halted(f"{spent} requests spent, {label} costs {cost}, the cap is {REQUEST_CAP}")

      if cost:
         self.wait_for_turn(is_write)

      step_number = len(self.steps) + 1
      command = ["uv", "run", "dumpsta", "--session", str(self.session_path), "--json"]
      command += arguments

      if takes_request_options and self.user_agent:
         command += ["--user-agent", self.user_agent]

      child_environment = {
         **os.environ,
         "PYTHONPATH": str(COUNTER_DIRECTORY),
         "DUMPSTA_PROBE_REQUEST_LOG": str(self.request_log),
         "DUMPSTA_PROBE_REQUEST_CAP": str(REQUEST_CAP),
         "DUMPSTA_PROBE_STEP": str(step_number),
      }

      launched_at = time.monotonic()
      completed = subprocess.run(
         command,
         cwd=ENGINE_ROOT,
         env=child_environment,
         capture_output=True,
         text=True,
         check=False,
      )
      ended_at = time.monotonic()

      self.last_command_ended_at = ended_at

      if is_write:
         self.last_write_ended_at = ended_at

      requests = [entry for entry in self.requests_sent() if entry["step"] == str(step_number)]
      step: dict[str, object] = {
         "step": step_number,
         "label": label,
         "exit": completed.returncode,
         "requests": len(requests),
         "sent": [
            {key: entry.get(key) for key in ("host", "name", "status", "failed_with")}
            for entry in requests
         ],
         "started_at_s": round(launched_at - self.started_at, 1),
         "elapsed_ms": int((ended_at - launched_at) * 1000),
      }
      self.steps.append(step)
      print(f"step {step_number} {label}: exit {completed.returncode}, {len(requests)} requests")

      if completed.returncode != 0:
         step["error_class"] = error_class_from(completed.stderr)

      refused_by_the_counter = "refusing request" in completed.stderr

      if refused_by_the_counter:
         raise Halted(f"the counter refused a request in {label}")

      if completed.returncode in HALTING_EXITS:
         raise Halted(f"{HALTING_EXITS[completed.returncode]} in {label}")

      if completed.returncode != 0:
         return None

      counter_saw_nothing = cost > 0 and not requests

      if counter_saw_nothing:
         raise Halted(f"{label} exited 0 and the counter saw no request, so it is not loaded")

      try:
         payload: Payload = json.loads(completed.stdout)
      except json.JSONDecodeError:
         step["stdout_was_not_json"] = True

         return None

      return payload

   def read(self, label: str, arguments: list[str], *, cost: int = 1) -> Payload | None:
      payload = self.dumpsta(label, arguments, cost=cost)

      if payload is None:
         self.stop_writes(label)

      return payload

   def write(
      self, label: str, arguments: list[str], *, reverses: bool = False, cost: int = 1
   ) -> tuple[bool, Payload | None]:
      """Send one write. Returns whether it was sent at all, and what it printed on success."""

      is_refused_by_the_stop = self.writes_stopped_by is not None and not reverses

      if is_refused_by_the_stop:
         self.steps.append(
            {"label": label, "not_sent": f"writes stopped by {self.writes_stopped_by}"}
         )

         return False, None

      payload = self.dumpsta(label, arguments, cost=cost, is_write=True)

      if payload is None:
         self.stop_writes(label)

      return True, payload

   def stop_writes(self, label: str) -> None:
      if self.writes_stopped_by is None:
         self.writes_stopped_by = label


def error_class_from(stderr: str) -> str | None:
   lines = [line for line in stderr.splitlines() if line.strip()]

   if not lines:
      return None

   first_word = lines[-1].split(":")[0].strip()
   is_an_identifier = first_word.isidentifier()

   return first_word if is_an_identifier else "unparsed"


def note_cycle(run: Run, text: str) -> dict[str, object]:
   result: dict[str, object] = {}

   before = run.read("note list, before", ["note", "list"])

   if before is None:
      return result

   result["before"] = {"note_count": before["note_count"], "own_note_id": before["own_note_id"]}

   if before["own_note_id"] is not None:
      result["refused"] = "a note is already up and a set would replace it"
      run.stop_writes("note precondition")

      return result

   sent, created = run.write("note set", ["note", "set", text, "--audience", "close-friends"])

   if not sent:
      return result

   created_id = created["note"]["id"] if created else None
   result["set_exit_ok"] = created is not None
   result["created_note_id"] = created_id
   result["created_audience"] = created["note"]["audience"] if created else None

   middle = run.read("note list, after the set", ["note", "list"])
   own_note_after_the_set = own_note_in(middle)

   if own_note_after_the_set is not None:
      result["after_set"] = {
         "note_count": middle["note_count"] if middle else None,
         "own_note_id": own_note_after_the_set["id"],
         "is_the_created_note": own_note_after_the_set["id"] == created_id,
         "audience": own_note_after_the_set["audience"],
         "text_matches": own_note_after_the_set["text"] == text,
      }
   else:
      result["after_set"] = {"own_note_id": None}

   note_to_delete = created_id or (own_note_after_the_set or {}).get("id")

   if note_to_delete is None:
      return result

   _, deleted = run.write("note delete", ["note", "delete", note_to_delete], reverses=True)
   result["delete_exit_ok"] = deleted is not None

   after = run.read("note list, after the delete", ["note", "list"])

   if after is not None:
      result["after_delete"] = {
         "note_count": after["note_count"],
         "own_note_id": after["own_note_id"],
      }
      result["restored"] = after["own_note_id"] is None

   return result


def own_note_in(listing: Payload | None) -> Payload | None:
   if listing is None:
      return None

   own_notes = [note for note in listing["notes"] if note["is_own"]]

   return own_notes[0] if own_notes else None


def describe_post(payload: Payload) -> dict[str, object]:
   post = payload["post"]

   return {"pk": post["pk"], "has_liked": post["has_liked"], "like_count": post["like_count"]}


def like_cycle(run: Run, viewer_id: str) -> dict[str, object]:
   result: dict[str, object] = {}

   before = run.read("post, before", ["post", POST_CODE])

   if before is None:
      return result

   result["before"] = describe_post(before)
   is_the_named_post = before["post"]["pk"] == POST_PK
   is_own_post = before["post"]["author"]["id"] == viewer_id

   if not (is_the_named_post and is_own_post):
      result["refused"] = "the post is not the named pk on the viewer's own account"
      run.stop_writes("like precondition")

      return result

   started_liked = before["post"]["has_liked"]
   away, back = ("unlike", "like") if started_liked else ("like", "unlike")
   result["order"] = [away, back]

   sent, moved = run.write(away, [away, POST_PK])

   if not sent:
      return result

   result["away_exit_ok"] = moved is not None

   middle = run.read(f"post, after {away}", ["post", POST_CODE])

   if middle is not None:
      result["middle"] = describe_post(middle)

   flipped = middle is not None and middle["post"]["has_liked"] is not started_liked
   result["flipped_in_the_middle"] = flipped

   if moved is not None and middle is not None:
      result["like_count_moved_by_one"] = (
         abs(middle["post"]["like_count"] - before["post"]["like_count"]) == 1
      )

   needs_reversing = moved is not None or flipped or middle is None

   if not needs_reversing:
      return result

   _, returned = run.write(back, [back, POST_PK], reverses=True)
   result["back_exit_ok"] = returned is not None

   after = run.read(f"post, after {back}", ["post", POST_CODE])

   if after is not None:
      result["after"] = describe_post(after)
      result["restored"] = (
         after["post"]["has_liked"] is started_liked
         and after["post"]["like_count"] == before["post"]["like_count"]
      )

   return result


def describe_comments(payload: Payload, viewer_id: str) -> dict[str, object]:
   return {
      "comment_count": payload["comment_count"],
      "comment_ids": [comment["id"] for comment in payload["comments"]],
      "viewer_comment_ids": [
         comment["id"] for comment in payload["comments"] if comment["author"]["id"] == viewer_id
      ],
      "more_available": payload["more_available"],
   }


def comment_cycle(run: Run, viewer_id: str, text: str) -> dict[str, object]:
   result: dict[str, object] = {}

   before = run.read("comments, before", ["comments", POST_PK])

   if before is None:
      return result

   result["before"] = describe_comments(before, viewer_id)
   ids_before = {comment["id"] for comment in before["comments"]}

   sent, created = run.write("comment", ["comment", POST_PK, text])

   if not sent:
      return result

   created_id = created["comment"]["id"] if created else None
   result["comment_exit_ok"] = created is not None
   result["created_comment_id"] = created_id

   middle = run.read("comments, after the comment", ["comments", POST_PK])
   to_delete: list[str] = []

   if created_id is not None:
      to_delete.append(created_id)

   if middle is not None:
      result["middle"] = describe_comments(middle, viewer_id)
      listed = [comment for comment in middle["comments"] if comment["id"] == created_id]
      result["created_is_listed"] = bool(listed)

      if listed:
         result["text_matches"] = listed[0]["text"] == text
         result["author_is_viewer"] = listed[0]["author"]["id"] == viewer_id

      strays = [
         comment["id"]
         for comment in middle["comments"]
         if comment["author"]["id"] == viewer_id and comment["id"] not in ids_before
      ]

      if created_id is None:
         to_delete.extend(strays[:1])

   for comment_id in to_delete:
      _, deleted = run.write(
         "delete-comment", ["delete-comment", POST_PK, comment_id], reverses=True
      )
      result["delete_exit_ok"] = deleted is not None

   if not to_delete:
      return result

   after = run.read("comments, after the delete", ["comments", POST_PK])

   if after is not None:
      result["after"] = describe_comments(after, viewer_id)
      ids_after = {comment["id"] for comment in after["comments"]}
      result["restored"] = ids_after == ids_before

   return result


def describe_relationship(payload: Payload, target_username: str) -> dict[str, object]:
   profile = payload["profile"]
   status = profile["friendship_status"] or {}

   return {
      "id": profile["id"],
      "username_is_the_named_target": profile["username"] == target_username,
      "is_private": profile["is_private"],
      "following": status.get("following"),
      "outgoing_request": status.get("outgoing_request"),
      "follower_count": profile["follower_count"],
   }


def follow_cycle(run: Run, target_username: str) -> dict[str, object]:
   result: dict[str, object] = {}
   profile_arguments = ["profile", "--by-id", FOLLOW_TARGET_ID]

   before = run.read("profile --by-id, before", profile_arguments)

   if before is None:
      return result

   relationship_before = describe_relationship(before, target_username)
   result["before"] = relationship_before

   is_the_named_account = (
      relationship_before["id"] == FOLLOW_TARGET_ID
      and relationship_before["username_is_the_named_target"]
   )
   already_related = bool(relationship_before["following"]) or bool(
      relationship_before["outgoing_request"]
   )

   if not is_the_named_account or already_related:
      result["refused"] = "not the named account, or already followed or requested"
      run.stop_writes("follow precondition")

      return result

   sent, followed = run.write("follow", ["follow", FOLLOW_TARGET_ID])

   if not sent:
      return result

   result["follow_exit_ok"] = followed is not None

   middle = run.read("profile --by-id, after the follow", profile_arguments)
   related_in_the_middle = False

   if middle is not None:
      relationship_middle = describe_relationship(middle, target_username)
      result["middle"] = relationship_middle
      related_in_the_middle = bool(relationship_middle["following"]) or bool(
         relationship_middle["outgoing_request"]
      )

   result["related_in_the_middle"] = related_in_the_middle
   needs_reversing = followed is not None or related_in_the_middle or middle is None

   if not needs_reversing:
      return result

   _, unfollowed = run.write("unfollow", ["unfollow", FOLLOW_TARGET_ID], reverses=True)
   result["unfollow_exit_ok"] = unfollowed is not None

   after = run.read("profile --by-id, after the unfollow", profile_arguments)

   if after is not None:
      relationship_after = describe_relationship(after, target_username)
      result["after"] = relationship_after
      result["restored"] = (
         not relationship_after["following"] and not relationship_after["outgoing_request"]
      )

   return result


def describe_thread(payload: Payload, viewer_id: str) -> dict[str, object]:
   return {
      "message_count": payload["message_count"],
      "viewer_message_count": sum(
         1 for message in payload["messages"] if message["sender_igid"] == viewer_id
      ),
      "more_available": payload["more_available"],
   }


def direct_cycle(run: Run, viewer_id: str, text: str) -> dict[str, object]:
   result: dict[str, object] = {}
   thread_arguments = ["thread", THREAD_FBID]

   before = run.read("thread, before", thread_arguments)

   if before is None:
      return result

   result["before"] = describe_thread(before, viewer_id)
   ids_before = {message["id"] for message in before["messages"]}

   sent, delivered = run.write("send-message", ["send-message", THREAD_FBID, text])

   if not sent:
      return result

   sent_message = delivered["message"] if delivered else None
   sent_id = sent_message["id"] if sent_message else None
   sent_offline_id = sent_message["offline_threading_id"] if sent_message else None
   result["send_exit_ok"] = delivered is not None
   result["sent_message_id"] = sent_id
   result["sent_offline_threading_id"] = sent_offline_id

   middle = run.read("thread, after the send", thread_arguments)
   to_unsend: list[str] = []

   if sent_id is not None:
      to_unsend.append(sent_id)

   if middle is not None:
      result["middle"] = describe_thread(middle, viewer_id)
      found_by_id = [message for message in middle["messages"] if message["id"] == sent_id]
      found_by_offline_id = [
         message
         for message in middle["messages"]
         if sent_offline_id is not None and message["offline_threading_id"] == sent_offline_id
      ]
      result["found_by_id"] = bool(found_by_id)
      result["found_by_offline_threading_id"] = bool(found_by_offline_id)
      found = found_by_id or found_by_offline_id

      if found:
         result["text_matches"] = found[0]["text"] == text
         result["sender_is_viewer"] = found[0]["sender_igid"] == viewer_id

      strays = [
         message["id"]
         for message in middle["messages"]
         if message["id"] not in ids_before
         and message["sender_igid"] == viewer_id
         and message["text"] == text
      ]

      if sent_id is None:
         to_unsend.extend(strays[:1])

   for message_id in to_unsend:
      _, unsent = run.write(
         "unsend-message",
         ["unsend-message", THREAD_FBID, message_id],
         reverses=True,
         cost=2,
      )
      result["unsend_exit_ok"] = unsent is not None

   if not to_unsend:
      return result

   after = run.read("thread, after the unsend", thread_arguments)

   if after is not None:
      result["after"] = describe_thread(after, viewer_id)
      ids_after = {message["id"] for message in after["messages"]}
      result["sent_message_gone"] = all(message_id not in ids_after for message_id in to_unsend)
      result["restored"] = ids_after == ids_before

   return result


def run_all(approved: bool) -> int:
   environment = {key: value for key, value in load_env().items() if key in ENVIRONMENT_KEYS}

   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT") or None

   report: dict[str, object] = {"approved": approved, "request_cap": REQUEST_CAP}

   if not approved:
      report["failed_with"] = "not approved, pass --approve phase3"
      report_run("phase3-cli-acceptance-refused", report)

      return 2

   texts = {
      key: environment.get(key, "") for key in ("IG_NOTE_TEXT", "IG_COMMENT_TEXT", "IG_DM_TEXT")
   }
   target_username = environment.get("IG_FOLLOW_TARGET", "")
   missing = [key for key, value in texts.items() if not value]

   if not target_username:
      missing.append("IG_FOLLOW_TARGET")

   if missing:
      report["failed_with"] = f"missing from .env: {', '.join(missing)}"
      report_run("phase3-cli-acceptance-refused", report)

      return 2

   report["text_lengths"] = {key: len(value) for key, value in texts.items()}
   capabilities: dict[str, dict[str, object]] = {}
   report["capabilities"] = capabilities

   with tempfile.TemporaryDirectory() as scratch:
      run = Run(session_path, user_agent, Path(scratch) / "requests.jsonl")
      report["steps"] = run.steps

      try:
         session = run.dumpsta("session", ["session"], cost=0, takes_request_options=False)

         if session is None:
            raise Halted("dumpsta session did not answer")

         viewer_id = str(session["ds_user_id"])
         report["session_was_bootstrapped"] = session["bootstrapped"]

         capabilities["note"] = note_cycle(run, texts["IG_NOTE_TEXT"])
         capabilities["like"] = like_cycle(run, viewer_id)
         capabilities["comment"] = comment_cycle(run, viewer_id, texts["IG_COMMENT_TEXT"])
         capabilities["follow"] = follow_cycle(run, target_username)
         capabilities["direct"] = direct_cycle(run, viewer_id, texts["IG_DM_TEXT"])
      except Halted as halt:
         report["halted_by"] = str(halt)
      finally:
         requests = run.requests_sent()
         report["requests_spent"] = len(requests)
         report["requests_by_host"] = {
            host: sum(1 for entry in requests if entry["host"] == host)
            for host in sorted({str(entry["host"]) for entry in requests})
         }
         report["elapsed_s"] = round(time.monotonic() - run.started_at, 1)
         report["writes_stopped_by"] = run.writes_stopped_by

   every_capability_restored = all(
      capabilities.get(name, {}).get("restored") is True
      for name in ("note", "like", "comment", "follow", "direct")
   )
   report["every_capability_restored"] = every_capability_restored

   was_clean = every_capability_restored and "halted_by" not in report
   was_clean = was_clean and report["writes_stopped_by"] is None

   report_run("phase3-cli-acceptance" if was_clean else "phase3-cli-acceptance-failed", report)

   return 0 if was_clean else 3


if __name__ == "__main__":
   parser = argparse.ArgumentParser()
   parser.add_argument("--approve", default="")
   arguments = parser.parse_args()

   sys.exit(run_all(arguments.approve == "phase3"))
