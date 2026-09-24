"""Break the durable pacing ledger, watch each of its gates go red, restore.

Same harness and same rule as ``verify_write_safety_gates.py``: one mutation per line below,
only the gate that should catch it is run, every anchor must be found exactly once, and every
file is restored from an in-memory copy in a ``finally`` so an interrupted run cannot leave a
mutation behind. The gates are in ``tests/test_pacing_ledger.py``, E1 item 8 of
``engine/docs/web-parity-plan.md``.

Run from ``engine/`` with ``uv run python scripts/verify_ledger_gates.py``. Writes its result to
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


LEDGER = "dumpstagram/_core/ledger.py"
PACER = "dumpstagram/_core/pacer.py"
CLIENT = "dumpstagram/aio.py"
BLOCKING_CLIENT = "dumpstagram/client.py"
SESSION_COMMAND = "dumpstagram/_cli/commands/session.py"
SESSION = "dumpstagram/session.py"

GATES = "tests/test_pacing_ledger.py"

LEDGER_IMPORT = (
   "from dumpstagram._core.ledger import LedgerUnreadable, MemoryLedger, WriteLedger, WriteRecord\n"
)


def gate(name: str, module: str = GATES) -> str:
   return f"{module}::{name}"


MUTATIONS: list[dict[str, object]] = [
   {
      "gate": gate("test_two_processes_on_one_session_file_share_one_write_budget"),
      "defect": "a departure is never recorded in the ledger",
      "edits": [(PACER, "         record.departures.append(now)\n", "         pass\n")],
   },
   {
      "gate": gate("test_a_write_stop_seen_by_one_process_refuses_writes_in_another"),
      "defect": "the stop is not persisted",
      "edits": [(PACER, "         await self.ledger.update(_mark_stopped)\n", "         pass\n")],
   },
   {
      "gate": gate("test_the_write_stop_survives_a_restart_long_after_the_window"),
      "defect": "the stop lapses with the budget window",
      "edits": [
         (
            PACER,
            "      record.forget_before(now - WRITE_BUDGET_WINDOW_SECONDS)\n",
            "      record.forget_before(now - WRITE_BUDGET_WINDOW_SECONDS)\n"
            "      stopped_at = record.stopped_at or now\n"
            "      stopped_long_ago = now - stopped_at > WRITE_BUDGET_WINDOW_SECONDS\n"
            "      record.writes_stopped = record.writes_stopped and not stopped_long_ago\n",
         )
      ],
   },
   {
      "gate": gate("test_concurrent_increments_under_the_lock_are_not_lost"),
      "defect": "the file lock is removed",
      "edits": [(LEDGER, "         fcntl.flock(descriptor, fcntl.LOCK_EX)\n", "")],
   },
   {
      "gate": gate("test_the_rolling_window_frees_the_shared_budget"),
      "defect": "the rolling window is not applied",
      "edits": [(PACER, "      record.forget_before(now - WRITE_BUDGET_WINDOW_SECONDS)\n", "")],
   },
   {
      "gate": gate("test_a_budget_spent_elsewhere_during_the_wait_refuses_the_write"),
      "defect": "the ledger is read once and not reloaded before a later check",
      "edits": [
         (
            LEDGER,
            "         record = self._read()\n",
            '         record = self.__dict__.get("_trusted") or self._read()\n'
            "         self._trusted = record\n",
         )
      ],
   },
   {
      "gate": gate("test_a_budget_spent_elsewhere_during_the_wait_refuses_the_write"),
      "defect": "the departure is recorded after the wait without a second judgement",
      "edits": [
         (
            PACER,
            "         await self._judge_write(writes, record_departure=True)\n",
            "         await self.ledger.update(\n"
            "            lambda record, now: record.departures.append(now)\n"
            "         )\n",
         )
      ],
   },
   {
      "gate": gate("test_a_stop_shared_by_another_process_refuses_before_the_wait"),
      "defect": "the judgement before the wait is dropped",
      "edits": [(PACER, "         await self._judge_write(writes, record_departure=False)\n", "")],
   },
   {
      "gate": gate("test_a_corrupt_ledger_refuses_writes_and_is_left_as_it_was"),
      "defect": "a ledger that is not JSON is read as empty",
      "edits": [
         (
            LEDGER,
            '         raise LedgerUnreadable(f"the pacing ledger at {self.path} is not JSON") '
            "from parse_failure\n",
            "         return WriteRecord()\n",
         )
      ],
   },
   {
      "gate": gate("test_a_ledger_from_a_newer_engine_refuses_writes_and_is_left_as_it_was"),
      "defect": "any integer schema_version is read as this one",
      "edits": [
         (
            LEDGER,
            "is_this_version = type(version) is int and version == LEDGER_SCHEMA_VERSION",
            "is_this_version = type(version) is int",
         )
      ],
   },
   {
      "gate": gate("test_pacers_over_a_bare_session_keep_their_own_budgets"),
      "defect": "a pacer with no ledger given keeps one in a file anyway",
      "edits": [
         (
            PACER,
            LEDGER_IMPORT,
            LEDGER_IMPORT.replace("import LedgerUnreadable", "import FileLedger, LedgerUnreadable"),
         ),
         (
            PACER,
            "self.ledger: WriteLedger = ledger or MemoryLedger(clock)",
            'self.ledger: WriteLedger = ledger or FileLedger("pacing.ledger")',
         ),
      ],
   },
   {
      "gate": gate("test_clients_from_a_session_file_keep_the_ledger_beside_it"),
      "defect": "the awaitable client from a file keeps its pacing in memory",
      "edits": [(CLIENT, "      client._keep_write_record_beside(path)\n", "")],
   },
   {
      "gate": gate("test_clients_from_a_session_file_keep_the_ledger_beside_it"),
      "defect": "the blocking client from a file keeps its pacing in memory",
      "edits": [(BLOCKING_CLIENT, "      client._impl._keep_write_record_beside(path)\n", "")],
   },
   {
      "gate": gate("test_clearing_the_write_stop_keeps_the_hours_departures"),
      "defect": "clearing the stop also forgets the budget",
      "edits": [
         (
            SESSION,
            "   record.stopped_at = None\n",
            "   record.stopped_at = None\n   record.departures = []\n",
         )
      ],
   },
   {
      "gate": gate("test_the_session_command_leaves_the_write_stop_unless_asked"),
      "defect": "the session command clears the stop unasked",
      "edits": [(SESSION_COMMAND, "   if arguments.clear_write_stop:\n", "   if True:\n")],
   },
   {
      "gate": gate("test_clearing_the_stop_on_an_unreadable_ledger_changes_nothing"),
      "defect": "clearing the stop deletes a ledger it could not read",
      "edits": [
         (
            SESSION,
            "   except LedgerUnreadable as unreadable:\n",
            "   except LedgerUnreadable as unreadable:\n      ledger.path.unlink()\n",
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
   log_path = LOG_DIR / f"mutation-ledger-{stamp}.json"
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
