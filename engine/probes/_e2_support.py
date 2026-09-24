"""Shared plumbing for the E2 replay probes, the ``e2_*.py`` files beside this one.

Not a library module and not importable from the package. Every E2 probe replays operations
whose contracts are hypothesis findings in the local knowledge base, so the ``doc_id``, the
friendly name, the path and the root field of each are read at run time from
``skills/reverse-engineer/knowledge/endpoints/<finding id>.md`` rather than written here. That
keeps every ``doc_id`` literal out of ``engine/``, and a finding re-recorded after a rotation is
picked up without touching a probe.

A replay spends one paced request at a time, at least 2850 ms apart, through the account's own
transport and the library's own request builder, and refuses to send past the count the probe
declared. It stops the whole probe at the first checkpoint, throttle, authentication failure or
HTML shell, and never retries one. Only key names, types, counts, lengths and a few enum values
reach the log. No caption, username, full name, message text, URL or id is written, except the
first four characters of an id where a probe needs to show two reads returned the same thing.
"""

from __future__ import annotations

import asyncio
import json
import random
import string
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from _probe_support import ENGINE_ROOT, ENV_PATH, SESSION_PATH, load_env, report_run

from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import HttpxTransport, Request, cookies_for
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, ORIGIN, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.documents.common import (
   API_GRAPHQL_URL,
   GRAPHQL_QUERY_URL,
   PersistedQuery,
)
from dumpstagram._private.web.requests.common import build_graphql_request, jazoest_for
from dumpstagram.errors import (
   AuthenticationFailed,
   CheckpointRequired,
   DumpstagramError,
   RateLimited,
   UpstreamRejected,
)
from dumpstagram.session import Session

KNOWLEDGE_ENDPOINTS = ENGINE_ROOT.parent / "skills" / "reverse-engineer" / "knowledge" / "endpoints"
NON_CREDENTIAL_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE", "IG_THREAD_FBID")
PROBE_SPACING_SECONDS = 2.85
SHAPE_DEPTH = 5

STOPPING_FAILURES = (CheckpointRequired, RateLimited, AuthenticationFailed)
STOPPING_CODES = ("html_app_shell",)

QUOTABLE_KEYS = (
   "__typename",
   "media_type",
   "product_type",
   "reel_type",
   "status",
   "big_list",
   "has_more",
   "has_next_page",
   "has_previous_page",
   "more_available",
   "is_private",
   "is_verified",
   "folder",
   "tab",
)


class ProbeStopped(Exception):
   """The upstream said stop, or the probe reached the count it declared."""


class ProbeCannotStart(Exception):
   """Something the probe needs before its first request is missing."""


@dataclass(frozen=True)
class Hypothesis:
   """The parts of one knowledge base finding a replay needs, read off its front matter."""

   finding_id: str
   friendly_name: str
   doc_id: str
   url: str
   status: str
   root_field: str | None
   template: dict[str, Any] | None

   def query(self, url: str | None = None) -> PersistedQuery:
      chosen_url = url or self.url
      on_the_query_path = chosen_url == GRAPHQL_QUERY_URL

      return PersistedQuery(
         doc_id=self.doc_id,
         friendly_name=self.friendly_name,
         finding_id=self.finding_id,
         url=chosen_url,
         root_field=self.root_field if on_the_query_path else None,
      )


def read_hypothesis(finding_id: str) -> Hypothesis:
   path = KNOWLEDGE_ENDPOINTS / f"{finding_id}.md"

   if not path.exists():
      raise ProbeCannotStart(f"no finding {finding_id} in the local knowledge base")

   text = path.read_text(encoding="utf-8")
   _, front, body = text.split("---\n", 2)
   meta: dict[str, str] = {}

   for line in front.splitlines():
      key, separator, value = line.partition(":")

      if separator:
         meta[key.strip()] = value.strip().strip('"')

   template = None
   marker = "## Replay template"

   if marker in body:
      fenced = body.split(marker, 1)[1].split("```json", 1)[1].split("```", 1)[0]
      template = json.loads(fenced)

   return Hypothesis(
      finding_id=finding_id,
      friendly_name=meta.get("friendly_name", ""),
      doc_id=meta.get("doc_id", ""),
      url=meta.get("url", ""),
      status=meta.get("status", ""),
      root_field=meta.get("root_field") or None,
      template=template,
   )


