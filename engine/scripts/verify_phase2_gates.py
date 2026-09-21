"""Break the source, watch each Phase 2 model and capability gate go red, restore.

Same harness as ``verify_step8_gates.py`` and the same rule behind it: a gate that has never
been seen to fail is a gate nobody has tested. One mutation per gate, only the gate that should
catch it is run, and every file is restored from an in-memory copy in a ``finally`` so an
interrupted run cannot leave a mutation behind.

Run from ``engine/`` with ``uv run python scripts/verify_phase2_gates.py``. Writes its result
to ``engine/logs/``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
LOG_DIR = ENGINE / "logs"

PARSE = "dumpstagram/_private/web/parse.py"
DIRECT = "dumpstagram/_core/direct.py"
TOKENS = "dumpstagram/_core/tokens.py"
AIO = "dumpstagram/aio.py"
CLIENT = "dumpstagram/client.py"

REQUIRED_RAISES = """   if not isinstance(node, dict) or key not in node:
      raise SchemaChanged(f"{path}.{key} is missing from the payload", path=f"{path}.{key}")

   return node[key]"""

REQUIRED_DEFAULTS = """   if not isinstance(node, dict) or key not in node:
      return ""

   return node[key]"""

CURSOR_REPORTED_AS_SENT = """
   end_cursor = _optional_string(page_info, "end_cursor", page_info_path)

   return Page("""

CURSOR_CONTRADICTION_RULED_ON = """
   end_cursor = _optional_string(page_info, "end_cursor", page_info_path)

   if has_next_page and end_cursor is None:
      raise SchemaChanged(page_info_path, path=page_info_path)

   return Page("""

UNREACHABLE_PATH_RAISES = """      if not isinstance(current, dict):
         raise SchemaChanged(
            f"{reached} is not reachable, its parent is not an object", path=reached
         )"""

UNREACHABLE_PATH_INVENTS_AN_EMPTY_PAGE = """      if not isinstance(current, dict):
         return {"edges": [], "page_info": {"has_next_page": False, "end_cursor": None}}"""

MESSAGES_IN_UPSTREAM_ORDER = """   messages = tuple(
      parse_message(
         _required(edge, "node", f"{connection_path}.edges[{index}]"),
         f"{connection_path}.edges[{index}].node",
      )
      for index, edge in enumerate(edges)
   )"""

MESSAGES_SORTED = """   messages = tuple(
      sorted(
         (
            parse_message(
               _required(edge, "node", f"{connection_path}.edges[{index}]"),
               f"{connection_path}.edges[{index}].node",
            )
            for index, edge in enumerate(edges)
         ),
         key=lambda message: message.sent_at,
      )
   )"""

MESSAGE_CONSTRUCTION = """   return Message(
      id=_required_string(node, "id", path),"""

MESSAGE_STRICT_ON_UNKNOWN_KEYS = """   known = {
      "__typename",
      "bot_response_id",
      "content",
      "content_type",
      "expiration_timestamp_ms",
      "id",
      "igd_is_forwarded",
      "igd_wearables_attribution_text",
      "igd_wearables_attribution_type",
      "is_ai_generated",
      "is_pinned",
      "is_reported",
      "is_tombstone_revealable",
      "mentions",
      "message_id",
      "msg_reactions",
      "offline_threading_id",
      "reactions",
      "replied_to_message",
      "replied_to_message_id",
      "sender",
      "sender_fbid",
      "slide_edit_history",
      "text_body",
      "thread_fbid",
      "timestamp_ms",
      "tombstone_reason",
      "view_expiration_timestamp_ms",
   }

   for key in node:
      if key not in known:
         raise SchemaChanged(f"{path}.{key} is not a field this mapper knows", path=f"{path}.{key}")

   return Message(
      id=_required_string(node, "id", path),"""

CAPABILITY_PARSES = "      return parse_thread_message_page(classify(response))"

CAPABILITY_RETURNS_THE_PAYLOAD = "      return classify(response)  # type: ignore[no-any-return]"

TOKEN_RECOVERY_BODY = """   token_before_the_attempt = session.fb_dtsg

   try:
      return await run_with_retries(attempt, pacer=sender.pacer, deadline=deadline)"""

TOKEN_RECOVERY_GIVES_UP = """   token_before_the_attempt = session.fb_dtsg

   if token_before_the_attempt is None:
      pass

   try:
      return await run_with_retries(attempt, pacer=sender.pacer, deadline=deadline)
   except RuntimeError:
      raise
   else:
      pass

   try:
      return await run_with_retries(attempt, pacer=sender.pacer, deadline=deadline)"""

CONDITIONAL_BOOTSTRAP = """      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)"""

STALE_TOKEN_GATE = (
   "tests/test_direct.py::test_a_stale_token_is_re_bootstrapped_once_for_the_capability_too"
)

CLOSED_GUARD = """      if self._closed:
         raise RuntimeError("this client is closed, so its connection pool is gone")"""

MUTATIONS = [
   {
      "gate": "tests/test_parse.py::test_the_identifier_comes_from_id_and_not_from_message_id",
      "defect": "the mapper reads the duplicate identifier instead of the one it documents",
      "file": PARSE,
      "find": '      id=_required_string(node, "id", path),',
      "replace": '      id=_required_string(node, "message_id", path),',
   },
   {
      "gate": "tests/test_parse.py::test_reactions_come_from_reactions_and_not_from_msg_reactions",
      "defect": "reactions read from the member of the pair that carries no emoji",
      "file": PARSE,
      "find": '   raw = _required(node, "reactions", path)',
      "replace": '   raw = _required(node, "msg_reactions", path)',
   },
   {
      "gate": "tests/test_parse.py::test_a_missing_required_key_raises_rather_than_defaulting",
      "defect": "a renamed upstream field becomes an empty value instead of an error",
      "file": PARSE,
      "find": REQUIRED_RAISES,
      "replace": REQUIRED_DEFAULTS,
   },
   {
      "gate": "tests/test_parse.py::test_the_timestamp_becomes_aware_utc_at_the_right_instant",
      "defect": "milliseconds read as seconds, which dates every message to 1970",
      "file": PARSE,
      "find": "   return datetime.fromtimestamp(milliseconds / MILLISECONDS_PER_SECOND, tz=UTC)",
      "replace": "   return datetime.fromtimestamp(milliseconds, tz=UTC)",
   },
   {
      "gate": "tests/test_parse.py::test_a_null_text_body_stays_none_rather_than_becoming_empty",
      "defect": "null and empty collapsed into one state",
      "file": PARSE,
      "find": "   if value is None:\n      return None",
      "replace": '   if value is None:\n      return ""',
   },
   {
      "gate": (
         "tests/test_parse.py::test_another_page_with_no_cursor_to_reach_it_is_reported_as_sent"
      ),
      "defect": "the mapper rules on a shape nobody has observed instead of passing it on",
      "file": PARSE,
      "find": CURSOR_REPORTED_AS_SENT,
      "replace": CURSOR_CONTRADICTION_RULED_ON,
   },
   {
      "gate": (
         "tests/test_parse.py::test_an_unresolved_thread_stops_the_walk_where_it_stopped_resolving"
      ),
      "defect": "an unreachable path is given an invented meaning instead of being reported",
      "file": PARSE,
      "find": UNREACHABLE_PATH_RAISES,
      "replace": UNREACHABLE_PATH_INVENTS_AN_EMPTY_PAGE,
   },
   {
      "gate": "tests/test_parse.py::test_edges_keep_the_order_the_upstream_sent_them_in",
      "defect": "the mapper reorders the page, hiding whether upstream order ever changes",
      "file": PARSE,
      "find": MESSAGES_IN_UPSTREAM_ORDER,
      "replace": MESSAGES_SORTED,
   },
   {
      "gate": "tests/test_parse.py::test_an_unknown_upstream_key_is_ignored",
      "defect": "a new upstream field breaks every page instead of being ignored",
      "file": PARSE,
      "find": MESSAGE_CONSTRUCTION,
      "replace": MESSAGE_STRICT_ON_UNKNOWN_KEYS,
   },
   {
      "gate": "tests/test_direct.py::test_the_capability_returns_typed_models_and_not_a_payload",
      "defect": "a raw upstream dict reaches the public boundary",
      "file": DIRECT,
      "find": CAPABILITY_PARSES,
      "replace": CAPABILITY_RETURNS_THE_PAYLOAD,
   },
   {
      "gate": "tests/test_direct.py::test_the_cursor_reaches_the_request_body",
      "defect": "the cursor is accepted and dropped, so pagination reads page one forever",
      "file": DIRECT,
      "find": "         after=after,",
      "replace": "         after=None,",
   },
   {
      "gate": "tests/test_direct.py::test_the_newer_than_marker_reaches_the_request_body",
      "defect": "the top-up marker is dropped, so every poll is a full re-read",
      "file": DIRECT,
      "find": "         newer_than_message_id=newer_than_message_id,",
      "replace": "         newer_than_message_id=None,",
   },
   {
      "gate": "tests/test_direct.py::test_a_session_without_a_token_bootstraps_first",
      "defect": "the capability sends an empty token and gets the HTML shell",
      "file": DIRECT,
      "find": CONDITIONAL_BOOTSTRAP,
      "replace": "      pass",
   },
   {
      "gate": STALE_TOKEN_GATE,
      "defect": "token recovery wired to the internal read and not to the capability",
      "file": TOKENS,
      "find": TOKEN_RECOVERY_BODY,
      "replace": TOKEN_RECOVERY_GIVES_UP,
   },
   {
      "gate": "tests/test_direct.py::test_the_async_facade_forwards_every_argument",
      "defect": "the async surface accepts a cursor and never passes it on",
      "file": AIO,
      "find": "         after=after,",
      "replace": "         after=None,",
   },
   {
      "gate": "tests/test_direct.py::test_the_sync_facade_forwards_every_argument",
      "defect": "the two surfaces drift, and only the sync one loses the cursor",
      "file": CLIENT,
      "find": "            after=after,",
      "replace": "            after=None,",
   },
   {
      "gate": "tests/test_direct.py::test_a_closed_client_refuses_rather_than_sending",
      "defect": "a read is issued through a connection pool that is already torn down",
      "file": AIO,
      "find": CLOSED_GUARD,
      "replace": "      if self._closed:\n         pass",
   },
]


def run_gate(gate: str) -> subprocess.CompletedProcess[str]:
   return subprocess.run(
      [sys.executable, "-m", "pytest", gate, "-q", "--no-header", "-p", "no:cacheprovider"],
      cwd=ENGINE,
      capture_output=True,
      text=True,
   )


def apply_mutation(mutation: dict[str, str]) -> str:
   path = ENGINE / mutation["file"]
   original = path.read_text(encoding="utf-8")

   if mutation["find"] not in original:
      raise SystemExit(f"mutation anchor not found in {mutation['file']} for {mutation['gate']}")

   path.write_text(original.replace(mutation["find"], mutation["replace"], 1), encoding="utf-8")

   return original


def main() -> int:
   results = []

   for mutation in MUTATIONS:
      path = ENGINE / mutation["file"]
      original = apply_mutation(mutation)

      try:
         mutated = run_gate(mutation["gate"])
      finally:
         path.write_text(original, encoding="utf-8")

      restored = run_gate(mutation["gate"])

      results.append(
         {
            "gate": mutation["gate"],
            "defect": mutation["defect"],
            "mutated_file": mutation["file"],
            "red_under_mutation": mutated.returncode != 0,
            "green_after_restore": restored.returncode == 0,
            "mutated_tail": mutated.stdout.strip().splitlines()[-1:],
         }
      )

   every_gate_fired = all(
      entry["red_under_mutation"] and entry["green_after_restore"] for entry in results
   )

   LOG_DIR.mkdir(parents=True, exist_ok=True)
   stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
   log_path = LOG_DIR / f"mutation-phase2-{stamp}.json"
   log_path.write_text(
      json.dumps({"every_gate_fired": every_gate_fired, "gates": results}, indent=2) + "\n",
      encoding="utf-8",
   )

   for entry in results:
      status = (
         "red then green"
         if entry["red_under_mutation"] and entry["green_after_restore"]
         else "DID NOT FIRE"
      )
      print(f"{status}: {entry['gate']}")

   print(f"log written to {log_path}")

   return 0 if every_gate_fired else 1


if __name__ == "__main__":
   raise SystemExit(main())
