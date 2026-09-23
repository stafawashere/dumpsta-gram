"""Break the network guard in ``tests/conftest.py``, watch each of its gates go red, restore.

Same harness and same rule as ``verify_cookie_sync_gates.py``: one mutation per line below, only
the gate that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

A mutated guard lets its gate's connection through for real. Every gate reaches only for
192.0.2.1, which nothing answers, or for a name under ``.invalid``, so a red run here sends
nothing to Instagram.

Run from ``engine/`` with ``uv run python scripts/verify_network_guard_gates.py``. Writes its
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


CONFTEST = "tests/conftest.py"
GATES = "tests/test_network_guard.py"


def gate(name: str) -> str:
   return f"{GATES}::{name}"


MUTATIONS: list[dict[str, object]] = [
   {
      "gate": gate("test_both_engine_transports_are_refused_a_real_connection"),
      "defect": "the connect guard lets a non-loopback host through",
      "edits": [
         (
            CONFTEST,
            '      if not is_loopback_host(host):\n         self.refuse(f"connect to',
            '      if False:\n         self.refuse(f"connect to',
         )
      ],
   },
   {
      "gate": gate("test_both_engine_transports_are_refused_a_real_connection"),
      "defect": "the guard is built and never installed",
      "edits": [
         (
            CONFTEST,
            "      guard.install(monkeypatch)\n",
            "",
         )
      ],
   },
   {
      "gate": gate("test_a_name_lookup_is_refused"),
      "defect": "a name lookup goes out, which offline is where a request dies quietly",
      "edits": [
         (
            CONFTEST,
            "      if not may_resolve:\n",
            "      if False:\n",
         )
      ],
   },
   {
      "gate": gate("test_a_refusal_the_test_swallows_still_fails_it"),
      "defect": "a refusal the code under test swallows leaves the test green",
      "edits": [
         (
            CONFTEST,
            "   if left_behind:\n",
            "   if False:\n",
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
   log_path = LOG_DIR / f"mutation-network-guard-{stamp}.json"
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
