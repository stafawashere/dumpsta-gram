"""Posts a photo and a two slide carousel from the dumpsta command and deletes both. 13 requests.

E1 item 9's stop condition: a photo and a two item carousel are posted, read back, and deleted
from ``dumpsta`` in one run. This drives the installed console script as ``uv run dumpsta --json``
subprocesses and never imports the library, as ``phase3_cli_acceptance.py`` did.

   profile --by-id <viewer>       1 request, media_count before
   publish-photo a.jpg            3, the upload, the publish and the read back by code
   delete-post PK CODE            2, the delete and the read that shows it gone
   publish-carousel b.jpg c.jpg   4, two uploads, the publish and the read back
   delete-post PK CODE            2
   profile --by-id <viewer>       1, media_count after, which must equal the one before

Thirteen when the stored tokens are accepted, and one more for each bootstrap, so the counter in
``cli_request_counter/`` refuses the seventeenth. Each process has its own pacer, so the probe
spaces commands itself: 2.85 s after the previous one, and 30 s plus a mean 5 s of jitter after
the previous write before the next write command.

Approved by the owner on 2026-09-23: images generated here, solid colour squares, an empty
caption, nothing that names or tags anyone, and every post deleted in this run. It stops on a
``CheckpointRequired`` exit at once. On a ``RateLimited`` exit or any failed write it stops, and
when a post is up at that moment it sends that post's one delete unless the stop was a
checkpoint. A post left up is printed with its code.

Recorded: exit codes, error class names, ids of the owner's own posts, counts, booleans, the
requests each command sent and timings. No caption, no username.

It sends nothing without ``--approve posting``. Run it from `engine/` with:

   uv run python probes/posting_cli_acceptance.py --approve posting
"""

from __future__ import annotations

import argparse
import io
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
from PIL import Image

REQUEST_CAP = 16
READ_GAP_SECONDS = 2.85
WRITE_FLOOR_SECONDS = 30.0
WRITE_MEAN_JITTER_SECONDS = 5.0

EXIT_CHECKPOINT = 4

COUNTER_DIRECTORY = Path(__file__).resolve().parent / "cli_request_counter"

ENVIRONMENT_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE")

COLOURS = ((46, 111, 158), (201, 130, 43), (74, 140, 90), (150, 70, 120))

Payload = dict[str, Any]


class Halted(Exception):
   def __init__(
      self, reason: str, *, checkpoint: bool = False, printed: dict[str, object] | None = None
   ) -> None:
      super().__init__(reason)
      self.checkpoint = checkpoint
      self.printed = printed


class Run:
   def __init__(self, session_path: Path, user_agent: str | None, request_log: Path) -> None:
      self.session_path = session_path
      self.user_agent = user_agent
      self.request_log = request_log
      self.steps: list[dict[str, object]] = []
      self.started_at = time.monotonic()
      self.last_command_ended_at: float | None = None
      self.last_write_ended_at: float | None = None

   def requests_sent(self) -> list[dict[str, object]]:
      if not self.request_log.exists():
         return []

      return [json.loads(line) for line in self.request_log.read_text().splitlines()]

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
      self, label: str, arguments: list[str], *, cost: int, is_write: bool
   ) -> tuple[int, Payload | None]:
      spent = len(self.requests_sent())
      would_pass_the_cap = spent + cost > REQUEST_CAP

      if would_pass_the_cap:
         raise Halted(f"{spent} requests spent, {label} costs {cost}, the cap is {REQUEST_CAP}")

      self.wait_for_turn(is_write)

      step_number = len(self.steps) + 1
      command = ["uv", "run", "dumpsta", "--session", str(self.session_path), "--json"]
      command += arguments

      if self.user_agent:
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
         command, cwd=ENGINE_ROOT, env=child_environment, capture_output=True, text=True
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
         lines = [line for line in completed.stderr.splitlines() if line.strip()]
         step["error_class"] = lines[0].split(":")[0] if lines else None
         step["note_count"] = max(0, len(lines) - 1)

      if "refusing request" in completed.stderr:
         raise Halted(f"the counter refused a request in {label}")

      payload: Payload | None = None

      if completed.stdout.strip():
         try:
            payload = json.loads(completed.stdout)
         except json.JSONDecodeError:
            step["stdout_was_not_json"] = True

      if completed.returncode == EXIT_CHECKPOINT:
         printed = _ids_only(payload)
         step["payload_on_halt"] = printed
         raise Halted(f"CheckpointRequired in {label}", checkpoint=True, printed=printed)

      return completed.returncode, payload


def _ids_only(payload: Payload | None) -> dict[str, object] | None:
   if payload is None:
      return None

   post = payload.get("post") or {}

   return {"pk": post.get("pk"), "code": post.get("code")}


def square_jpeg(path: Path, colour: tuple[int, int, int]) -> Path:
   buffer = io.BytesIO()
   Image.new("RGB", (1080, 1080), colour).save(buffer, "JPEG", quality=90)
   path.write_bytes(buffer.getvalue())

   return path


