"""Gates for the additive freeze, ADR-0011 as amended on 2026-09-23.

The committed snapshot may grow, but no line of it at the Phase 3 baseline may be removed or
changed. `scripts/check_surface_additive.py` owns the comparison, and these gates run it against
the committed file and against temporary copies that break it on purpose.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ENGINE_ROOT = Path(__file__).resolve().parent.parent
CHECK_PATH = ENGINE_ROOT / "scripts" / "check_surface_additive.py"
SNAPSHOT_PATH = ENGINE_ROOT / "tests" / "public_surface.txt"

PHASE_3_BASELINE_LINES = 254


def load_check() -> ModuleType:
   specification = importlib.util.spec_from_file_location("check_surface_additive", CHECK_PATH)

   assert specification is not None and specification.loader is not None

   module = importlib.util.module_from_spec(specification)
   sys.modules[specification.name] = module
   specification.loader.exec_module(module)

   return module


@pytest.fixture(scope="module")
def check() -> ModuleType:
   return load_check()


@pytest.fixture(scope="module")
def baseline(check: ModuleType) -> list[str]:
   lines: list[str] = check.read_baseline()

   return lines


def write_copy(directory: Path, lines: list[str]) -> Path:
   copy = directory / "public_surface.txt"
   copy.write_text("\n".join(lines) + "\n", encoding="utf-8")

   return copy


def test_the_baseline_is_the_phase_3_snapshot(baseline: list[str]) -> None:
   assert len(baseline) == PHASE_3_BASELINE_LINES


def test_the_committed_snapshot_keeps_every_baseline_line(
   check: ModuleType, baseline: list[str]
) -> None:
   current = SNAPSHOT_PATH.read_text(encoding="utf-8").splitlines()

   comparison = check.compare(baseline, current)

   assert comparison.missing == [], (
      "a line of the Phase 3 baseline was removed or changed, which restarts the freeze under "
      "ADR-0011. That is the owner's call, never a regenerated snapshot"
   )


def test_a_deleted_baseline_line_is_reported(
   check: ModuleType, baseline: list[str], tmp_path: Path
) -> None:
   deleted = baseline[len(baseline) // 2]
   remaining = [line for line in baseline if line != deleted]

   assert check.main(["--current", str(write_copy(tmp_path, remaining))]) == 1
   assert check.compare(baseline, remaining).missing == [deleted]


def test_a_changed_baseline_line_is_reported(
   check: ModuleType, baseline: list[str], tmp_path: Path
) -> None:
   original = next(line for line in baseline if line.startswith("def ") and "->" in line)
   changed = original.replace("->", "-> None | ", 1)
   edited = [changed if line == original else line for line in baseline]

   assert check.main(["--current", str(write_copy(tmp_path, edited))]) == 1
   assert check.compare(baseline, edited).missing == [original]


def test_an_added_line_is_allowed_and_counted(
   check: ModuleType, baseline: list[str], tmp_path: Path
) -> None:
   added = "def dumpstagram.client.SyncClient.a_later_capability(self) -> None"
   grown = sorted([*baseline, added])

   assert check.main(["--current", str(write_copy(tmp_path, grown))]) == 0
   assert check.compare(baseline, grown).added == [added]


def test_the_command_line_run_is_green_on_the_committed_snapshot(
   check: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
   exit_code = check.main([])
   printed = capsys.readouterr().out

   assert exit_code == 0
   assert "positive control: a deleted and a changed baseline line were both reported" in printed
