"""Break the first feed page's document route, watch each of its gates go red, restore.

Same harness and same rule as ``verify_parity_gates.py``: one mutation per gate, only the gate
that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

Run from ``engine/`` with ``uv run python scripts/verify_feed_first_page_gates.py``. Writes its
result to ``engine/logs/``.
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


AIO = "dumpstagram/aio.py"
FEED = "dumpstagram/_core/feed.py"
PRELOAD = "dumpstagram/_private/web/preload.py"
BEHAVIOR = "dumpstagram/behavior.py"
GATES = "tests/test_feed_first_page.py"

MUTATIONS: list[dict[str, object]] = [
   {
      "gate": f"{GATES}::test_the_reader_takes_the_feed_preload_and_not_the_one_before_it",
      "defect": "the reader returns the first stream call whatever query it preloaded",
      "edits": [(PRELOAD, "if is_the_wanted_query:", "if True:")],
   },
   {
      "gate": f"{GATES}::test_a_preload_the_upstream_has_not_finished_raises",
      "defect": "a result not marked complete is accepted",
      "edits": [(PRELOAD, 'if box.get("complete") is not True:', "if False:")],
   },
   {
      "gate": f"{GATES}::test_two_preloaded_chunks_raise_rather_than_one_being_picked",
      "defect": "a streamed result keeps its first chunk and drops the rest",
      "edits": [(PRELOAD, "if len(boxes) > 1:", "if False:")],
   },
   {
      "gate": f"{GATES}::test_the_document_route_spends_one_navigation_and_no_query",
      "defect": "the first page goes through the pagination query under parity",
      "edits": [
         (
            FEED,
            "reads_the_document = after is None and first_page is FeedFirstPage.DOCUMENT",
            "reads_the_document = False",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_the_document_route_writes_the_fresh_tokens_onto_the_session",
      "defect": "the document's tokens are read and thrown away",
      "edits": [(FEED, "apply_tokens(session, tokens_from(response))", "tokens_from(response)")],
   },
   {
      "gate": f"{GATES}::test_an_envelope_inside_the_preload_is_a_rejection",
      "defect": "a preloaded envelope goes straight to the mapper",
      "edits": [
         (
            FEED,
            "return parse_feed_page(classify_preloaded(result))",
            "return parse_feed_page(result)",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_a_page_with_a_cursor_goes_through_the_query_even_under_parity",
      "defect": "a page with a cursor is read from the document",
      "edits": [
         (
            FEED,
            "reads_the_document = after is None and first_page is FeedFirstPage.DOCUMENT",
            "reads_the_document = first_page is FeedFirstPage.DOCUMENT",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_parity_reads_the_first_page_from_the_document",
      "defect": "the parity default is the departure",
      "edits": [
         (
            BEHAVIOR,
            "feed_first_page: FeedFirstPage = FeedFirstPage.DOCUMENT",
            "feed_first_page: FeedFirstPage = FeedFirstPage.QUERY",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_the_client_sends_the_document_under_the_default_behavior",
      "defect": "the client drops its behavior and the capability falls back to the query",
      "edits": [(AIO, "first_page=self._behavior.feed_first_page,\n", "")],
   },
   {
      "gate": f"{GATES}::test_the_client_sends_the_query_when_the_behavior_names_the_departure",
      "defect": "the client always sends the document whatever the behavior names",
      "edits": [
         (
            AIO,
            "first_page=self._behavior.feed_first_page,",
            "first_page=type(self._behavior.feed_first_page).DOCUMENT,",
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

         if find not in current:
            raise SystemExit(f"mutation anchor not found in {relative} for {gate}")

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

   every_gate_fired = all(
      entry["red_under_mutation"] and entry["green_after_restore"] for entry in results
   )

   LOG_DIR.mkdir(parents=True, exist_ok=True)
   stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
   log_path = LOG_DIR / f"mutation-feed-first-page-{stamp}.json"
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
