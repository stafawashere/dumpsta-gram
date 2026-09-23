"""Read only. One live request, the profile page document of an account that does not exist.

Answers what the upstream sends a plain HTTP client that navigates to a profile page for a
username nobody holds, before the engine's profile route treats that page as its first
request. Two browser cold loads on 2026-09-23 of real accounts carried the account id as
``"profile_id"``. What a missing account's page carries was never observed, and the route has
to tell a missing account from a dead session.

It records the status, whether the request was redirected, the document size, and whether
``fb_dtsg``, ``WebBloksVersioningID`` and ``profile_id`` are present. The username is made up
and only its length is written.

Run it from `engine/` with:

   uv run python probes/profile_page_document.py
"""

from __future__ import annotations

import asyncio
import re
import sys
import time
from pathlib import Path

from _probe_support import SESSION_PATH, load_env, report_run

from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import HttpxTransport, cookies_for
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, ORIGIN, build_document_request
from dumpstagram.errors import DumpstagramError
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE")
MADE_UP_USERNAME = "zq_no_such_account_7k3v9x2m"


async def run() -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}

   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT") or DEFAULT_USER_AGENT

   report: dict[str, object] = {
      "session_path": str(session_path),
      "credentials_read_from_env": False,
      "requests_spent": 1,
      "username_length": len(MADE_UP_USERNAME),
   }

   try:
      session = Session.load(session_path)
   except (OSError, DumpstagramError) as failure:
      report["failed_with"] = type(failure).__name__
      report["requests_spent"] = 0

      report_run("profile-page-document-failed", report)

      return 2

   transport = HttpxTransport(cookies=cookies_for(session), proxy=session.proxy)
   request = build_document_request(f"{ORIGIN}/{MADE_UP_USERNAME}/", user_agent)
   started_at = time.monotonic()

   try:
      async with PacedSender(transport, Pacer()) as sender:
         response = await sender.send(request)
   except DumpstagramError as failure:
      report["failed_with"] = type(failure).__name__
      report["failure_text"] = str(failure)[:200]

      report_run("profile-page-document-failed", report)

      return 3

   html = response.text
   final_path = response.final_url.split("instagram.com", 1)[-1]

   report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
   report["status"] = response.status_code
   report["redirected"] = final_path.rstrip("/") != f"/{MADE_UP_USERNAME}"
   report["final_path_is_login_or_challenge"] = bool(
      re.match(r"/(accounts|challenge)/", final_path)
   )
   report["document_bytes"] = len(html)
   report["has_fb_dtsg"] = '"DTSGInitialData",[],{"token":"' in html
   report["has_bloks_version"] = '"WebBloksVersioningID"' in html
   report["profile_id_count"] = len(re.findall(r'"profile_id":"\d+"', html))
   report["page_id_profile_count"] = html.count('"page_id":"profilePage_')

   report_run("profile-page-document", report)

   return 0


if __name__ == "__main__":
   sys.exit(asyncio.run(run()))
