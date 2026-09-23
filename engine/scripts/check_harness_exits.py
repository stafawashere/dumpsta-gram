"""Prove every mutation harness exits nonzero when it cannot vouch for its gates.

On 2026-09-23 ``verify_cli_gates.py`` reported three gates that did not fire, and the cause
was an anchor that had become ambiguous: the write-back block it named had been copied into
every command since the profile command landed, ``str.replace(..., 1)`` mutated the first copy,
and the thread gates never ran that code. Each harness now refuses an anchor that is not found
exactly once. This script checks that refusal, and the plain exit code, in each of them.

For every ``scripts/verify_*_gates.py`` it runs three controls, each through the harness's own
``main()`` with its first mutation altered in memory, and it expects a nonzero exit from each:

- the anchor is missing from the file, refused before any gate runs,
- the anchor is found more than once, refused the same way,
- the mutation changes nothing, so the gate stays green under it and does not fire.

The first two must end in the harness's anchor refusal and not merely in a nonzero code. Before
the fix an ambiguous anchor was applied at its first copy, and a nonzero exit could only come
later, from a gate that happened not to fire.

No source file is written by the first two, since the harness refuses before writing. The third
writes the file back unchanged. The third runs one gate twice per harness, and each harness
writes its own log for it, reporting that the gate did not fire.

Run from ``engine/`` with ``uv run python scripts/check_harness_exits.py``. Writes its result to
``engine/logs/``.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

ENGINE = Path(__file__).resolve().parents[1]
LOG_DIR = ENGINE / "logs"

ABSENT_ANCHOR = "an anchor no source file in this engine contains\n"
REPEATED_ANCHOR = "\n\n"


def load(script: Path) -> ModuleType:
   spec = importlib.util.spec_from_file_location(script.stem, script)
   assert spec is not None and spec.loader is not None
   module = importlib.util.module_from_spec(spec)
   spec.loader.exec_module(module)

   return module


def first_anchor(harness: ModuleType, mutation: dict[str, Any]) -> str:
   if "edits" in mutation:
      return str(mutation["edits"][0][1])

   if "find" in mutation:
      return str(mutation["find"])

   return str(harness.THREAD_CURSOR_FROM_END)


def with_anchor(
   harness: ModuleType, mutation: dict[str, Any], find: str, replace: str
) -> dict[str, Any]:
   altered = dict(mutation)

   if "edits" in mutation:
      relative = mutation["edits"][0][0]
      altered["edits"] = [(relative, find, replace)]
   elif "find" in mutation:
      altered["find"] = find
      altered["replace"] = replace
   else:
      altered["transform"] = harness.replace_text(find, replace)

   return altered


def outcome_of(main: Callable[[], int]) -> dict[str, Any]:
   quiet = io.StringIO()

   try:
      with contextlib.redirect_stdout(quiet):
         return {"exit": main(), "anchor_refused": False}
   except SystemExit as stop:
      message = stop.code if isinstance(stop.code, str) else ""
      code = 1 if message else int(stop.code or 0)
      anchor_refused = "expected exactly once" in message

      return {"exit": code, "anchor_refused": anchor_refused}


def control_held(control: str, outcome: dict[str, Any]) -> bool:
   exited_nonzero = outcome["exit"] != 0
   must_refuse_the_anchor = control != "gate_did_not_fire"

   if must_refuse_the_anchor:
      return exited_nonzero and bool(outcome["anchor_refused"])

   return exited_nonzero


def controls_for(script: Path) -> dict[str, dict[str, Any]]:
   harness = load(script)
   original_mutations = harness.MUTATIONS
   first = original_mutations[0]
   anchor = first_anchor(harness, first)

   altered_by_control = {
      "missing_anchor": with_anchor(harness, first, ABSENT_ANCHOR, ABSENT_ANCHOR),
      "ambiguous_anchor": with_anchor(harness, first, REPEATED_ANCHOR, REPEATED_ANCHOR),
      "gate_did_not_fire": with_anchor(harness, first, anchor, anchor),
   }

   outcomes = {}

   try:
      for control, altered in altered_by_control.items():
         harness.MUTATIONS = [altered]
         outcome = outcome_of(harness.main)
         outcome["held"] = control_held(control, outcome)
         outcomes[control] = outcome
   finally:
      harness.MUTATIONS = original_mutations

   return outcomes


def main() -> int:
   results = {}

   for script in sorted((ENGINE / "scripts").glob("verify_*_gates.py")):
      results[script.name] = controls_for(script)

   every_control_held = bool(results) and all(
      outcome["held"] for outcomes in results.values() for outcome in outcomes.values()
   )

   LOG_DIR.mkdir(parents=True, exist_ok=True)
   stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
   log_path = LOG_DIR / f"harness-exits-{stamp}.json"
   log_path.write_text(
      json.dumps({"every_control_held": every_control_held, "harnesses": results}, indent=2) + "\n",
      encoding="utf-8",
   )

   for name, outcomes in results.items():
      held_all = all(outcome["held"] for outcome in outcomes.values())
      status = "every control held" if held_all else "A CONTROL DID NOT HOLD"
      exits = {control: outcome["exit"] for control, outcome in outcomes.items()}
      print(f"{status}: {name}  {exits}")

   print(f"log written to {log_path}")

   return 0 if every_control_held else 1


if __name__ == "__main__":
   raise SystemExit(main())
