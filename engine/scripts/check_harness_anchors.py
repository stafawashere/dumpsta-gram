"""Gate: every mutation anchor of every harness is found exactly once in the source, today.

Each ``scripts/verify_*_gates.py`` refuses an anchor that is not found exactly once, but only
when it reaches that row, and only when someone runs it. In release phase 4 four of them
(direct_send, oracle, phase2, thread_route) were found refusing on anchors that had gone stale
in release phase 2, when ``parse_message`` gained ``viewer_igid`` and a second
``isinstance(answer, bool)`` check landed, and nothing had said so for two phases. A stale
anchor means the gates behind it are vouched for by nobody.

This check reads each harness's ``MUTATIONS`` without running a gate and without writing a file:

- a row with ``edits`` is a list of ``(file, find, replace)``, and each ``find`` is counted,
- a row with ``file`` and ``find`` is counted the same way,
- a row with a ``transform`` is called on the file's bytes in memory, and an anchor refusal
  (``SystemExit``) from it counts as stale.

Every run first proves the counting on built-in controls, a missing anchor and a doubled one,
and exits 2 as unrunnable if either goes unreported, so a dead scanner cannot report zero.

Exit 0 when every anchor is found once, 1 when one is not, 2 when the check could not run.
Run from ``engine/`` with ``uv run python scripts/check_harness_anchors.py``. It reads only, so it
must not run beside a harness, which mutates the source while it runs.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

ENGINE = Path(__file__).resolve().parents[1]
SCRIPTS = ENGINE / "scripts"

Anchor = tuple[str, str, Callable[[bytes], bool]]
"""A gate, the file its mutation edits, and whether that mutation's anchor is found once."""


def load(path: Path) -> ModuleType:
   spec = importlib.util.spec_from_file_location(path.stem, path)

   if spec is None or spec.loader is None:
      raise RuntimeError(f"cannot load {path.name}")

   module = importlib.util.module_from_spec(spec)
   spec.loader.exec_module(module)

   return module


def found_once(find: str) -> Callable[[bytes], bool]:
   anchor = find.encode("utf-8")
   return lambda content: content.count(anchor) == 1


# A transform may rewrite a binary fixture, such as the oracle's gzip pages, so files are read
# and handed over as bytes.
def transform_applies(transform: Callable[[bytes], bytes]) -> Callable[[bytes], bool]:
   def applies(content: bytes) -> bool:
      try:
         transform(content)
      except SystemExit:
         return False

      return True

   return applies


def anchors(mutations: list[dict[str, Any]]) -> Iterator[Anchor]:
   for mutation in mutations:
      gate = str(mutation.get("gate", "?"))

      if "edits" in mutation:
         for edit in mutation["edits"]:
            yield gate, str(edit[0]), found_once(str(edit[1]))
      elif "find" in mutation:
         yield gate, str(mutation["file"]), found_once(str(mutation["find"]))
      elif "transform" in mutation:
         yield gate, str(mutation["file"]), transform_applies(mutation["transform"])
      else:
         raise RuntimeError(f"a mutation for {gate} has no edits, find or transform")


def stale(mutations: list[dict[str, Any]], read: Callable[[str], bytes]) -> list[str]:
   return [
      f"{gate} ({relative})"
      for gate, relative, is_found_once in anchors(mutations)
      if not is_found_once(read(relative))
   ]


def controls_report_both() -> bool:
   """The positive control: one missing anchor and one doubled anchor, both reported."""

   files = {"control.py": b"alpha\nbeta\nbeta\n"}
   mutations: list[dict[str, Any]] = [
      {"gate": "missing", "edits": [("control.py", "gamma\n", "")]},
      {"gate": "doubled", "file": "control.py", "find": "beta\n"},
      {"gate": "present", "edits": [("control.py", "alpha\n", "")]},
   ]
   reported = stale(mutations, files.__getitem__)

   return reported == ["missing (control.py)", "doubled (control.py)"]


def main() -> int:
   if not controls_report_both():
      print("check_harness_anchors: the controls were not both reported, so nothing is vouched for")
      return 2

   harnesses = sorted(SCRIPTS.glob("verify_*_gates.py"))

   if not harnesses:
      print("check_harness_anchors: no harness found")
      return 2

   cache: dict[str, bytes] = {}

   def read(relative: str) -> bytes:
      if relative not in cache:
         cache[relative] = (ENGINE / relative).read_bytes()

      return cache[relative]

   sys.path.insert(0, str(SCRIPTS))
   problems: list[str] = []
   counted = 0

   for path in harnesses:
      module = load(path)
      mutations = getattr(module, "MUTATIONS", None)

      if not isinstance(mutations, list) or not mutations:
         problems.append(f"{path.name}: no MUTATIONS list")
         continue

      counted += sum(1 for _ in anchors(mutations))
      problems.extend(f"{path.name}: {entry}" for entry in stale(mutations, read))

   for problem in problems:
      print(f"stale: {problem}")

   print("positive control: a missing and a doubled anchor were both reported")
   print(f"harness anchors: {counted} in {len(harnesses)} harnesses, {len(problems)} stale")

   return 1 if problems else 0


if __name__ == "__main__":
   raise SystemExit(main())
