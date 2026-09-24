"""Read only. One live request per page of the whole thread, plus one if the tokens are stale.

The thread measured on 2026-09-21 was 306 pages, so a full run is roughly 307 requests and,
at the library's default pacing, roughly fifteen minutes. It stops on the upstream's own
``has_next_page`` and nothing else, and it refuses to go past `MAX_PAGES` so a cursor that
loops cannot turn into an unbounded run against the account.

What it produces is the raw material for the recorded test oracle. Every GraphQL body is
written verbatim to `engine/exports/thread-oracle-<stamp>/pages/`, which is gitignored at the
repository root because those bodies carry message text and third-party names. Nothing in that
directory is a fixture. `scripts/build_thread_oracle.py` turns it into one, pseudonymised,
under `tests/fixtures/`.

The walk to the connection and the cursor is written out here rather than taken from the
mapper, so a page the mapper cannot map is still recorded and the run still reaches the end.
Each page is also offered to the mapper, and the outcome is logged per page, because a full
thread is the first chance to see content types the one measured page never carried.

A run that stops early leaves a manifest behind. Passing its directory with ``--resume``
continues from the last cursor it recorded instead of spending the first pages again.

Run it from `engine/` with:

   uv run python probes/capture_thread_oracle.py
   uv run python probes/capture_thread_oracle.py --resume exports/thread-oracle-<stamp>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from _probe_support import ENGINE_ROOT, SESSION_PATH, THREAD_FBID, load_env, report_run

from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._private.transport import HttpxTransport, cookies_for
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse.direct import parse_thread_message_page
from dumpstagram._private.web.requests.direct import build_thread_page_request
from dumpstagram.errors import DumpstagramError, SchemaChanged
from dumpstagram.session import Session

MAX_PAGES = 400
"""The 2026-09-21 thread was 306 pages. Past this, the cursor is looping or the thread grew
by a quarter overnight, and either one deserves a person looking before more requests go out."""

EXPORT_ROOT = ENGINE_ROOT / "exports"

CONNECTION_PATH = ("data", "fetch__SlideThread", "as_ig_direct_thread", "slide_messages")


def connection_of(payload: Any) -> dict[str, Any] | None:
   current = payload

   for key in CONNECTION_PATH:
      if not isinstance(current, dict):
         return None

      current = current.get(key)

   return current if isinstance(current, dict) else None


def load_manifest(export_dir: Path) -> dict[str, Any]:
   manifest_path = export_dir / "manifest.json"

   if manifest_path.exists():
      loaded: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))

      return loaded

   return {"thread_fbid_length": None, "pages": [], "finished": False}


def save_manifest(export_dir: Path, manifest: dict[str, Any]) -> None:
   manifest_path = export_dir / "manifest.json"
   manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def mapper_outcome(payload: Any) -> dict[str, Any]:
   try:
      page = parse_thread_message_page(payload)
   except SchemaChanged as failure:
      return {"mapped": False, "path": failure.path}

   return {"mapped": True, "items": len(page.items)}


async def capture(
   session: Session,
   thread_fbid: str,
   export_dir: Path,
   manifest: dict[str, Any],
   user_agent: str,
) -> dict[str, Any]:
   pages_dir = export_dir / "pages"
   pages_dir.mkdir(parents=True, exist_ok=True)

   recorded_pages: list[dict[str, Any]] = manifest["pages"]
   after = recorded_pages[-1]["end_cursor"] if recorded_pages else None
   requests_spent = 0
   stop_reason = "has_next_page false"

   transport = HttpxTransport(cookies=cookies_for(session), proxy=session.proxy)

   async with PacedSender(transport, Pacer()) as sender:

      async def one_page() -> Any:
         nonlocal requests_spent

         if not session.fb_dtsg:
            requests_spent += 1
            await bootstrap(sender, session, user_agent=user_agent)

         request = build_thread_page_request(
            session, thread_fbid, after=after, user_agent=user_agent
         )
         requests_spent += 1
         response = await sender.send(request)

         return classify(response)

      while True:
         page_index = len(recorded_pages)

         if page_index >= MAX_PAGES:
            stop_reason = f"MAX_PAGES {MAX_PAGES} reached"
            break

         started = time.monotonic()
         payload = await with_token_recovery(one_page, sender=sender, session=session)
         elapsed_ms = round((time.monotonic() - started) * 1000)

         page_path = pages_dir / f"page-{page_index:04d}.json"
         page_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

         connection = connection_of(payload)

         if connection is None:
            stop_reason = "connection path absent"
            break

         page_info = connection.get("page_info") or {}
         edges = connection.get("edges") or []
         has_next_page = page_info.get("has_next_page")
         end_cursor = page_info.get("end_cursor")

         recorded_pages.append(
            {
               "index": page_index,
               "file": page_path.name,
               "after": after,
               "edge_count": len(edges),
               "has_next_page": has_next_page,
               "end_cursor": end_cursor,
               "elapsed_ms": elapsed_ms,
               "mapper": mapper_outcome(payload),
            }
         )
         save_manifest(export_dir, manifest)

         print(
            f"page {page_index:4d}  edges {len(edges):3d}  next {has_next_page}  {elapsed_ms} ms",
            flush=True,
         )

         if has_next_page is not True:
            manifest["finished"] = has_next_page is False
            break

         if not end_cursor:
            stop_reason = "has_next_page true with no end_cursor"
            break

         after = end_cursor

   save_manifest(export_dir, manifest)

   return {"requests_spent": requests_spent, "stop_reason": stop_reason}


def census(export_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
   """Counts over every recorded page. Ids appear only as counts, never as values."""

   ids: list[str] = []
   timestamps: list[int] = []
   content_types: Counter[str] = Counter()
   typenames: Counter[str] = Counter()

   for page in manifest["pages"]:
      payload = json.loads((export_dir / "pages" / page["file"]).read_text(encoding="utf-8"))
      connection = connection_of(payload) or {}

      for edge in connection.get("edges") or []:
         node = edge.get("node") or {}
         ids.append(str(node.get("id")))
         content_types[str(node.get("content_type"))] += 1
         typenames[str(node.get("__typename"))] += 1

         timestamp_ms = node.get("timestamp_ms")

         if isinstance(timestamp_ms, str) and timestamp_ms.isdigit():
            timestamps.append(int(timestamp_ms))

   unmapped = [page for page in manifest["pages"] if not page["mapper"]["mapped"]]
   unmapped_paths = Counter(str(page["mapper"]["path"]) for page in unmapped)

   return {
      "pages": len(manifest["pages"]),
      "edges": len(ids),
      "distinct_ids": len(set(ids)),
      "duplicate_edges": len(ids) - len(set(ids)),
      "oldest_ms": min(timestamps) if timestamps else None,
      "newest_ms": max(timestamps) if timestamps else None,
      "content_types": dict(content_types.most_common()),
      "typenames": dict(typenames.most_common()),
      "pages_the_mapper_refused": len(unmapped),
      "refusal_paths": dict(unmapped_paths.most_common()),
      "edge_count_histogram": dict(Counter(page["edge_count"] for page in manifest["pages"])),
   }


def main() -> int:
   parser = argparse.ArgumentParser()
   parser.add_argument("--resume", type=Path, default=None)
   arguments = parser.parse_args()

   environment = load_env()
   thread_fbid = environment.get("IG_THREAD_FBID") or THREAD_FBID
   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT") or DEFAULT_USER_AGENT

   if arguments.resume is not None:
      export_dir = arguments.resume.resolve()
   else:
      stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
      export_dir = EXPORT_ROOT / f"thread-oracle-{stamp}"

   export_dir.mkdir(parents=True, exist_ok=True)
   manifest = load_manifest(export_dir)
   manifest["thread_fbid_length"] = len(thread_fbid)
   pages_before = len(manifest["pages"])

   report: dict[str, Any] = {
      "export_dir": str(export_dir),
      "session_path": str(session_path),
      "credentials_read_from_env": False,
      "resumed_from_page": pages_before if arguments.resume is not None else None,
   }

   started = time.monotonic()
   exit_code = 0

   try:
      session = Session.load(session_path)
      outcome = asyncio.run(capture(session, thread_fbid, export_dir, manifest, user_agent))
      report.update(outcome)
   except DumpstagramError as failure:
      report["failure"] = {"type": type(failure).__name__, "code": getattr(failure, "code", None)}
      exit_code = 1

   report["elapsed_s"] = round(time.monotonic() - started, 1)
   report["pages_this_run"] = len(manifest["pages"]) - pages_before
   report["finished"] = manifest["finished"]
   report["census"] = census(export_dir, manifest)

   report_run("thread-oracle-capture", report)

   return exit_code


if __name__ == "__main__":
   sys.exit(main())
