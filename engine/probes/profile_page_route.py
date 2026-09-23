"""Read only. Ten live requests, all against the signed-in account's own profile.

Answers whether the engine's profile page route works against the live upstream: the profile
page document, the account id read out of it, and the page's six queries sent together inside
one pacer slot, including the rotated timeline query on ``/graphql/query`` with its two path
headers. It also runs the departure route, which now resolves through that rotated query too.

The viewer's own account is used so that no third party's page is loaded. Its username is not
in the environment, so the first request is the profile query by id, which returns it.

Requests: 1 profile by id, then 7 for the page route (1 document, 6 queries), then 2 for the
queries route. It records per request the friendly name or method, status, response size,
whether the body carried an error envelope, and the gap from the previous departure. No
username, name, caption or id is written, only whether the ids agreed.

Run it from `engine/` with:

   uv run python probes/profile_page_route.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from _probe_support import SESSION_PATH, load_env, report_run

from dumpstagram._core.pacer import Pacer
from dumpstagram._core.profiles import read_profile, read_profile_by_id
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import HttpxTransport, Request, Response, cookies_for
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT
from dumpstagram.behavior import ProfileRoute
from dumpstagram.errors import DumpstagramError
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE")


def _path_kind(url: str) -> str:
   if "/graphql/query" in url:
      return "graphql/query"

   if "/api/graphql" in url:
      return "api/graphql"

   return "profile page"


class RecordingTransport:
   def __init__(self, inner: HttpxTransport) -> None:
      self.inner = inner
      self.records: list[dict[str, object]] = []
      self.started_at = time.monotonic()

   async def send(self, request: Request) -> Response:
      departed_ms = int((time.monotonic() - self.started_at) * 1000)
      response = await self.inner.send(request)
      body = response.text
      has_envelope = False

      if request.method == "POST":
         try:
            parsed = json.loads(body)
            has_envelope = bool(parsed.get("errors") or parsed.get("error"))
         except ValueError:
            has_envelope = True

      self.records.append(
         {
            "what": request.headers.get("x-fb-friendly-name") or request.method,
            "path": _path_kind(request.url),
            "departed_ms": departed_ms,
            "status": response.status_code,
            "bytes": len(body),
            "has_envelope": has_envelope,
            "sent_bloks_header": "x-bloks-version-id" in request.headers,
         }
      )

      return response

   async def aclose(self) -> None:
      await self.inner.aclose()


async def run() -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}

   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT") or DEFAULT_USER_AGENT

   report: dict[str, object] = {"session_path": str(session_path), "requests_planned": 10}

   try:
      session = Session.load(session_path)
   except (OSError, DumpstagramError) as failure:
      report["failed_with"] = type(failure).__name__

      report_run("profile-page-route-failed", report)

      return 2

   transport = RecordingTransport(HttpxTransport(cookies=cookies_for(session), proxy=session.proxy))

   try:
      async with PacedSender(transport, Pacer()) as sender:
         own = await read_profile_by_id(sender, session, session.ds_user_id, user_agent=user_agent)
         by_page = await read_profile(
            sender, session, own.username, route=ProfileRoute.PAGE, user_agent=user_agent
         )
         by_queries = await read_profile(
            sender, session, own.username, route=ProfileRoute.QUERIES, user_agent=user_agent
         )
   except DumpstagramError as failure:
      report["failed_with"] = type(failure).__name__
      report["failure_text"] = str(failure)[:200]
      report["requests"] = transport.records

      report_run("profile-page-route-failed", report)

      return 3

   report["requests_spent"] = len(transport.records)
   report["page_route_id_matches"] = by_page.id == own.id
   report["queries_route_id_matches"] = by_queries.id == own.id
   report["page_route_username_matches"] = by_page.username == own.username
   report["requests"] = transport.records

   report_run("profile-page-route", report)

   return 0


if __name__ == "__main__":
   sys.exit(asyncio.run(run()))
