"""Read only. Three live requests: the home document, then two of the bundles it names.

The E1 item 7 evidence for the static bundle host. The rotation canary reads the bundles a page
document names off ``static.cdninstagram.com`` through a cookieless transport pinned to that
host, and until this probe runs that host rests on two browser captures of 2026-09-23 rather
than on this client. It answers three things: whether the home document this client receives
names its bundles the way the captured one did, whether a plain HTTP client with no cookie gets
a bundle back, and whether the id module shape ``<Operation>_instagramRelayOperation`` appears
in a fetched bundle.

The document goes through the account's paced transport, the two bundles through the canary's
own cookieless one, 2850 ms apart as every probe paces. It drives the library's own
``bundle_urls``, ``build_bundle_request`` and ``compiled_operations``. It records sizes, counts,
status codes, header presence and the names of registry operations found, which are the site's
own module names. No document text, no bundle text, no id of the account and no token is
written.

Run it from `engine/` with:

   uv run python probes/doctor_bundle_host.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from _probe_support import SESSION_PATH, load_env, report_run

from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import HttpxTransport, cookies_for
from dumpstagram._private.web.bootstrap import (
   DEFAULT_USER_AGENT,
   INSTAGRAM_HOST,
   build_document_request,
)
from dumpstagram._private.web.bundles import (
   STATIC_BUNDLE_HOST,
   build_bundle_request,
   bundle_urls,
   compiled_operations,
)
from dumpstagram._private.web.classify import classify_checkpoint_only
from dumpstagram._private.web.documents.catalog import (
   COMPANION_QUERIES,
   READ_QUERIES,
   WRITE_QUERIES,
)
from dumpstagram._private.web.preload import HOME_DOCUMENT_URL
from dumpstagram.errors import DumpstagramError
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE")
PROBE_SPACING_SECONDS = 2.85
BUNDLES_FETCHED = 2
EVERY_STORED_QUERY = (*READ_QUERIES, *COMPANION_QUERIES, *WRITE_QUERIES)
STORED = {query.friendly_name: query.doc_id for query in EVERY_STORED_QUERY}


def describe_bundle(url: str, status: int, headers: dict[str, str], body: str) -> dict[str, object]:
   found = compiled_operations(body)
   registry_found = sorted(name for name in found.doc_ids if name in STORED)
   matching = sorted(name for name in registry_found if found.doc_ids[name] == {STORED[name]})

   return {
      "path_segments": len(urlsplit(url).path.split("/")),
      "status": status,
      "content_type": headers.get("content-type"),
      "content_encoding_on_the_wire": headers.get("content-encoding"),
      "content_length_header": headers.get("content-length"),
      "set_cookie_present": "set-cookie" in headers,
      "access_control_allow_origin": headers.get("access-control-allow-origin"),
      "decoded_chars": len(body),
      "relay_operation_id_modules": len(found.doc_ids),
      "graphql_artifacts": len(found.artifacts),
      "registry_operations_found": registry_found,
      "registry_operations_matching_stored_id": matching,
   }


async def run() -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}

   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT") or DEFAULT_USER_AGENT

   report: dict[str, object] = {
      "session_path": str(session_path),
      "credentials_read_from_env": False,
      "requests_planned": 1 + BUNDLES_FETCHED,
      "static_bundle_host": STATIC_BUNDLE_HOST,
   }

   if not session_path.exists():
      report["failed_with"] = "no session file, run probes/adopt_and_save.py first"
      report["requests_spent"] = 0

      report_run("doctor-bundle-host-failed", report)

      return 2

   session = Session.load(session_path)
   account = HttpxTransport(
      cookies=cookies_for(session), proxy=session.proxy, allowed_host=INSTAGRAM_HOST
   )
   bundles = HttpxTransport(proxy=session.proxy, allowed_host=STATIC_BUNDLE_HOST, cookieless=True)
   spent = 0
   started_at = time.monotonic()

   try:
      async with PacedSender(account, Pacer()) as sender:
         response = await sender.send(build_document_request(HOME_DOCUMENT_URL, user_agent))
         spent += 1
         classify_checkpoint_only(response)

         html = response.text
         named = bundle_urls(html)

         report["document"] = {
            "status": response.status_code,
            "chars": len(html),
            "bundles_named": len(named),
            "bundles_named_plainly": sum(1 for url in named if url in html),
         }

         fetched = []

         for url in named[:BUNDLES_FETCHED]:
            await asyncio.sleep(PROBE_SPACING_SECONDS)

            answer = await bundles.send(build_bundle_request(url, user_agent))
            spent += 1
            fetched.append(
               describe_bundle(url, answer.status_code, dict(answer.headers), answer.text)
            )

         report["bundles"] = fetched
   except DumpstagramError as failure:
      report["failed_with"] = type(failure).__name__
      report["failure_text"] = str(failure)[:200]
      report["requests_spent"] = spent
      report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)

      report_run("doctor-bundle-host-failed", report)

      return 3
   finally:
      await bundles.aclose()

   report["requests_spent"] = spent
   report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)

   report_run("doctor-bundle-host", report)

   return 0


if __name__ == "__main__":
   sys.exit(asyncio.run(run()))
