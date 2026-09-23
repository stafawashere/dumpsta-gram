"""Break the behavior configuration, watch each of its gates go red, restore.

Same harness and same rule as ``verify_parity_gates.py``: one mutation per gate, only the gate
that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

Run from ``engine/`` with ``uv run python scripts/verify_behavior_gates.py``. Writes its result
to ``engine/logs/``.
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
CLIENT = "dumpstagram/client.py"
PACER = "dumpstagram/_core/pacer.py"
BEHAVIOR = "dumpstagram/behavior.py"
GATES = "tests/test_behavior.py"

MUTATIONS: list[dict[str, object]] = [
   {
      "gate": f"{GATES}::test_the_departing_request_chooses_its_own_gap",
      "defect": "the pacer spaces by its own policy and ignores the one it was handed",
      "edits": [
         (
            PACER,
            "await self._wait_until_allowed(pacing or self.pacing)",
            "await self._wait_until_allowed(self.pacing)",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_a_client_spaces_by_its_behavior",
      "defect": "the client accepts a behavior and paces by the fixed default",
      "edits": [
         (
            AIO,
            "transport, Pacer(), pacing_for(behavior), write_policy_for(behavior)",
            "transport, Pacer(), None, write_policy_for(behavior)",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_a_scoped_client_shares_the_account_pacer",
      "defect": "a scoped client gets a pacer of its own",
      "edits": [
         (
            AIO,
            "self._sender.with_pacing(pacing_for(behavior), write_policy_for(behavior))",
            "PacedSender(\n"
            "         self._sender._sender, Pacer(), pacing_for(behavior), "
            "write_policy_for(behavior)\n"
            "      )",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_closing_a_scoped_client_leaves_the_pool_open",
      "defect": "closing a scoped client closes the pool it borrowed",
      "edits": [(AIO, "owns_the_pool = self._owner is None", "owns_the_pool = True")],
   },
   {
      "gate": f"{GATES}::test_closing_the_owner_stops_its_scoped_clients",
      "defect": "a scoped client ignores its owner having closed",
      "edits": [
         (
            AIO,
            "owner_closed = self._owner is not None and self._owner.closed",
            "owner_closed = False",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_a_blocking_scoped_client_holds_and_releases_its_own_thread_reference",
      "defect": "a blocking scoped client releases a loop thread reference it never took",
      "edits": [(CLIENT, "scoped._loop = _LoopThread.acquire()", "scoped._loop = self._loop")],
   },
   {
      "gate": f"{GATES}::test_negative_spacing_is_refused",
      "defect": "a negative spacing reaches the pacer",
      "edits": [
         (
            BEHAVIOR,
            "if has_negative_floor or has_negative_jitter:",
            "if False:",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_the_export_preset_is_the_sustained_measured_rate",
      "defect": "the export preset drifts from the sustained measured rate",
      "edits": [
         (
            BEHAVIOR,
            "EXPORT = Behavior(spacing=Spacing(floor_seconds=2.5, mean_jitter_seconds=0.35))",
            "EXPORT = Behavior(spacing=Spacing(floor_seconds=2.0, mean_jitter_seconds=0.35))",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_parity_spacing_is_the_measured_human_fit",
      "defect": "the parity default drifts from the fitted numbers",
      "edits": [
         (
            BEHAVIOR,
            "spacing: Spacing = Spacing(floor_seconds=1.3, mean_jitter_seconds=2.0)",
            "spacing: Spacing = Spacing(floor_seconds=2.5, mean_jitter_seconds=0.35)",
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
   log_path = LOG_DIR / f"mutation-behavior-{stamp}.json"
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
