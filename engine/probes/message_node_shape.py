"""Read only. One live request, or two if the stored tokens are stale and re-bootstrap fires.

Answers the two questions Phase 2 cannot pick a model field without:
which of `id` and `message_id` identifies a message, and which of `reactions` and
`msg_reactions` holds them. Both pairs were seen on the same node in the 2026-09-21 capture
and are recorded UNRESOLVED in `docs/knowledge/assumptions-and-open-questions.md`.

It also records the full key union of the message node, the edge, the connection and the
thread, plus the key union one level into every object-valued node field. The 2026-09-21
capture recorded only the first twenty keys of one node in sorted order, which stops at
`replied_to_message_id` and so says nothing about a sender or a timestamp.

No value is written to the log except a `__typename`, a `content_type`, a boolean, and the
first four characters of an id. Everything else is recorded as a type name, a count, or a
length, per the log rules. Message text, names and mentions never leave this process.

Run it from `engine/` with:

   uv run python probes/message_node_shape.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

from _probe_support import (
   SESSION_PATH,
   THREAD_FBID,
   describe_page,
   load_env,
   report_run,
)

from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.smoke import read_one_thread_page
from dumpstagram._private.transport import HttpxTransport, cookies_for
from dumpstagram.errors import DumpstagramError
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_THREAD_FBID", "IG_USER_AGENT", "IG_SESSION_FILE")

QUOTABLE_KEYS = ("__typename", "content_type", "item_type", "status")
"""Keys whose values are enum-like rather than user content, so the value itself is evidence."""

ID_PREFIX_CHARS = 4


def _shape_of(value: Any) -> dict[str, Any]:
   """One value reduced to what may be logged: its type, and a size when it has one."""

   if value is None:
      return {"type": "null"}

   if isinstance(value, bool):
      return {"type": "bool", "value": value}

   if isinstance(value, int):
      return {"type": "int", "digits": len(str(abs(value)))}

   if isinstance(value, float):
      return {"type": "float"}

   if isinstance(value, str):
      return {"type": "str", "length": len(value)}

   if isinstance(value, list):
      return {"type": "list", "length": len(value)}

   if isinstance(value, dict):
      return {"type": "object", "keys": sorted(value.keys())}

   return {"type": type(value).__name__}


def _merge_key_report(report: dict[str, Any], key: str, value: Any) -> None:
   entry = report.setdefault(
      key,
      {"present_on": 0, "null_on": 0, "types": set(), "nested_keys": set(), "values": set()},
   )

   entry["present_on"] += 1

   shape = _shape_of(value)
   entry["types"].add(shape["type"])

   if value is None:
      entry["null_on"] += 1

      return

   if isinstance(value, dict):
      entry["nested_keys"].update(value.keys())

   if isinstance(value, str):
      lengths = entry.setdefault("str_lengths", set())
      lengths.add(len(value))

   if isinstance(value, list):
      lengths = entry.setdefault("list_lengths", set())
      lengths.add(len(value))

      for element in value:
         if isinstance(element, dict):
            entry["nested_keys"].update(element.keys())

   is_quotable = key in QUOTABLE_KEYS and isinstance(value, str)

   if is_quotable:
      entry["values"].add(value)


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


def _id_pair_verdict(nodes: list[dict[str, Any]]) -> dict[str, Any]:
   """Whether `id` and `message_id` are the same identifier under two names."""

   both_present = 0
   equal = 0
   id_prefixes: set[str] = set()
   message_id_prefixes: set[str] = set()

   for node in nodes:
      node_id = node.get("id")
      message_id = node.get("message_id")

      if not isinstance(node_id, str) or not isinstance(message_id, str):
         continue

      both_present += 1

      if node_id == message_id:
         equal += 1

      id_prefixes.add(node_id[:ID_PREFIX_CHARS])
      message_id_prefixes.add(message_id[:ID_PREFIX_CHARS])

   return {
      "nodes_carrying_both": both_present,
      "nodes_where_they_are_equal": equal,
      "id_prefixes": sorted(id_prefixes),
      "message_id_prefixes": sorted(message_id_prefixes),
   }


def _reaction_pair_verdict(nodes: list[dict[str, Any]]) -> dict[str, Any]:
   """Which of `reactions` and `msg_reactions` actually carries anything."""

   verdict: dict[str, Any] = {}

   for key in ("reactions", "msg_reactions"):
      present = 0
      null = 0
      non_empty = 0
      nested: set[str] = set()

      for node in nodes:
         if key not in node:
            continue

         present += 1
         value = node[key]

         if value is None:
            null += 1

            continue

         if isinstance(value, dict):
            nested.update(value.keys())

            if any(value.values()):
               non_empty += 1

         if isinstance(value, list):
            if value:
               non_empty += 1

            for element in value:
               if isinstance(element, dict):
                  nested.update(element.keys())

      verdict[key] = {
         "present_on": present,
         "null_on": null,
         "non_empty_on": non_empty,
         "nested_keys": sorted(nested),
      }

   return verdict


def describe_shape(parsed: object) -> dict[str, Any]:
   if not isinstance(parsed, dict):
      return {"payload_is_an_object": False}

   data = parsed.get("data")
   thread_field = data.get("fetch__SlideThread") if isinstance(data, dict) else None
   thread = thread_field.get("as_ig_direct_thread") if isinstance(thread_field, dict) else None
   connection = thread.get("slide_messages") if isinstance(thread, dict) else None

   if not isinstance(connection, dict):
      return {"payload_is_an_object": True, "canonical_path_present": False}

   edges = [edge for edge in (connection.get("edges") or []) if isinstance(edge, dict)]
   nodes = [edge["node"] for edge in edges if isinstance(edge.get("node"), dict)]

   edge_report: dict[str, Any] = {}
   node_report: dict[str, Any] = {}

   for edge in edges:
      for key, value in edge.items():
         _merge_key_report(edge_report, key, value)

   for node in nodes:
      for key, value in node.items():
         _merge_key_report(node_report, key, value)

   page_info = connection.get("page_info")

   return {
      "payload_is_an_object": True,
      "canonical_path_present": True,
      "thread_keys": sorted(thread.keys()),
      "connection_keys": sorted(connection.keys()),
      "page_info_keys": sorted(page_info.keys()) if isinstance(page_info, dict) else None,
      "edge_count": len(edges),
      "node_count": len(nodes),
      "edge_keys": _finalize(edge_report),
      "node_keys": _finalize(node_report),
      "id_versus_message_id": _id_pair_verdict(nodes),
      "reactions_versus_msg_reactions": _reaction_pair_verdict(nodes),
   }


async def run() -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}

   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   thread_fbid = environment.get("IG_THREAD_FBID") or THREAD_FBID
   user_agent_override = environment.get("IG_USER_AGENT")

   report: dict[str, object] = {
      "session_path": str(session_path),
      "credentials_read_from_env": False,
      "thread_fbid_length": len(thread_fbid),
   }

   if not session_path.exists():
      report["failed_with"] = "no session file, run probes/adopt_and_save.py first"

      report_run("message-node-shape-failed", report)

      return 2

   try:
      session = Session.load(session_path)
   except DumpstagramError as failure:
      report["failed_with"] = type(failure).__name__

      report_run("message-node-shape-failed", report)

      return 2

   token_from_the_file = session.fb_dtsg
   pacer = Pacer()
   read_arguments = {"user_agent": user_agent_override} if user_agent_override else {}

   transport = HttpxTransport(cookies=cookies_for(session), proxy=session.proxy)
   started_at = time.monotonic()

   try:
      async with PacedSender(transport, pacer) as sender:
         parsed = await read_one_thread_page(sender, session, thread_fbid, **read_arguments)
   except DumpstagramError as failure:
      report["failed_with"] = type(failure).__name__
      report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)

      report_run("message-node-shape-failed", report)

      return 3

   re_bootstrapped = session.fb_dtsg != token_from_the_file

   report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
   report["re_bootstrapped"] = re_bootstrapped
   report["requests_spent"] = 2 if re_bootstrapped else 1
   report["page"] = describe_page(parsed)
   report["shape"] = describe_shape(parsed)

   report_run("message-node-shape", report)

   return 0


if __name__ == "__main__":
   sys.exit(asyncio.run(run()))
