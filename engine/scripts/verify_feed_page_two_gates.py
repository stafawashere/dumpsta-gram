"""Break the feed's page two request, watch each of its gates go red, restore.

Same harness and same rule as ``verify_parity_gates.py``: one mutation per gate, only the gate
that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

Run from ``engine/`` with ``uv run python scripts/verify_feed_page_two_gates.py``. Writes its
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


BOOTSTRAP = "dumpstagram/_private/web/bootstrap.py"
DOCUMENTS_COMMON = "dumpstagram/_private/web/documents/common.py"
DOCUMENTS_FEED = "dumpstagram/_private/web/documents/feed.py"
REQUESTS_COMMON = "dumpstagram/_private/web/requests/common.py"
FEED = "dumpstagram/_core/feed.py"
SESSION = "dumpstagram/session.py"
FEED_GATES = "tests/test_feed.py"
BOOTSTRAP_GATES = "tests/test_bootstrap.py"
SESSION_GATES = "tests/test_session.py"

MUTATIONS: list[dict[str, object]] = [
   {
      "gate": f"{FEED_GATES}::test_the_feed_request_carries_the_two_headers_its_path_carries",
      "defect": "the feed request goes out without the path headers",
      "edits": [(REQUESTS_COMMON, "   if query.sends_path_headers:\n", "   if False:\n")],
   },
   {
      "gate": f"{FEED_GATES}::test_a_query_on_the_other_path_carries_neither_header",
      "defect": "every query carries the path headers whatever path it answers on",
      "edits": [(DOCUMENTS_COMMON, "return self.url == GRAPHQL_QUERY_URL", "return True")],
   },
   {
      "gate": f"{FEED_GATES}::test_every_query_on_the_graphql_query_path_names_its_root_field",
      "defect": "a query on /graphql/query is registered without a root field",
      "edits": [
         (
            DOCUMENTS_FEED,
            '   root_field="xdt_api__v1__feed__timeline__connection",\n',
            "",
         )
      ],
   },
   {
      "gate": f"{FEED_GATES}::test_the_feed_request_refuses_a_session_with_no_bloks_version_id",
      "defect": "a missing bloks id goes out as an empty header",
      "edits": [
         (
            REQUESTS_COMMON,
            "is_missing_bloks_version = query.sends_path_headers and not session.bloks_version_id",
            "is_missing_bloks_version = False",
         )
      ],
   },
   {
      "gate": (
         f"{FEED_GATES}::"
         "test_a_session_saved_before_the_bloks_id_existed_bootstraps_before_the_feed"
      ),
      "defect": "a session with page tokens but no bloks id is not refreshed",
      "edits": [
         (
            FEED,
            "lacks_page_tokens = not session.fb_dtsg or not session.bloks_version_id",
            "lacks_page_tokens = not session.fb_dtsg",
         )
      ],
   },
   {
      "gate": f"{BOOTSTRAP_GATES}::test_every_token_is_read_off_the_page",
      "defect": "the bloks id pattern stops matching",
      "edits": [(BOOTSTRAP, '"WebBloksVersioningID",', '"WebBloksVersionID",')],
   },
   {
      "gate": f"{BOOTSTRAP_GATES}::test_a_page_without_a_bloks_version_id_still_bootstraps",
      "defect": "a page without a bloks id fails the whole bootstrap",
      "edits": [
         (
            BOOTSTRAP,
            "   spin_revision = _first_match(_SPIN_REVISION, html)\n",
            "   if not _first_match(_BLOKS_VERSION_ID, html):\n"
            '      raise AuthenticationFailed("no bloks id")\n\n'
            "   spin_revision = _first_match(_SPIN_REVISION, html)\n",
         )
      ],
   },
   {
      "gate": f"{BOOTSTRAP_GATES}::test_bootstrap_writes_every_token_onto_the_session",
      "defect": "the bloks id is read and never written onto the session",
      "edits": [(BOOTSTRAP, "   session.bloks_version_id = tokens.bloks_version_id\n", "")],
   },
   {
      "gate": f"{SESSION_GATES}::test_round_trip_through_disk_preserves_every_field",
      "defect": "the bloks id is saved and not loaded back",
      "edits": [(SESSION, 'bloks_version_id=payload.get("bloks_version_id"),', "")],
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
   log_path = LOG_DIR / f"mutation-feed-page-two-{stamp}.json"
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
