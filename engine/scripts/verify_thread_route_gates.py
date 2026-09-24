"""Break how a thread is read, watch each of its gates go red, restore.

Same harness and same rule as ``verify_parity_gates.py``: one mutation per gate, only the gate
that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

Run from ``engine/`` with ``uv run python scripts/verify_thread_route_gates.py``. Writes its
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
DIRECT = "dumpstagram/_core/direct.py"
PARSE_DIRECT = "dumpstagram/_private/web/parse/direct.py"
REQUESTS_DIRECT = "dumpstagram/_private/web/requests/direct.py"
GATES = "tests/test_thread_route.py"

MUTATIONS: list[dict[str, object]] = [
   {
      "gate": f"{GATES}::test_a_default_client_opens_a_thread_with_the_detail_query",
      "defect": "the client does not pass its behavior down to the capability",
      "edits": [(AIO, "         first_page=self._behavior.thread_first_page,\n", "")],
   },
   {
      "gate": f"{GATES}::test_the_detail_query_carries_the_variables_a_browser_sent",
      "defect": "the chat themes flag goes out as the replay template's true",
      "edits": [
         (
            REQUESTS_DIRECT,
            '"__relay_internal__pv__IGDEnableOffMsysChatThemesQErelayprovider": False,',
            '"__relay_internal__pv__IGDEnableOffMsysChatThemesQErelayprovider": True,',
         )
      ],
   },
   {
      "gate": f"{GATES}::test_an_older_page_goes_through_the_query_a_browser_scrolls_with",
      "defect": "older pages stay on the retired pagination doc_id",
      "edits": [
         (
            REQUESTS_DIRECT,
            "      THREAD_OLDER_PAGE,\n      _thread_page_variables",
            "      THREAD_MESSAGE_PAGE,\n      _thread_page_variables",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_a_top_up_is_not_sent_as_a_thread_open",
      "defect": "a newer-than read is sent as a thread open and loses its marker",
      "edits": [
         (
            DIRECT,
            "is_newest_page = after is None and newer_than_message_id is None",
            "is_newest_page = after is None",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_the_query_departure_reads_the_newest_page_with_the_scrolling_query",
      "defect": "ThreadFirstPage.QUERY is ignored",
      "edits": [
         (
            DIRECT,
            "opens_the_thread = is_newest_page and first_page is ThreadFirstPage.DETAIL",
            "opens_the_thread = is_newest_page",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_the_capability_keeps_the_scrolling_query_as_its_own_default",
      "defect": "the capability's own default flips to the detail query",
      "edits": [
         (
            DIRECT,
            "first_page: ThreadFirstPage = ThreadFirstPage.QUERY,",
            "first_page: ThreadFirstPage = ThreadFirstPage.DETAIL,",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_the_detail_mapper_reads_the_detail_root_and_keeps_the_cursor",
      "defect": "the detail mapper reads the pagination query's root field",
      "edits": [
         (
            PARSE_DIRECT,
            "   return _message_page(payload, THREAD_DETAIL_PATH)",
            "   return _message_page(payload, THREAD_PAGE_PATH)",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_a_null_thread_raises_rather_than_reading_as_an_empty_thread",
      "defect": "a null thread is mapped to an empty page",
      "edits": [
         (
            PARSE_DIRECT,
            "   return _message_page(payload, THREAD_DETAIL_PATH)",
            '   if payload["data"]["get_slide_thread_nullable"] is None:\n'
            "      return Page(items=(), has_next_page=False)\n\n"
            "   return _message_page(payload, THREAD_DETAIL_PATH)",
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
   log_path = LOG_DIR / f"mutation-thread-route-{stamp}.json"
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
