"""Break the additive surface check and the snapshot it guards, watch each gate go red, restore.

Same harness and same rule as ``verify_parity_gates.py``: one mutation per gate, only the gate
that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind. Two of the mutations edit
``tests/public_surface.txt`` itself, one deleting a baseline line and one changing another,
because that is the defect the freeze exists to catch.

Run from ``engine/`` with ``uv run python scripts/verify_surface_additive_gates.py``. Writes its
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


CHECK = "scripts/check_surface_additive.py"
SNAPSHOT = "tests/public_surface.txt"
GATES = "tests/test_surface_additive.py"

MUTATIONS: list[dict[str, object]] = [
   {
      "gate": f"{GATES}::test_the_baseline_is_the_phase_3_snapshot",
      "defect": "the baseline points at the Phase 2 snapshot rather than the Phase 3 one",
      "edits": [(CHECK, 'BASELINE_COMMIT = "413793a"', 'BASELINE_COMMIT = "3f84560"')],
   },
   {
      "gate": f"{GATES}::test_the_committed_snapshot_keeps_every_baseline_line",
      "defect": "a baseline line is deleted from the committed snapshot",
      "edits": [(SNAPSHOT, "alias dumpstagram.FAST -> dumpstagram.behavior.FAST\n", "")],
   },
   {
      "gate": f"{GATES}::test_the_committed_snapshot_keeps_every_baseline_line",
      "defect": "a baseline line is changed in the committed snapshot",
      "edits": [
         (
            SNAPSHOT,
            "alias dumpstagram.NotFound -> dumpstagram.errors.NotFound\n",
            "alias dumpstagram.NotFound -> dumpstagram.errors.Missing\n",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_a_deleted_baseline_line_is_reported",
      "defect": "the comparison runs the wrong way and reports additions as missing",
      "edits": [
         (
            CHECK,
            "missing = sorted((baseline_counts - current_counts).elements())",
            "missing = sorted((current_counts - baseline_counts).elements())",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_a_changed_baseline_line_is_reported",
      "defect": "entries are matched by name, so a changed signature passes",
      "edits": [
         (
            CHECK,
            "   baseline_counts = Counter(baseline)\n   current_counts = Counter(current)\n",
            '   baseline_counts = Counter(line.split("(")[0] for line in baseline)\n'
            '   current_counts = Counter(line.split("(")[0] for line in current)\n',
         )
      ],
   },
   {
      "gate": f"{GATES}::test_an_added_line_is_allowed_and_counted",
      "defect": "an added line fails the check, which is the literal freeze ADR-0011 amended away",
      "edits": [
         (
            CHECK,
            "   if comparison.is_additive:\n",
            "   if comparison.is_additive and not comparison.added:\n",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_the_command_line_run_is_green_on_the_committed_snapshot",
      "defect": "the positive control mutates nothing, so the run cannot trust itself",
      "edits": [
         (
            CHECK,
            '   mutated = [*baseline[1:-1], changed + " | changed"]',
            "   mutated = list(baseline)",
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
   log_path = LOG_DIR / f"mutation-surface-additive-{stamp}.json"
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
