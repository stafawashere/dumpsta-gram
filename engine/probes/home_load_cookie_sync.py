"""Writes once. Ten live requests at most, two of them to facebook.com, about 12 s.

Posts to ``/sync/instagram/`` and may change the saved ``fr``, both approved by the owner on
2026-09-23 for this one run. It is the first time the engine sends the page-load cookie sync.

Answers whether a home load driven through the public client sends its companions and then,
seconds later and outside the pacer slot, the four-request cookie sync tail: the facebook.com
``login_sync`` iframe document, ``PolarisAPIGetFrCookieQuery``, the facebook.com sync fetch and
the post back to ``/sync/instagram/``. It calls ``AsyncClient.feed()`` under the default parity
behavior, so every request is built, sent and read by the library's own code, and keeps the
client open until the tail has finished or 16 s have passed since the document.

The only thing the probe adds is a recorder around ``HttpxTransport.send``, which also refuses
an eleventh request. Per request it records the host, the path or friendly name, the status,
the response length, the classification and the offsets from the document's departure, plus the
names of any cookie a response set. ``fr`` is recorded as presence and length before and after,
never its value. The session is saved afterwards, as the CLI would, so the answer persists.

It sends nothing without ``--approved``, because it writes.

Run it from `engine/` with:

   uv run python probes/home_load_cookie_sync.py --approved
"""

from __future__ import annotations

import asyncio
import sys
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from _probe_support import SESSION_PATH, load_env, report_run

from dumpstagram._private.transport import HttpxTransport, Request, Response
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT
from dumpstagram._private.web.classify import classify, classify_checkpoint_only
from dumpstagram._private.web.cookie_sync import read_fr, read_sync_data
from dumpstagram.aio import AsyncClient
from dumpstagram.errors import DumpstagramError, TransportFailure
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE")

REQUEST_CAP = 10
TAIL_WAIT_SECONDS = 16.0

current_entry: ContextVar[dict[str, Any] | None] = ContextVar("current_entry", default=None)


def fr_state(session: Session) -> dict[str, object]:
   return {"present": session.fr is not None, "length": len(session.fr or "")}


def cookie_names(client: httpx.AsyncClient) -> list[str]:
   return sorted({cookie.name for cookie in client.cookies.jar})


def classification_of(response: Response) -> str:
   content_type = response.headers.get("content-type", "")
   is_document = content_type.startswith("text/html")

   try:
      if is_document:
         classify_checkpoint_only(response)
         return "document"

      classify(response)
   except DumpstagramError as failure:
      return type(failure).__name__

   return "ok"


def answer_lengths(path: str, friendly_name: str | None, response: Response) -> dict[str, object]:
   """Lengths the tail's readers take out of its two JSON answers, never the values."""

   try:
      if friendly_name == "PolarisAPIGetFrCookieQuery":
         return {"fr_answer_length": len(read_fr(response))}

      if path == "/instagram/sync/":
         return {"sync_data_length": len(read_sync_data(response))}
   except DumpstagramError as failure:
      return {"reader_failed_with": type(failure).__name__}

   return {}


class Recorder:
   def __init__(self) -> None:
      self.entries: list[dict[str, Any]] = []
      self.refused = 0
      self.origin: float | None = None

   def offset_ms(self, instant: float) -> int:
      origin = self.origin if self.origin is not None else instant

      return int((instant - origin) * 1000)

   def install(self) -> None:
      original_send = HttpxTransport.send
      recorder = self

      async def recorded_send(transport: HttpxTransport, request: Request) -> Response:
         is_over_budget = len(recorder.entries) >= REQUEST_CAP

         if is_over_budget:
            recorder.refused += 1
            raise TransportFailure("the probe's request budget is spent")

         departed = time.monotonic()

         if recorder.origin is None:
            recorder.origin = departed

         url = urlsplit(request.url)
         friendly_name = request.headers.get("x-fb-friendly-name")
         entry: dict[str, Any] = {
            "index": len(recorder.entries) + 1,
            "method": request.method,
            "host": url.hostname,
            "path": url.path,
            "name": friendly_name or url.path,
            "departed_ms": recorder.offset_ms(departed),
            "request_body_length": len(request.content or b""),
            "set_cookie_names": [],
         }
         recorder.entries.append(entry)
         current_entry.set(entry)

         try:
            response = await original_send(transport, request)
         except DumpstagramError as failure:
            entry["failed_with"] = type(failure).__name__
            entry["answered_ms"] = recorder.offset_ms(time.monotonic())
            raise

         entry["answered_ms"] = recorder.offset_ms(time.monotonic())
         entry["status"] = response.status_code
         entry["response_length"] = len(response.content)
         entry["content_type"] = response.headers.get("content-type", "").split(";")[0]
         entry["classification"] = classification_of(response)
         entry.update(answer_lengths(url.path, friendly_name, response))

         return response

      HttpxTransport.send = recorded_send


