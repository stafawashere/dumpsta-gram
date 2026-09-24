"""Break the rotation canary of E1 item 7, watch each gate go red, restore.

Same harness and same rule as ``verify_iterator_gates.py``: one mutation per entry below, only
the gate that should catch it is run, every anchor must be found exactly once, and every file is
restored from an in-memory copy in a ``finally`` so an interrupted run cannot leave a mutation
behind. A gate named without parameters runs every case it covers, and is red when any fails.

Run from ``engine/`` with ``uv run python scripts/verify_doctor_gates.py``. Writes its result to
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

GATE_TIMEOUT_SECONDS = 300

BUNDLES = "dumpstagram/_private/web/bundles.py"
CANARY = "dumpstagram/_private/web/canary.py"
CATALOG = "dumpstagram/_private/web/documents/catalog.py"
DOCTOR = "dumpstagram/_core/doctor.py"
ASSEMBLY = "dumpstagram/aio.py"
COMMAND = "dumpstagram/_cli/commands/doctor.py"
DOCTOR_GATES = "tests/test_doctor.py"

LIKE_BUILDER = '__import__("dumpstagram._private.web.requests.media", fromlist=["x"])'
NOTES_DOCUMENTS = '__import__("dumpstagram._private.web.documents.notes", fromlist=["x"])'


def gate(name: str) -> str:
   return f"{DOCTOR_GATES}::{name}"


MUTATIONS: list[dict[str, object]] = [
   {
      "gate": gate("test_the_recorded_bundle_yields_the_operation_and_the_doc_id_it_compiles"),
      "defect": "the id module is matched only when its exports object is named module",
      "edits": [
         (
            BUNDLES,
            r"""   r'\(function\([A-Za-z0-9_$,]*\)\{[A-Za-z0-9_$]+\.exports="(\d+)"\}\)'""",
            r"""   r'\(function\([A-Za-z0-9_$,]*\)\{module\.exports="(\d+)"\}\)'""",
         )
      ],
   },
   {
      "gate": gate("test_the_recorded_bundle_yields_the_operation_and_the_doc_id_it_compiles"),
      "defect": "an artifact is matched only when it has no dependencies",
      "edits": [
         (
            BUNDLES,
            """_OPERATION_ARTIFACT = re.compile(r'__d\\("([A-Za-z0-9_]+)\\.graphql"')""",
            """_OPERATION_ARTIFACT = re.compile(r'__d\\("([A-Za-z0-9_]+)\\.graphql",\\[\\]')""",
         )
      ],
   },
   {
      "gate": gate("test_every_bundle_the_document_names_is_found_once_in_document_order"),
      "defect": "the bootloader's escaped form goes unread",
      "edits": [(BUNDLES, '_SLASH = r"(?:\\\\/|/)"', '_SLASH = r"/"')],
   },
   {
      "gate": gate("test_every_bundle_the_document_names_is_found_once_in_document_order"),
      "defect": "a stylesheet is taken for a bundle",
      "edits": [
         (
            BUNDLES,
            r'   + r"[A-Za-z0-9_,.\-]+)*\.js(?![A-Za-z0-9_])"',
            r'   + r"[A-Za-z0-9_,.\-]+)*\.(?:js|css)(?![A-Za-z0-9_])"',
         )
      ],
   },
   {
      "gate": gate("test_every_bundle_the_document_names_is_found_once_in_document_order"),
      "defect": "a bundle named twice is listed twice",
      "edits": [
         (
            BUNDLES,
            "      ordered.setdefault(url, None)\n\n   return tuple(ordered)\n",
            "      ordered.setdefault(url, None)\n\n"
            '   return tuple(found.group(0).replace("\\\\/", "/") '
            "for found in _BUNDLE_URL.finditer(html))\n",
         )
      ],
   },
   {
      "gate": gate("test_an_operation_whose_compiled_id_differs_is_drift_with_both_ids_reported"),
      "defect": "an operation the bundle compiles under any id is reported ok",
      "edits": [(DOCTOR, "      elif found == {query.doc_id}:\n", "      elif found:\n")],
   },
   {
      "gate": gate("test_an_operation_no_bundle_compiles_is_missing_and_not_ok"),
      "defect": "an operation no bundle compiles is reported ok",
      "edits": [
         (
            DOCTOR,
            "         bundle = BundleVerdict.MISSING\n",
            "         bundle = BundleVerdict.OK\n",
         )
      ],
   },
   {
      "gate": gate("test_the_canary_never_sends_a_write_and_checks_every_write_by_artifact"),
      "defect": "the inbox replay step builds a like instead",
      "edits": [
         (
            CANARY,
            "      build=lambda session, arguments, user_agent: build_inbox_listing_request(\n"
            "         session, device_id=arguments.device_id, user_agent=user_agent\n"
            "      ),\n",
            "      build=lambda session, arguments, user_agent: "
            f"{LIKE_BUILDER}.build_like_request(\n"
            '         session, "3100000000000000001", client_mutation_id="1", '
            "user_agent=user_agent\n"
            "      ),\n",
         )
      ],
   },
   {
      "gate": gate("test_every_replay_step_is_a_catalogued_read_and_none_is_a_write"),
      "defect": "a replay step is keyed on a write",
      "edits": [
         (
            CANARY,
            "      query=INBOX_TRAY,\n",
            f"      query={NOTES_DOCUMENTS}.CREATE_NOTE,\n",
         )
      ],
   },
   {
      "gate": gate("test_every_replay_step_is_a_catalogued_read_and_none_is_a_write"),
      "defect": "a write is catalogued as a read",
      "edits": [
         (
            CATALOG,
            "READ_QUERIES: tuple[PersistedQuery, ...] = (\n   DIRECT_INBOX,\n",
            "READ_QUERIES: tuple[PersistedQuery, ...] = (\n   LIKE_MEDIA,\n   DIRECT_INBOX,\n",
         )
      ],
   },
   {
      "gate": gate("test_the_catalog_lists_every_registry_query_exactly_once"),
      "defect": "a registry query is left out of the catalog",
      "edits": [(CATALOG, "   PROFILE_SCHOOL_BADGE,\n)\n", ")\n")],
   },
   {
      "gate": gate("test_a_checkpoint_on_a_replay_ends_the_run_and_nothing_departs_after_it"),
      "defect": "a checkpoint is recorded as a failed replay and the run goes on",
      "edits": [(DOCTOR, "      except CheckpointRequired:\n         raise\n", "")],
   },
   {
      "gate": gate(
         "test_a_failed_replay_is_reported_with_its_classified_error_and_the_run_goes_on"
      ),
      "defect": "a failed replay is reported as ok",
      "edits": [
         (
            DOCTOR,
            "         return _ReplayOutcome(ReplayVerdict.FAILED, error=",
            "         return _ReplayOutcome(ReplayVerdict.OK, error=",
         )
      ],
   },
   {
      "gate": gate(
         "test_a_failed_replay_is_reported_with_its_classified_error_and_the_run_goes_on"
      ),
      "defect": "a failed replay ends the run",
      "edits": [
         (
            DOCTOR,
            "      except DumpstagramError as failure:\n",
            "      except DumpstagramError as failure:\n         raise\n",
         )
      ],
   },
   {
      "gate": gate("test_a_read_whose_argument_was_never_learned_is_skipped_and_not_sent"),
      "defect": "a read is sent whether or not its argument was learned",
      "edits": [
         (
            DOCTOR,
            "         missing_argument = needs_an_argument and learned is None\n",
            "         missing_argument = False\n",
         )
      ],
   },
   {
      "gate": gate("test_the_bundle_scan_stops_once_every_stored_operation_is_located"),
      "defect": "the scan fetches every bundle after it has its answer",
      "edits": [
         (
            DOCTOR,
            "         if every_operation_located:\n            break\n",
            "         if every_operation_located:\n            pass\n",
         )
      ],
   },
   {
      "gate": gate("test_the_bundle_scan_fetches_no_more_than_its_limit"),
      "defect": "the bundle limit is ignored",
      "edits": [
         (
            DOCTOR,
            "      within_the_limit = named[: self._bundle_limit]\n",
            "      within_the_limit = named\n",
         )
      ],
   },
   {
      "gate": gate("test_the_bundle_transport_is_cookieless_and_pinned_to_the_static_host"),
      "defect": "the bundle transport keeps a cookie jar",
      "edits": [
         (
            ASSEMBLY,
            "      allowed_host=STATIC_BUNDLE_HOST,\n      cookieless=True,\n",
            "      allowed_host=STATIC_BUNDLE_HOST,\n      cookieless=False,\n",
         )
      ],
   },
   {
      "gate": gate("test_the_bundle_transport_is_cookieless_and_pinned_to_the_static_host"),
      "defect": "the bundle transport is not pinned",
      "edits": [
         (
            ASSEMBLY,
            "      allowed_host=STATIC_BUNDLE_HOST,\n      cookieless=True,\n",
            "      allowed_host=None,\n      cookieless=True,\n",
         )
      ],
   },
   {
      "gate": gate("test_a_dry_run_sends_nothing_opens_no_client_and_states_the_plan"),
      "defect": "the command runs live without --live",
      "edits": [(COMMAND, "   if not arguments.live:\n", "   if False:\n")],
   },
   {
      "gate": gate("test_drift_exits_12_a_failed_replay_13_and_a_missing_operation_alone_0"),
      "defect": "drift exits 0",
      "edits": [
         (
            COMMAND,
            "   if report.drifted:\n      return EXIT_DRIFT\n",
            "   if report.drifted:\n      return EXIT_OK\n",
         )
      ],
   },
   {
      "gate": gate("test_drift_exits_12_a_failed_replay_13_and_a_missing_operation_alone_0"),
      "defect": "a failed replay is judged before drift and hides it",
      "edits": [
         (
            COMMAND,
            "   if report.drifted:\n      return EXIT_DRIFT\n\n"
            "   if report.failed_replays:\n      return EXIT_REPLAY_FAILED\n",
            "   if report.failed_replays:\n      return EXIT_REPLAY_FAILED\n\n"
            "   if report.drifted:\n      return EXIT_DRIFT\n",
         )
      ],
   },
   {
      "gate": gate("test_drift_exits_12_a_failed_replay_13_and_a_missing_operation_alone_0"),
      "defect": "a missing operation exits as drift",
      "edits": [
         (
            COMMAND,
            "   if report.drifted:\n",
            "   if report.drifted or report.missing:\n",
         )
      ],
   },
   {
      "gate": gate("test_a_live_run_states_what_it_will_send_on_stderr_before_it_sends"),
      "defect": "the plan is stated only after the run",
      "edits": [
         (COMMAND, "   print(render_plan_line(plan), file=stderr, flush=True)\n", ""),
         (
            COMMAND,
            "      report = runner.run(run_and_close())\n",
            "      report = runner.run(run_and_close())\n\n"
            "   print(render_plan_line(plan), file=stderr, flush=True)\n",
         ),
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
      timeout=GATE_TIMEOUT_SECONDS,
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
   log_path = LOG_DIR / f"mutation-doctor-{stamp}.json"
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
