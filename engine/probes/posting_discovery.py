"""Posts on the owner's own account and deletes in the same run. Seven or eight live requests.

E1 item 9's discovery run from the engine side. The browser observed the carousel flow once in
``run-2026-09-23-222948``: two uploads to ``i.instagram.com``, ``configure_sidecar``, and the
post page's delete. The single photo publish, ``configure``, was named from the composer bundle
only. This probe sends each through the engine's own builders and ``send_write``, which is the
second observation of the three the browser saw and the first two of the one it did not.

Stage ``photo``, seven requests: the viewer's profile for ``media_count``, one upload, one
publish, the post read back by its code, the delete, the same read once more to record what a
deleted post answers, and the profile again. Stage ``carousel``, eight: the same with two
uploads. One more for a bootstrap if the saved tokens are refused.

Approved by the owner on 2026-09-23, with these limits: only images generated here, a solid
colour square, an empty caption, no location, no tag, no collaborator, and every post deleted in
the run that made it. The profile's ``media_count`` is read before and after and must match.

Stops all traffic on ``CheckpointRequired``. On ``RateLimited`` or a rejected write it stops too,
and when a post is up at that moment it sends that post's one delete, never more. A post left up
is printed with its code.

Recorded: counts, lengths, key names, ids of the owner's own posts, error classes and codes,
timings. No caption, no username, no header value.

It sends nothing without ``--approve posting``. Run it from `engine/` with:

   uv run python probes/posting_discovery.py --approve posting --stage photo
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

from _probe_support import SESSION_PATH, load_env, report_run
from PIL import Image

from dumpstagram._core.pacer import Pacer, PacingPolicy, WritePolicy
from dumpstagram._core.posts import read_post
from dumpstagram._core.profiles import read_profile_by_id
from dumpstagram._core.redaction import redact
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.writes.posts import delete_post, publish_carousel, publish_photo
from dumpstagram._private.transport import HttpxTransport, Request, Response, cookies_for
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, INSTAGRAM_HOST
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.requests.media import build_post_request
from dumpstagram._private.web.requests.posting import UPLOAD_HOST
from dumpstagram.errors import CheckpointRequired, DumpstagramError
from dumpstagram.models import PublishedPost
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE")

STAGE_CAPS = {"photo": 8, "carousel": 9}

READ_PACING = PacingPolicy(floor_seconds=2.85, mean_jitter_seconds=0.0)

WRITE_POLICY = WritePolicy(stop_after_unrecognised_rejection=False)
"""The probe decides by hand which write follows a rejection, so the one cleanup delete can go."""

SQUARE_SIDE = 1080

COLOURS = ((46, 111, 158), (201, 130, 43), (74, 140, 90), (150, 70, 120), (90, 90, 90))


class Halted(Exception):
   """A checkpoint, a throttle or a rejected write. Nothing more goes out but one cleanup."""


class CountingTransport:
   """Counts what leaves on either host against one cap shared by both."""

   def __init__(self, inner: HttpxTransport, ledger: list[dict[str, object]], cap: int) -> None:
      self.inner = inner
      self.ledger = ledger
      self.cap = cap
      self.started_at = time.monotonic()

   async def send(self, request: Request) -> Response:
      if len(self.ledger) >= self.cap:
         raise RuntimeError(f"refusing request {len(self.ledger) + 1}, the cap is {self.cap}")

      entry: dict[str, object] = {
         "host": request.url.split("/")[2],
         "name": request.headers.get("x-fb-friendly-name", _path_kind(request.url)),
         "offset_ms": int((time.monotonic() - self.started_at) * 1000),
         "request_bytes": len(request.content or b""),
      }
      self.ledger.append(entry)

      response = await self.inner.send(request)
      entry["status"] = response.status_code
      entry["response_bytes"] = len(response.content)

      return response

   async def aclose(self) -> None:
      await self.inner.aclose()


def _path_kind(url: str) -> str:
   for marker in ("rupload_igphoto", "configure_sidecar", "configure", "/delete/"):
      if marker in url:
         return marker.strip("/")

   return "other"


def square_jpeg(colour: tuple[int, int, int]) -> bytes:
   buffer = io.BytesIO()
   Image.new("RGB", (SQUARE_SIDE, SQUARE_SIDE), colour).save(buffer, "JPEG", quality=90)

   return buffer.getvalue()


def shape(value: Any, depth: int = 0) -> Any:
   if depth > 3:
      return type(value).__name__

   if isinstance(value, dict):
      return {key: shape(item, depth + 1) for key, item in sorted(value.items())}

   if isinstance(value, list):
      return [shape(value[0], depth + 1), f"len {len(value)}"] if value else []

   if isinstance(value, str):
      return f"str len {len(value)}"

   return type(value).__name__


def failure_record(failure: BaseException) -> dict[str, object]:
   return {
      "error_class": type(failure).__name__,
      "code": getattr(failure, "code", None),
      "notes": [redact(note) for note in getattr(failure, "__notes__", [])],
      "text": redact(str(failure))[:300],
   }


def envelope_record(response: Response) -> dict[str, object]:
   """The upstream's own error fields, which are its text and not anybody's content."""

   try:
      parsed = json.loads(response.text)
   except json.JSONDecodeError:
      return {"json": False}

   errors = parsed.get("errors") if isinstance(parsed, dict) else None
   first = errors[0] if isinstance(errors, list) and errors else {}

   return {
      "top_keys": sorted(parsed) if isinstance(parsed, dict) else None,
      "error_count": len(errors) if isinstance(errors, list) else None,
      "first_error_keys": sorted(first) if isinstance(first, dict) else None,
      "first_error": {
         key: redact(str(first.get(key)))[:200]
         for key in ("code", "summary", "message", "description", "severity", "is_silent")
         if isinstance(first, dict) and key in first
      },
      "data_shape": shape(parsed.get("data")) if isinstance(parsed, dict) else None,
   }


async def media_count(sender: PacedSender, session: Session, user_agent: str) -> int:
   profile = await read_profile_by_id(sender, session, session.ds_user_id, user_agent=user_agent)

   return profile.media_count


async def read_after_delete(
   sender: PacedSender, session: Session, code: str, user_agent: str
) -> dict[str, object]:
   response = await sender.send(build_post_request(session, code, user_agent=user_agent))
   record: dict[str, object] = {"status": response.status_code, "bytes": len(response.content)}

   try:
      payload = classify(response)
   except DumpstagramError as failure:
      record["classified"] = failure_record(failure)
      record["envelope"] = envelope_record(response)

      return record

   record["shape"] = shape(payload)

   return record


async def run_stage(
   stage: str,
   sender: PacedSender,
   upload_sender: PacedSender,
   session: Session,
   user_agent: str,
   report: dict[str, Any],
) -> None:
   steps: list[dict[str, object]] = report["steps"]
   before = await media_count(sender, session, user_agent)
   report["media_count_before"] = before
   steps.append({"step": "profile before", "media_count": before})

   colours = random.sample(COLOURS, 2)
   published: PublishedPost | None = None
   halted_by: str | None = None

   try:
      if stage == "photo":
         published = await publish_photo(
            sender, upload_sender, session, square_jpeg(colours[0]), user_agent=user_agent
         )
      else:
         images = [square_jpeg(colour) for colour in colours]
         published = await publish_carousel(
            sender, upload_sender, session, images, user_agent=user_agent
         )
   except CheckpointRequired as failure:
      steps.append({"step": "publish", **failure_record(failure)})
      raise Halted("checkpoint during the publish") from failure
   except DumpstagramError as failure:
      steps.append({"step": "publish", **failure_record(failure)})
      halted_by = type(failure).__name__

   if published is None:
      after = await media_count(sender, session, user_agent)
      report["media_count_after"] = after
      steps.append({"step": "profile after a failed publish", "media_count": after})
      raise Halted(f"the publish failed with {halted_by}")

   report["post"] = {
      "pk": published.pk,
      "code": published.code,
      "code_length": len(published.code),
      "media_type": published.media_type,
      "upload_ids": list(published.upload_ids),
   }
   steps.append({"step": "publish", "pk": published.pk, "media_type": published.media_type})

   try:
      detail = await read_post(sender, session, published.code, user_agent=user_agent)
      steps.append(
         {
            "step": "read back",
            "pk_matches": detail.pk == published.pk,
            "id_matches": detail.id == published.id,
            "author_is_viewer": detail.author.id == session.ds_user_id,
            "media_type": detail.media_type,
            "carousel_media_count": detail.carousel_media_count,
            "caption_is_empty": not detail.caption,
            "image_count": len(detail.images),
         }
      )
   except CheckpointRequired as failure:
      steps.append({"step": "read back", **failure_record(failure)})
      report["left_up"] = published.code
      raise Halted("checkpoint on the read back, the post stays up") from failure
   except DumpstagramError as failure:
      steps.append({"step": "read back", **failure_record(failure)})

   try:
      await delete_post(sender, session, published.pk, published.code, user_agent=user_agent)
      steps.append({"step": "delete", "did_delete": True})
   except DumpstagramError as failure:
      steps.append({"step": "delete", **failure_record(failure)})
      report["left_up"] = published.code
      raise Halted("the delete failed, the post may still be up") from failure

   steps.append(
      {
         "step": "read after delete",
         **await read_after_delete(sender, session, published.code, user_agent),
      }
   )

   after = await media_count(sender, session, user_agent)
   report["media_count_after"] = after
   report["media_count_restored"] = after == before
   steps.append({"step": "profile after", "media_count": after})


async def run(stage: str, report: dict[str, Any]) -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}
   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT") or DEFAULT_USER_AGENT
   session = Session.load(session_path)
   ledger: list[dict[str, object]] = []
   cap = STAGE_CAPS[stage]

   www = CountingTransport(
      HttpxTransport(
         cookies=cookies_for(session), proxy=session.proxy, allowed_host=INSTAGRAM_HOST
      ),
      ledger,
      cap,
   )
   upload = CountingTransport(
      HttpxTransport(cookies=cookies_for(session), proxy=session.proxy, allowed_host=UPLOAD_HOST),
      ledger,
      cap,
   )
   pacer = Pacer()
   report["requests"] = ledger
   exit_code = 0

   async with PacedSender(www, pacer, READ_PACING, WRITE_POLICY) as sender:
      async with PacedSender(upload, pacer, READ_PACING, WRITE_POLICY) as upload_sender:
         try:
            await run_stage(stage, sender, upload_sender, session, user_agent, report)
         except Halted as halt:
            report["halted"] = str(halt)
            exit_code = 2

   session.save(session_path)
   report["request_count"] = len(ledger)

   return exit_code


def main() -> int:
   parser = argparse.ArgumentParser()
   parser.add_argument("--approve", required=True)
   parser.add_argument("--stage", choices=sorted(STAGE_CAPS), required=True)
   arguments = parser.parse_args()

   if arguments.approve != "posting":
      print("refused: pass --approve posting", file=sys.stderr)
      return 1

   report: dict[str, Any] = {"stage": arguments.stage, "steps": []}
   exit_code = 3

   try:
      exit_code = asyncio.run(run(arguments.stage, report))
   except Exception as failure:
      report["crashed"] = failure_record(failure)
   finally:
      report_run(f"posting-discovery-{arguments.stage}", report)

   if "left_up" in report:
      print(f"LEFT UP: post {report['left_up']} is still published", file=sys.stderr)

   return exit_code


if __name__ == "__main__":
   sys.exit(main())