def media_count(run: Run, viewer_id: str, label: str) -> int | None:
   code, payload = run.dumpsta(label, ["profile", "--by-id", viewer_id], cost=1, is_write=False)

   if code != 0 or payload is None:
      raise Halted(f"{label} exited {code}")

   return int(payload["profile"]["media_count"])


def publish_and_delete(
   run: Run, label: str, arguments: list[str], cost: int, report: dict[str, Any]
) -> dict[str, object]:
   result: dict[str, object] = {}
   code, published = run.dumpsta(f"{label} publish", arguments, cost=cost, is_write=True)
   post = (published or {}).get("post")
   result["publish_exit"] = code

   if post is None:
      raise Halted(f"{label} publish exited {code} with no post printed")

   report["up"] = {"pk": post["pk"], "code": post["code"]}
   result["pk"] = post["pk"]
   result["code"] = post["code"]
   result["media_type"] = post["media_type"]
   result["upload_count"] = len(post["upload_ids"])
   result["confirmed_by_read"] = (published or {}).get("confirmed")
   read_back = (published or {}).get("read_back") or {}
   result["read_back_carousel_media_count"] = read_back.get("carousel_media_count")
   result["read_back_caption_is_empty"] = not read_back.get("caption")

   report["delete_attempted"] = post["code"]
   delete_code, deleted = run.dumpsta(
      f"{label} delete-post", ["delete-post", post["pk"], post["code"]], cost=2, is_write=True
   )
   result["delete_exit"] = delete_code
   result["gone"] = (deleted or {}).get("gone")
   result["read_refused_with"] = (deleted or {}).get("read_refused_with")

   if delete_code == 0 and result["gone"] is True:
      report.pop("up", None)
   else:
      raise Halted(f"{label} delete exited {delete_code}")

   if code != 0:
      raise Halted(f"{label} publish exited {code}, its post deleted and nothing more sent")

   return result


def cleanup(run: Run, report: dict[str, Any]) -> None:
   """The one delete a post still up gets after a stop that was not a checkpoint."""

   post = report.get("up")
   already_attempted = post is not None and report.get("delete_attempted") == post["code"]

   if post is None or already_attempted:
      return

   try:
      code, deleted = run.dumpsta(
         "cleanup delete-post", ["delete-post", post["pk"], post["code"]], cost=2, is_write=True
      )
   except Halted as halt:
      report["cleanup"] = str(halt)
      return

   report["cleanup"] = {"exit": code, "gone": (deleted or {}).get("gone")}

   if code == 0 and (deleted or {}).get("gone") is True:
      report.pop("up", None)


def run_all(approved: bool) -> int:
   environment = {key: value for key, value in load_env().items() if key in ENVIRONMENT_KEYS}
   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT") or None
   report: dict[str, Any] = {"approved": approved, "request_cap": REQUEST_CAP}

   if not approved:
      report["failed_with"] = "not approved, pass --approve posting"
      report_run("posting-cli-acceptance-refused", report)

      return 2

   viewer_id = json.loads(session_path.read_text())["ds_user_id"]

   with tempfile.TemporaryDirectory() as scratch:
      folder = Path(scratch)
      colours = random.sample(COLOURS, 3)
      photo = square_jpeg(folder / "a.jpg", colours[0])
      slides = [
         square_jpeg(folder / f"{name}.jpg", colour)
         for name, colour in zip("bc", colours[1:], strict=True)
      ]
      run = Run(session_path, user_agent, folder / "requests.jsonl")
      report["steps"] = run.steps

      try:
         before = media_count(run, viewer_id, "profile before")
         report["media_count_before"] = before
         report["photo"] = publish_and_delete(
            run, "photo", ["publish-photo", str(photo)], 3, report
         )
         report["carousel"] = publish_and_delete(
            run, "carousel", ["publish-carousel", *[str(slide) for slide in slides]], 4, report
         )
         after = media_count(run, viewer_id, "profile after")
         report["media_count_after"] = after
         report["media_count_restored"] = after == before
      except Halted as halt:
         report["halted_by"] = str(halt)
         printed_a_post = halt.printed is not None and halt.printed.get("code") is not None

         if printed_a_post and "up" not in report:
            report["up"] = halt.printed

         if not halt.checkpoint:
            cleanup(run, report)
      finally:
         requests = run.requests_sent()
         report["requests_spent"] = len(requests)
         report["requests_by_host"] = {
            host: sum(1 for entry in requests if entry["host"] == host)
            for host in sorted({str(entry["host"]) for entry in requests})
         }
         report["elapsed_s"] = round(time.monotonic() - run.started_at, 1)

   was_clean = report.get("media_count_restored") is True and "halted_by" not in report
   report_run("posting-cli-acceptance" if was_clean else "posting-cli-acceptance-failed", report)

   if "up" in report:
      print(f"LEFT UP: post {report['up']['code']} is still published", file=sys.stderr)

   return 0 if was_clean else 3


if __name__ == "__main__":
   parser = argparse.ArgumentParser()
   parser.add_argument("--approve", default="")
   arguments = parser.parse_args()

   sys.exit(run_all(arguments.approve == "posting"))