async def note_set_cookie_names(response: httpx.Response) -> None:
   entry = current_entry.get()

   if entry is None:
      return

   set_cookies = response.headers.get_list("set-cookie")
   entry["set_cookie_names"] = sorted({line.split("=", 1)[0].strip() for line in set_cookies})


def watch_set_cookies(client: httpx.AsyncClient) -> None:
   hooks = client.event_hooks
   hooks["response"] = [*hooks.get("response", []), note_set_cookie_names]
   client.event_hooks = hooks


async def run(approved: bool) -> int:
   if not approved:
      print("this probe posts to /sync/instagram/, pass --approved to send it")

      return 2

   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}

   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT") or DEFAULT_USER_AGENT

   report: dict[str, object] = {
      "session_path": str(session_path),
      "credentials_read_from_env": False,
      "request_cap": REQUEST_CAP,
   }

   try:
      session = Session.load(session_path)
   except (OSError, DumpstagramError) as failure:
      report["failed_with"] = type(failure).__name__
      report["requests_spent"] = 0

      report_run("home-load-cookie-sync-failed", report)

      return 2

   report["fr_before"] = fr_state(session)
   report["checkpoint_active_before"] = session.checkpoint_active

   recorder = Recorder()
   recorder.install()

   client = AsyncClient(session, user_agent=user_agent)
   instagram_client = client._sender._sender._client
   facebook_client = client._facebook._client
   watch_set_cookies(instagram_client)
   watch_set_cookies(facebook_client)

   report["behavior"] = {
      "feed_first_page": client.behavior.feed_first_page.name,
      "page_load_companions": client.behavior.page_load_companions,
      "cookie_sync": client.behavior.cookie_sync,
   }
   report["instagram_jar_names_before"] = cookie_names(instagram_client)

   exit_code = 0

   try:
      page = await client.feed()
      report["feed_page"] = {
         "item_count": len(page.items),
         "has_next_page": page.has_next_page,
      }
      report["tail_pending_after_feed"] = client._cookie_sync.pending

      while client._cookie_sync.pending:
         since_document = time.monotonic() - (recorder.origin or time.monotonic())

         if since_document > TAIL_WAIT_SECONDS:
            break

         await asyncio.sleep(0.25)

      report["tail_pending_at_close"] = client._cookie_sync.pending
   except DumpstagramError as failure:
      report["failed_with"] = type(failure).__name__
      report["failure_text"] = str(failure)[:200]
      exit_code = 3
   finally:
      report["instagram_jar_names_after"] = cookie_names(instagram_client)
      report["facebook_jar_names_after"] = cookie_names(facebook_client)
      await client.aclose()

   report["requests"] = recorder.entries
   report["requests_spent"] = len(recorder.entries)
   report["requests_refused_by_cap"] = recorder.refused
   report["hosts"] = {
      host: sum(1 for entry in recorder.entries if entry["host"] == host)
      for host in sorted({str(entry["host"]) for entry in recorder.entries})
   }
   report["fr_after"] = fr_state(session)
   report["checkpoint_active_after"] = session.checkpoint_active

   should_save = exit_code == 0 and not session.checkpoint_active

   if should_save:
      session.save(session_path)

   report["session_saved"] = should_save

   kind = "home-load-cookie-sync" if exit_code == 0 else "home-load-cookie-sync-failed"
   report_run(kind, report)

   return exit_code


if __name__ == "__main__":
   sys.exit(asyncio.run(run("--approved" in sys.argv[1:])))