def other_path(url: str) -> str:
   return API_GRAPHQL_URL if url == GRAPHQL_QUERY_URL else GRAPHQL_QUERY_URL


def web_session_id() -> str:
   """Three groups of six base36 characters, the shape the browser's header carried."""

   alphabet = string.ascii_lowercase + string.digits

   return ":".join("".join(random.choice(alphabet) for _ in range(6)) for _ in range(3))


def _shape_of(value: Any) -> str:
   if value is None:
      return "null"

   if isinstance(value, bool):
      return "bool"

   if isinstance(value, int):
      return "int"

   if isinstance(value, float):
      return "float"

   if isinstance(value, str):
      return "str"

   if isinstance(value, list):
      return "list"

   if isinstance(value, dict):
      return "object"

   return type(value).__name__


def key_union(value: Any, depth: int = SHAPE_DEPTH) -> dict[str, Any]:
   """The keys and types under ``value``, merged across list elements, with no content."""

   summary: dict[str, Any] = {"types": {_shape_of(value)}}

   if depth <= 0:
      return summary

   if isinstance(value, list):
      summary["lengths"] = {len(value)}
      elements = [key_union(element, depth - 1) for element in value]
      summary["items"] = _merge_all(elements)

   if isinstance(value, dict):
      summary["keys"] = {}

      for key, inner in value.items():
         entry = key_union(inner, depth - 1)
         is_quotable = key in QUOTABLE_KEYS and isinstance(inner, (str, bool, int))

         if is_quotable:
            entry["values"] = {str(inner)}

         summary["keys"][key] = entry

   return summary


def _merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
   merged: dict[str, Any] = {"types": left["types"] | right["types"]}

   for collection in ("lengths", "values"):
      if collection in left or collection in right:
         merged[collection] = left.get(collection, set()) | right.get(collection, set())

   if "items" in left or "items" in right:
      merged["items"] = _merge_all([part["items"] for part in (left, right) if "items" in part])

   if "keys" in left or "keys" in right:
      keys: dict[str, Any] = {}

      for part in (left, right):
         for key, entry in part.get("keys", {}).items():
            keys[key] = _merge(keys[key], entry) if key in keys else entry

      merged["keys"] = keys

   return merged


def _merge_all(parts: list[dict[str, Any]]) -> dict[str, Any]:
   if not parts:
      return {"types": set()}

   merged = parts[0]

   for part in parts[1:]:
      merged = _merge(merged, part)

   return merged


def render_shape(summary: dict[str, Any]) -> Any:
   rendered: dict[str, Any] = {"types": sorted(summary["types"])}

   if summary.get("lengths"):
      rendered["lengths"] = [min(summary["lengths"]), max(summary["lengths"])]

   if summary.get("values"):
      rendered["values"] = sorted(summary["values"])[:12]

   if summary.get("items") and summary["items"].get("types"):
      rendered["items"] = render_shape(summary["items"])

   if "keys" in summary:
      rendered["keys"] = {
         key: render_shape(entry) for key, entry in sorted(summary["keys"].items())
      }

   return rendered


def id_prefix(value: Any) -> str | None:
   return str(value)[:4] if value is not None else None


def dig(value: Any, *path: str | int) -> Any:
   current = value

   for step in path:
      if isinstance(step, int):
         is_indexable = isinstance(current, list) and -len(current) <= step < len(current)
         current = current[step] if is_indexable else None
      else:
         current = current.get(step) if isinstance(current, dict) else None

   return current


def page_info_of(connection: Any) -> dict[str, Any]:
   info = dig(connection, "page_info") or {}
   cursor = info.get("end_cursor") if isinstance(info, dict) else None

   return {
      "has_next_page": info.get("has_next_page") if isinstance(info, dict) else None,
      "end_cursor_length": len(cursor) if isinstance(cursor, str) else None,
      "edges": len(dig(connection, "edges") or []),
   }


