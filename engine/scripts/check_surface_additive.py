"""Check that the public surface has only grown since the Phase 3 baseline.

ADR-0011, as amended on 2026-09-23, counts the API as frozen when no line of the snapshot at the
Phase 3 baseline has been removed or changed by the close of Phase 4. Added lines are allowed.
This reads the snapshot at :data:`BASELINE_COMMIT` through ``git show`` and fails when any of its
lines is missing from the current file. A changed line fails too, because its old form is gone.
Added lines are counted for the reviewer and never fail the check.

Run it from ``engine/``:

   uv run python scripts/check_surface_additive.py
   uv run python scripts/check_surface_additive.py --current path/to/copy.txt

Exit 0 when every baseline line is present, 1 when one is missing, 2 when the check could not
run. Every run first proves it can fail: an in-memory copy of the baseline with one line deleted
and another changed has to be reported as two missing lines, or the run stops with 2.

The baseline moves only when the owner rules that the freeze restarts, and then by editing
:data:`BASELINE_COMMIT`, which is the one place it is recorded in code.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
CURRENT_SNAPSHOT = ENGINE / "tests" / "public_surface.txt"

BASELINE_COMMIT = "413793a"
"""The commit that closed Step 12a, whose snapshot is the Phase 3 baseline at 254 lines."""

BASELINE_SNAPSHOT = "engine/tests/public_surface.txt"
"""The snapshot's path from the repository root, which is what ``git show`` resolves against."""


class BaselineUnavailable(Exception):
   """The baseline snapshot could not be read, so no verdict is possible."""


@dataclass(frozen=True)
class SurfaceComparison:
   missing: list[str]
   added: list[str]

   @property
   def is_additive(self) -> bool:
      return not self.missing


def read_baseline(commit: str = BASELINE_COMMIT) -> list[str]:
   try:
      finished = subprocess.run(
         ["git", "show", f"{commit}:{BASELINE_SNAPSHOT}"],
         cwd=ENGINE,
         capture_output=True,
         text=True,
         check=False,
      )
   except OSError as exc:
      raise BaselineUnavailable(f"git could not be started: {exc}") from exc

   if finished.returncode != 0:
      raise BaselineUnavailable(finished.stderr.strip() or f"git show exited {finished.returncode}")

   lines = finished.stdout.splitlines()

   if not lines:
      raise BaselineUnavailable(f"the snapshot at {commit} is empty")

   return lines


def compare(baseline: list[str], current: list[str]) -> SurfaceComparison:
   """Every baseline line the current file lacks, and every line it has beyond the baseline.

   Lines are counted rather than collected into sets, so a line that appeared twice in the
   baseline and once now is reported missing.
   """

   baseline_counts = Counter(baseline)
   current_counts = Counter(current)

   missing = sorted((baseline_counts - current_counts).elements())
   added = sorted((current_counts - baseline_counts).elements())

   return SurfaceComparison(missing=missing, added=added)


def control_passes(baseline: list[str]) -> bool:
   """Delete one baseline line and change another in a copy, and require both to be reported."""

   if len(baseline) < 2:
      return False

   deleted = baseline[0]
   changed = baseline[-1]
   mutated = [*baseline[1:-1], changed + " | changed"]

   comparison = compare(baseline, mutated)

   return comparison.missing == sorted([deleted, changed]) and len(comparison.added) == 1


def main(argv: list[str] | None = None) -> int:
   parser = argparse.ArgumentParser()
   parser.add_argument("--current", type=Path, default=CURRENT_SNAPSHOT)
   args = parser.parse_args(argv)

   try:
      baseline = read_baseline()
   except BaselineUnavailable as exc:
      print(f"baseline {BASELINE_COMMIT} could not be read: {exc}")

      return 2

   if not control_passes(baseline):
      print("positive control: a deleted and a changed line were not both reported")
      print("the check is not working, a result would be meaningless")

      return 2

   print("positive control: a deleted and a changed baseline line were both reported")

   if not args.current.is_file():
      print(f"current snapshot not found: {args.current}")

      return 2

   current = args.current.read_text(encoding="utf-8").splitlines()
   comparison = compare(baseline, current)

   print(f"baseline {BASELINE_COMMIT}: {len(baseline)} lines, current: {len(current)} lines")
   print(f"added since the baseline: {len(comparison.added)}")

   if comparison.is_additive:
      print("surface additive: ok, every baseline line is present")

      return 0

   print(f"surface additive: {len(comparison.missing)} baseline line(s) removed or changed")

   for line in comparison.missing:
      print(f"- {line}")

   return 1


if __name__ == "__main__":
   sys.exit(main())
