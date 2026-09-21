"""Read only. One live request, or two if the stored tokens are stale and re-bootstrap fires.

Answers what a timeline feed node actually contains, which the model cannot be written
without. The `reverse-engineer` run on 2026-09-21 established the call and the connection
shape, and it established that each edge node is a nine slot union where exactly one slot is
non-null. What it did not establish is the type of every field inside `node.media`, which is
roughly a hundred keys wide, nor which of the union slots occur often enough to model.

It records the key union of the connection, the edge and the node, the count of each union
slot that came back non-null, and the key union one level into every object-valued field of
every `media` node.

No value is written to the log except a `__typename`, a `product_type`, a `media_type`, a
boolean, and the first four characters of an id. Captions, usernames, full names and every
URL are recorded as a length or a type, never as text, because a caption is the poster's
content and a feed is other people's content by definition.

Run it from `engine/` with:

   uv run python probes/feed_node_shape.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

from _probe_support import SESSION_PATH, load_env, report_run

from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._private.transport import HttpxTransport, cookies_for
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.requests import build_feed_page_request
from dumpstagram.errors import DumpstagramError
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE")

CONNECTION_PATH = ("data", "xdt_api__v1__feed__timeline__connection")

QUOTABLE_KEYS = ("__typename", "media_type", "product_type", "inventory_source", "audience")
"""Keys whose values are enum-like rather than someone's content."""

ID_PREFIX_CHARS = 4


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


def _merge_key_report(report: dict[str, Any], key: str, value: Any) -> None:
   entry = report.setdefault(
      key,
      {"present_on": 0, "null_on": 0, "types": set(), "nested_keys": set(), "values": set()},
   )

   entry["present_on"] += 1
   entry["types"].add(_shape_of(value))

   if value is None:
      entry["null_on"] += 1

      return

   if isinstance(value, dict):
      entry["nested_keys"].update(value.keys())

   if isinstance(value, list):
      lengths = entry.setdefault("list_lengths", set())
      lengths.add(len(value))

      for element in value:
         if isinstance(element, dict):
            entry["nested_keys"].update(element.keys())

   if isinstance(value, str):
      lengths = entry.setdefault("str_lengths", set())
      lengths.add(len(value))

      if key in QUOTABLE_KEYS:
         entry["values"].add(value)

   is_quotable_number = key in QUOTABLE_KEYS and isinstance(value, int)

   if is_quotable_number and not isinstance(value, bool):
      entry["values"].add(str(value))


def _finalize(report: dict[str, Any]) -> dict[str, Any]:
   finalized: dict[str, Any] = {}

   for key, entry in sorted(report.items()):
      rendered: dict[str, Any] = {
         "present_on": entry["present_on"],
         "null_on": entry["null_on"],
         "types": sorted(entry["types"]),
      }

      if entry["nested_keys"]:
         rendered["nested_keys"] = sorted(entry["nested_keys"])

      if entry["values"]:
         rendered["distinct_values"] = sorted(entry["values"])

      for size_key in ("str_lengths", "list_lengths"):
         sizes = entry.get(size_key)

         if sizes:
            rendered[size_key] = [min(sizes), max(sizes)]

      finalized[key] = rendered

   return finalized


def _union_census(nodes: list[dict[str, Any]]) -> dict[str, Any]:
   """How often each union slot came back non-null, and how many slots filled per node."""

   slots: dict[str, int] = {}
   filled_per_node: list[int] = []

   for node in nodes:
      filled = 0

      for key, value in node.items():
         if key == "__typename":
            continue

         if value is not None:
            slots[key] = slots.get(key, 0) + 1
            filled += 1

      filled_per_node.append(filled)

   return {
      "non_null_slot_counts": dict(sorted(slots.items())),
      "slots_filled_per_node": sorted(set(filled_per_node)),
      "typenames": sorted({node.get("__typename") for node in nodes if node.get("__typename")}),
   }


def describe_shape(parsed: object) -> dict[str, Any]:
   if not isinstance(parsed, dict):
      return {"payload_is_an_object": False}

   current: Any = parsed

   for key in CONNECTION_PATH:
      current = current.get(key) if isinstance(current, dict) else None

   if not isinstance(current, dict):
      return {
         "payload_is_an_object": True,
         "top_level_keys": sorted(parsed.keys()),
         "canonical_path_present": False,
      }

   connection = current
   edges = [edge for edge in (connection.get("edges") or []) if isinstance(edge, dict)]
   nodes = [edge["node"] for edge in edges if isinstance(edge.get("node"), dict)]
   media = [node["media"] for node in nodes if isinstance(node.get("media"), dict)]

   edge_report: dict[str, Any] = {}
   media_report: dict[str, Any] = {}

   for edge in edges:
      for key, value in edge.items():
         _merge_key_report(edge_report, key, value)

   for item in media:
      for key, value in item.items():
         _merge_key_report(media_report, key, value)

   page_info = connection.get("page_info")
   end_cursor = page_info.get("end_cursor") if isinstance(page_info, dict) else None
   owners = [item.get("user") for item in media if isinstance(item.get("user"), dict)]

   owner_report: dict[str, Any] = {}

   for owner in owners:
      for key, value in owner.items():
         _merge_key_report(owner_report, key, value)

   return {
      "payload_is_an_object": True,
      "top_level_keys": sorted(parsed.keys()),
      "canonical_path_present": True,
      "connection_keys": sorted(connection.keys()),
      "page_info_keys": sorted(page_info.keys()) if isinstance(page_info, dict) else None,
      "has_next_page": page_info.get("has_next_page") if isinstance(page_info, dict) else None,
      "end_cursor_length": len(end_cursor) if isinstance(end_cursor, str) else None,
      "edge_count": len(edges),
      "media_node_count": len(media),
      "edge_keys": _finalize(edge_report),
      "union": _union_census(nodes),
      "media_keys": _finalize(media_report),
      "owner_keys": _finalize(owner_report),
   }


async def run() -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}

   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT") or DEFAULT_USER_AGENT

   report: dict[str, object] = {
      "session_path": str(session_path),
      "credentials_read_from_env": False,
   }

   if not session_path.exists():
      report["failed_with"] = "no session file, run probes/adopt_and_save.py first"

      report_run("feed-node-shape-failed", report)

      return 2

   try:
      session = Session.load(session_path)
   except DumpstagramError as failure:
      report["failed_with"] = type(failure).__name__

      report_run("feed-node-shape-failed", report)

      return 2

   token_from_the_file = session.fb_dtsg
   transport = HttpxTransport(cookies=cookies_for(session), proxy=session.proxy)
   started_at = time.monotonic()

   try:
      async with PacedSender(transport, Pacer()) as sender:

         async def attempt() -> object:
            if not session.fb_dtsg:
               await bootstrap(sender, session, user_agent=user_agent)

            request = build_feed_page_request(session, user_agent=user_agent)

            return classify(await sender.send(request))

         parsed = await with_token_recovery(attempt, sender=sender, session=session)
   except DumpstagramError as failure:
      report["failed_with"] = type(failure).__name__
      report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)

      report_run("feed-node-shape-failed", report)

      return 3

   report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
   report["re_bootstrapped"] = session.fb_dtsg != token_from_the_file
   report["requests_spent"] = 2 if session.fb_dtsg != token_from_the_file else 1
   report["shape"] = describe_shape(parsed)

   report_run("feed-node-shape", report)

   return 0


if __name__ == "__main__":
   sys.exit(asyncio.run(run()))
