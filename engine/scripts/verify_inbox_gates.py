"""Break the inbox listing's request and mapper, watch each of its gates go red, restore.

Same harness and same rule as ``verify_notes_gates.py``: one mutation per line below, only the
gate that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

The listing is private. Step 20 of the build plan added the request and the mapper for the
Phase 4 listener to poll, and nothing public returns them yet.

Run from ``engine/`` with ``uv run python scripts/verify_inbox_gates.py``. Writes its result to
``engine/logs/``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
LOG_DIR = ENGINE / "logs"


PARSE_DIRECT = "dumpstagram/_private/web/parse/direct.py"
REQUESTS_DIRECT = "dumpstagram/_private/web/requests/direct.py"
GATES = "tests/test_inbox_listing.py"


def gate(name: str) -> str:
   return f"{GATES}::{name}"


MUTATIONS: list[dict[str, object]] = [
   {
      "gate": gate("test_a_row_maps_field_by_field"),
      "defect": "thread_fbid is read from thread_key",
      "edits": [
         (
            PARSE_DIRECT,
            'thread_fbid=_required_string(thread, "thread_fbid", thread_path),',
            'thread_fbid=_required_string(thread, "thread_key", thread_path),',
         )
      ],
   },
   {
      "gate": gate("test_a_row_maps_field_by_field"),
      "defect": "the newest message id is taken from the last listed message",
      "edits": [
         (
            PARSE_DIRECT,
            'node = _required(edges[0], "node", f"{messages_path}.edges[0]")',
            'node = _required(edges[-1], "node", f"{messages_path}.edges[0]")',
         )
      ],
   },
   {
      "gate": gate("test_a_row_maps_field_by_field"),
      "defect": "the pin flag is read from is_muted",
      "edits": [
         (
            PARSE_DIRECT,
            'is_pinned=_required_flag(thread, "is_pin", thread_path),',
            'is_pinned=_required_flag(thread, "is_muted", thread_path),',
         )
      ],
   },
   {
      "gate": gate("test_rows_keep_the_listings_order"),
      "defect": "the rows are sorted by thread id on the way out",
      "edits": [
         (
            PARSE_DIRECT,
            "   return Page(items=threads, has_next_page",
            "   return Page(items=tuple(sorted(threads, key=lambda row: row.thread_fbid)), "
            "has_next_page",
         )
      ],
   },
   {
      "gate": gate("test_a_thread_without_messages_has_no_newest_message_id"),
      "defect": "a thread with no messages is read as if it had one",
      "edits": [
         (
            PARSE_DIRECT,
            "   if not edges:\n      return None\n\n   node = _required(edges[0]",
            "   node = _required(edges[0]",
         )
      ],
   },
   {
      "gate": gate("test_a_row_without_an_activity_marker_is_a_schema_change"),
      "defect": "a missing activity marker defaults to zero",
      "edits": [
         (
            PARSE_DIRECT,
            "   raw = _required(node, key, path)\n   is_a_digit_string",
            '   raw = node.get(key) or "0"\n   is_a_digit_string',
         )
      ],
   },
   {
      "gate": gate("test_the_listing_ends_only_on_the_servers_flag"),
      "defect": "has_next_page is inferred from the cursor",
      "edits": [
         (
            PARSE_DIRECT,
            "\n\n   return Page(items=threads,",
            "\n   has_next_page = end_cursor is not None\n\n   return Page(items=threads,",
         )
      ],
   },
   {
      "gate": gate("test_the_listing_request_is_the_one_an_inbox_load_sends"),
      "defect": "the listing carries the home page as its referer",
      "edits": [
         (
            REQUESTS_DIRECT,
            "      DIRECT_INBOX,\n      variables,\n      referer=BOOTSTRAP_URL,\n",
            '      DIRECT_INBOX,\n      variables,\n      referer=f"{ORIGIN}/",\n',
         )
      ],
   },
   {
      "gate": gate("test_the_listing_request_is_the_one_an_inbox_load_sends"),
      "defect": "the caller's device id is replaced by a fixed one",
      "edits": [
         (
            REQUESTS_DIRECT,
            '      "device_id_for_iris_subscription": device_id,\n',
            '      "device_id_for_iris_subscription": FEED_DEVICE_ID,\n',
         ),
         (
            REQUESTS_DIRECT,
            "from dumpstagram._private.web.requests.common import ",
            "from dumpstagram._private.web.requests.feed import FEED_DEVICE_ID\n"
            "from dumpstagram._private.web.requests.common import ",
         ),
      ],
   },
   {
      "gate": gate("test_the_listing_request_is_the_one_an_inbox_load_sends"),
      "defect": "each row asks for a page of messages instead of five",
      "edits": [
         (
            REQUESTS_DIRECT,
            '"__relay_internal__pv__IGDMaxUnreadMessagesCountrelayprovider": INBOX_ROW_MESSAGES,',
            '"__relay_internal__pv__IGDMaxUnreadMessagesCountrelayprovider": PAGE_SIZE,',
         )
      ],
   },
]


def run_gate(gate: str) -> subprocess.CompletedProcess[str]:
   """Run one gate in a subprocess that cannot read a stale `.pyc`.

   The reason is the one ``verify_cli_gates.py`` records: CPython validates cached bytecode
   against the source's size and its mtime in whole seconds, so a same-length edit applied and
   undone inside one second is invisible to that check.
   """

   environment = dict(os.environ)
   environment["PYTHONDONTWRITEBYTECODE"] = "1"

   for cached in ENGINE.glob("**/__pycache__"):
      shutil.rmtree(cached, ignore_errors=True)

   return subprocess.run(
      [sys.executable, "-B", "-m", "pytest", gate, "-q", "--no-header", "-p", "no:cacheprovider"],
      cwd=ENGINE,
      capture_output=True,
      text=True,
      env=environment,
   )


def apply_edits(edits: list[tuple[str, str, str]], gate: str) -> dict[Path, str]:
   originals: dict[Path, str] = {}

   try:
      for relative, find, replace in edits:
         path = ENGINE / relative
         originals.setdefault(path, path.read_text(encoding="utf-8"))
         current = path.read_text(encoding="utf-8")

         occurrences = current.count(find)

         if occurrences != 1:
            raise SystemExit(
               f"mutation anchor found {occurrences} times in {relative} for {gate}, "
               "expected exactly once"
            )

         path.write_text(current.replace(find, replace, 1), encoding="utf-8")
   except BaseException:
      restore(originals)

      raise

   return originals


def restore(originals: dict[Path, str]) -> None:
   for path, original in originals.items():
      path.write_text(original, encoding="utf-8")


def main() -> int:
   results = []

   for mutation in MUTATIONS:
      gate = str(mutation["gate"])
      edits = mutation["edits"]
      assert isinstance(edits, list)

      originals = apply_edits(edits, gate)

      try:
         mutated = run_gate(gate)
      finally:
         restore(originals)

      restored = run_gate(gate)

      results.append(
         {
            "gate": gate,
            "defect": mutation["defect"],
            "mutated_files": sorted({relative for relative, _, _ in edits}),
            "red_under_mutation": mutated.returncode != 0,
            "green_after_restore": restored.returncode == 0,
            "mutated_tail": mutated.stdout.strip().splitlines()[-1:],
         }
      )

   every_gate_fired = bool(results) and all(
      entry["red_under_mutation"] and entry["green_after_restore"] for entry in results
   )

   LOG_DIR.mkdir(parents=True, exist_ok=True)
   stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
   log_path = LOG_DIR / f"mutation-inbox-listing-{stamp}.json"
   log_path.write_text(
      json.dumps({"every_gate_fired": every_gate_fired, "gates": results}, indent=2) + "\n",
      encoding="utf-8",
   )

   for entry in results:
      fired = entry["red_under_mutation"] and entry["green_after_restore"]
      status = "red then green" if fired else "DID NOT FIRE"
      print(f"{status}: {entry['gate'].split('::')[1]}  ({entry['defect']})")

   print(f"log written to {log_path}")

   return 0 if every_gate_fired else 1


if __name__ == "__main__":
   raise SystemExit(main())