class E2Replay:
   """One probe's session, transport, request count and report."""

   def __init__(self, kind: str, planned: int, conditional: int = 0) -> None:
      self.kind = kind
      self.planned = planned
      self.conditional = conditional
      self.spent = 0
      self.started_at = time.monotonic()
      self.report: dict[str, Any] = {
         "requests_planned": planned,
         "requests_conditional": conditional,
         "credentials_read_from_env": False,
         "replays": [],
      }
      self._last_departure: float | None = None

   async def __aenter__(self) -> E2Replay:
      if not ENV_PATH.exists():
         raise ProbeCannotStart("no .env at the repository root")

      environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}
      session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)

      if not session_path.exists():
         raise ProbeCannotStart("no session file, run probes/adopt_and_save.py first")

      self.environment = environment
      self.user_agent = environment.get("IG_USER_AGENT") or DEFAULT_USER_AGENT
      self.session = Session.load(session_path)
      self.device_id = str(uuid.uuid4())
      self.web_session_id = web_session_id()
      self._transport = HttpxTransport(cookies=cookies_for(self.session), proxy=self.session.proxy)
      self._sender = PacedSender(self._transport, Pacer())
      await self._sender.__aenter__()

      return self

   async def __aexit__(self, *exc_info: object) -> None:
      await self._sender.__aexit__(*exc_info)

   @property
   def viewer_id(self) -> str:
      return self.session.ds_user_id

   async def _space(self) -> None:
      if self._last_departure is not None:
         elapsed = time.monotonic() - self._last_departure
         remaining = PROBE_SPACING_SECONDS - elapsed

         if remaining > 0:
            await asyncio.sleep(remaining)

      budget = self.planned + self.conditional

      if self.spent >= budget:
         raise ProbeStopped(f"the probe declared {budget} requests and has spent them")

      self.spent += 1
      self._last_departure = time.monotonic()

   async def bootstrap(self) -> None:
      """The inbox document every probe reads its tokens from, one request."""

      await self._space()
      await bootstrap(self._sender, self.session, user_agent=self.user_agent)
      self.report["bootstrap"] = {
         "fb_dtsg_present": bool(self.session.fb_dtsg),
         "bloks_version_present": bool(self.session.bloks_version_id),
      }

   async def _send(self, label: str, request: Request) -> Any:
      await self._space()
      started = time.monotonic()
      entry: dict[str, Any] = {"label": label}

      try:
         response = await self._sender.send(request)
         entry["status"] = response.status_code
         entry["bytes"] = len(response.content)
         parsed = classify(response)
      except STOPPING_FAILURES as failure:
         entry["failed_with"] = type(failure).__name__
         self.report["replays"].append(entry)

         raise ProbeStopped(f"{label}: {type(failure).__name__}") from failure
      except UpstreamRejected as failure:
         entry["failed_with"] = "UpstreamRejected"
         entry["code"] = failure.code
         self.report["replays"].append(entry)

         if failure.code in STOPPING_CODES:
            raise ProbeStopped(f"{label}: {failure.code}") from failure

         return None
      except DumpstagramError as failure:
         entry["failed_with"] = type(failure).__name__
         self.report["replays"].append(entry)

         return None
      finally:
         entry["elapsed_ms"] = int((time.monotonic() - started) * 1000)

      entry["top_keys"] = sorted(parsed.keys()) if isinstance(parsed, dict) else None
      self.report["replays"].append(entry)

      return parsed

   async def engine_read(self, label: str, request: Request) -> dict[str, Any] | None:
      """One read the library already builds, from a verified finding, used for arguments."""

      parsed = await self._send(label, request)
      roots = self._record_roots(parsed)

      return None if roots["all_null"] else parsed

   async def graphql(
      self,
      finding_id: str,
      variables: dict[str, Any],
      *,
      referer: str,
      label: str | None = None,
      try_other_path_on_null: bool = False,
   ) -> dict[str, Any] | None:
      """One replay of a hypothesis query. ``None`` when it failed or answered nothing.

      A null root under HTTP 200 with no envelope is how a query answers on the wrong path, so
      with ``try_other_path_on_null`` a null root is sent once more on the other path, and the
      probe declares that request as conditional.
      """

      hypothesis = read_hypothesis(finding_id)
      name = label or finding_id
      parsed = await self._send(
         name,
         build_graphql_request(
            self.session,
            hypothesis.query(),
            variables,
            referer=referer,
            user_agent=self.user_agent,
         ),
      )
      roots = self._record_roots(parsed)

      if roots["all_null"] and try_other_path_on_null:
         alternate = other_path(hypothesis.url)
         parsed = await self._send(
            f"{name} on the other path",
            build_graphql_request(
               self.session,
               hypothesis.query(alternate),
               variables,
               referer=referer,
               user_agent=self.user_agent,
            ),
         )
         roots = self._record_roots(parsed)
         self.report["replays"][-1]["path"] = alternate.rsplit("/", 2)[-2:]

      return None if roots["all_null"] else parsed

   def _record_roots(self, parsed: Any) -> dict[str, Any]:
      data = parsed.get("data") if isinstance(parsed, dict) else None
      roots = data if isinstance(data, dict) else {}
      null_roots = sorted(key for key, value in roots.items() if value is None)
      summary = {
         "root_fields": sorted(roots.keys()),
         "null_roots": null_roots,
         "all_null": not roots or len(null_roots) == len(roots),
      }

      if self.report["replays"]:
         self.report["replays"][-1].update(
            {key: value for key, value in summary.items() if key != "all_null"}
         )

      return summary

   async def rest(
      self,
      label: str,
      url: str,
      *,
      referer: str,
      params: dict[str, str] | None = None,
      form: dict[str, str] | None = None,
   ) -> dict[str, Any] | None:
      """One replay of a hypothesis REST route, GET without a form and POST with one."""

      is_post = form is not None
      headers = {
         "accept": "*/*",
         "accept-language": "en-US,en;q=0.9",
         "referer": referer,
         "sec-fetch-dest": "empty",
         "sec-fetch-mode": "cors",
         "sec-fetch-site": "same-origin",
         "user-agent": self.user_agent,
         "x-asbd-id": "359341",
         "x-csrftoken": self.session.csrftoken,
         "x-ig-app-id": self.session.app_id or "",
         "x-ig-max-touch-points": "0",
         "x-requested-with": "XMLHttpRequest",
         "x-web-session-id": self.web_session_id,
      }
      content = None

      if is_post:
         revision = self.session.spin.revision if self.session.spin else None
         fb_dtsg = self.session.fb_dtsg or ""
         body = {**form, "fb_dtsg": fb_dtsg, "jazoest": jazoest_for(fb_dtsg)}
         content = urlencode(body).encode("ascii")
         headers["content-type"] = "application/x-www-form-urlencoded"
         headers["origin"] = ORIGIN
         headers["x-instagram-ajax"] = revision or ""

      request = Request(
         method="POST" if is_post else "GET",
         url=url,
         headers=headers,
         params=params or {},
         content=content,
      )
      parsed = await self._send(label, request)

      return parsed if isinstance(parsed, dict) else None

   def record(self, label: str, value: Any) -> None:
      self.report[label] = value

   def shape(self, label: str, value: Any) -> None:
      self.report.setdefault("shapes", {})[label] = render_shape(key_union(value))

   def finish(self, outcome: str) -> int:
      self.report["outcome"] = outcome
      self.report["requests_spent"] = self.spent
      self.report["elapsed_ms"] = int((time.monotonic() - self.started_at) * 1000)
      report_run(self.kind if outcome == "done" else f"{self.kind}-{outcome}", self.report)

      return 0 if outcome == "done" else 3


async def run_probe(kind: str, planned: int, conditional: int, body: Any) -> int:
   """Open the replay, run ``body(replay)``, and write the log whatever happened."""

   replay = E2Replay(kind, planned, conditional)

   try:
      async with replay:
         await body(replay)
   except ProbeCannotStart as failure:
      replay.record("failed_with", str(failure))

      return replay.finish("failed")
   except ProbeStopped as failure:
      replay.record("stopped_because", str(failure))

      return replay.finish("stopped")
   except DumpstagramError as failure:
      replay.record("stopped_because", type(failure).__name__)

      return replay.finish("stopped")

   return replay.finish("done")
