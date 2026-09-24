"""Break the mapper and the fixtures, watch each oracle gate go red, restore.

Same harness and same rule as ``verify_parity_gates.py``: one mutation per gate, only the gate
that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

Two mutations edit the fixtures rather than the source, because the gates they target guard
the fixtures: the exemption gate exists so the exemption list cannot hide a dropped message,
and the positive control exists so an empty fixture cannot make every other gate vacuous.

Run from ``engine/`` with ``uv run python scripts/verify_oracle_gates.py``. Writes its result
to ``engine/logs/``.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
LOG_DIR = ENGINE / "logs"

PARSE_DIRECT = "dumpstagram/_private/web/parse/direct.py"
PAGES = "tests/fixtures/thread_oracle/pages.json.gz"
INDEPENDENT = "tests/fixtures/thread_oracle/independent_export.json"
ORACLE = "tests/test_thread_oracle.py"

THREAD_PAGE_RETURN = (
   "\n\n   return Page(items=messages, has_next_page=has_next_page, end_cursor=end_cursor)"
)

THREAD_CURSOR_FROM_END = (
   '   end_cursor = _optional_string(page_info, "end_cursor", page_info_path)' + THREAD_PAGE_RETURN
)

THREAD_CURSOR_FROM_START = (
   '   end_cursor = _optional_string(page_info, "start_cursor", page_info_path)'
   + THREAD_PAGE_RETURN
)

THREAD_PAGE_AS_SENT = (
   "   return Page(items=messages, has_next_page=has_next_page, end_cursor=end_cursor)"
)

THREAD_PAGE_REPEATS_ITS_LAST = (
   "   return Page(items=messages + messages[-1:], has_next_page=has_next_page, "
   "end_cursor=end_cursor)"
)

EVERY_EDGE_MAPPED = """      parse_message(
         _required(edge, "node", f"{connection_path}.edges[{index}]"),
         f"{connection_path}.edges[{index}].node",
      )
      for index, edge in enumerate(edges)
   )"""

ONLY_TEXT_MAPPED = """      parse_message(
         _required(edge, "node", f"{connection_path}.edges[{index}]"),
         f"{connection_path}.edges[{index}].node",
      )
      for index, edge in enumerate(edges)
      if edge["node"]["content_type"] == "TEXT"
   )"""

SENDER_FROM_FBID = """   fbid = _required_string(node, "sender_fbid", path)"""

SENDER_FROM_IGID = """   fbid = _required_string(node["sender"], "igid", path)"""

SENT_AT_KEEPS_MILLISECONDS = "datetime.fromtimestamp(milliseconds / MILLISECONDS_PER_SECOND"

SENT_AT_DROPS_MILLISECONDS = "datetime.fromtimestamp(milliseconds // MILLISECONDS_PER_SECOND"


def replace_text(find: str, replace: str) -> Callable[[bytes], bytes]:
   def transform(original: bytes) -> bytes:
      text = original.decode("utf-8")

      occurrences = text.count(find)

      if occurrences != 1:
         raise SystemExit(
            f"mutation anchor found {occurrences} times, expected exactly once: {find[:60]!r}"
         )

      return text.replace(find, replace, 1).encode("utf-8")

   return transform


def exempt_a_message_the_pages_hold(original: bytes) -> bytes:
   independent = json.loads(original)
   exempted = set(independent["absent_from_capture"])
   present = next(
      record["id"] for record in independent["messages"] if record["id"] not in exempted
   )
   independent["absent_from_capture"].append(present)

   return json.dumps(independent).encode("utf-8")


def empty_the_recorded_thread(original: bytes) -> bytes:
   return gzip.compress(b"[]", mtime=0)


MUTATIONS: list[dict[str, object]] = [
   {
      "gate": f"{ORACLE}::test_the_read_follows_every_recorded_cursor_and_stops_on_the_terminator",
      "defect": "the next page is requested with a cursor the upstream did not hand out",
      "file": PARSE_DIRECT,
      "transform": replace_text(THREAD_CURSOR_FROM_END, THREAD_CURSOR_FROM_START),
   },
   {
      "gate": f"{ORACLE}::test_no_message_is_read_twice",
      "defect": "a page carries a message twice",
      "file": PARSE_DIRECT,
      "transform": replace_text(THREAD_PAGE_AS_SENT, THREAD_PAGE_REPEATS_ITS_LAST),
   },
   {
      "gate": (
         f"{ORACLE}::test_the_window_holds_exactly_the_messages_the_independent_export_holds"
      ),
      "defect": "the mapper silently skips every content type it was not written against",
      "file": PARSE_DIRECT,
      "transform": replace_text(EVERY_EDGE_MAPPED, ONLY_TEXT_MAPPED),
   },
   {
      "gate": f"{ORACLE}::test_every_message_in_the_window_agrees_with_the_independent_export",
      "defect": "the sender is read from the Instagram-side id rather than the fbid",
      "file": PARSE_DIRECT,
      "transform": replace_text(SENDER_FROM_FBID, SENDER_FROM_IGID),
   },
   {
      "gate": f"{ORACLE}::test_every_message_in_the_window_agrees_with_the_independent_export",
      "defect": "the timestamp loses its milliseconds",
      "file": PARSE_DIRECT,
      "transform": replace_text(SENT_AT_KEEPS_MILLISECONDS, SENT_AT_DROPS_MILLISECONDS),
   },
   {
      "gate": f"{ORACLE}::test_every_exempted_message_is_missing_from_the_raw_pages_too",
      "defect": "the exemption list grows to cover a message the pages do hold",
      "file": INDEPENDENT,
      "transform": exempt_a_message_the_pages_hold,
   },
   {
      "gate": f"{ORACLE}::test_the_fixtures_hold_a_whole_thread_and_a_whole_independent_export",
      "defect": "the recorded thread is empty, which would make the other gates vacuous",
      "file": PAGES,
      "transform": empty_the_recorded_thread,
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


def main() -> int:
   results = []

   for mutation in MUTATIONS:
      gate = str(mutation["gate"])
      path = ENGINE / str(mutation["file"])
      transform = mutation["transform"]
      assert callable(transform)

      original = path.read_bytes()
      path.write_bytes(transform(original))

      try:
         mutated = run_gate(gate)
      finally:
         path.write_bytes(original)

      restored = run_gate(gate)

      results.append(
         {
            "gate": gate,
            "defect": mutation["defect"],
            "mutated_file": mutation["file"],
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
   log_path = LOG_DIR / f"mutation-oracle-{stamp}.json"
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
