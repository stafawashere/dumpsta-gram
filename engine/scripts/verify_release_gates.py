"""Break the source once per gate that 17.8 of the build plan added, watch each go red, restore.

The gates are the Phase 5 entry items on the engine's side: the import boundary, the wheel and
sdist contents, ``py.typed`` read by a consumer, the clean-environment consumer run, the
credential absence scan, the scripts the shipped gates load, a worker thread draining while the
loop thread is busy, the input scan and the version one session file. Same harness and same rule
as ``verify_cookie_sync_gates.py``: one mutation per line below, only the gate that should catch
it is run, and every file is restored from an in-memory copy in a ``finally`` so an interrupted
run cannot leave a mutation behind.

Several mutations edit ``pyproject.toml``, because what ships is decided there. Two of them put
``state/session.json`` into an artifact on purpose, so the credential scan has something real to
find. Those artifacts are built into a temporary directory the gate removes when it finishes.

Run from ``engine/`` with ``uv run python scripts/verify_release_gates.py``. Writes its result to
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


PYPROJECT = "pyproject.toml"
PARSE = "dumpstagram/_private/web/parse.py"
EXITS = "dumpstagram/_cli/exits.py"
CLIENT = "dumpstagram/client.py"
LISTENER = "dumpstagram/listener.py"
COOKIE_SOURCES = "dumpstagram/_cli/cookie_sources.py"
SESSION = "dumpstagram/session.py"

BOUNDARY = "tests/test_import_boundary.py"
DISTRIBUTION = "tests/test_distribution.py"
BLOCKING = "tests/test_blocking_input.py"
SESSION_GATES = "tests/test_session.py"
EVENTS = "tests/test_events.py"
SURFACE = "tests/test_public_surface.py"

WHEEL_PACKAGES = 'packages = ["dumpstagram"]\n'
EXITS_TAIL = "         return EXIT_BY_ERROR[ancestor]\n\n   return 1\n"
LISTENER_DRAIN = "      self._refuse_with_a_handler()\n\n      return self._buffer.drain()\n"
LISTENER_WAIT = "      return self._buffer.wait(timeout)\n"


def gate(module: str, name: str) -> str:
   return f"{module}::{name}"


MUTATIONS: list[dict[str, object]] = [
   {
      "gate": gate(BOUNDARY, "test_private_never_imports_core"),
      "defect": "the response mapper reaches up into _core",
      "edits": [
         (
            PARSE,
            "from __future__ import annotations\n",
            "from __future__ import annotations\n\n"
            "from dumpstagram._core.redaction import redact\n",
         )
      ],
   },
   {
      "gate": gate(BOUNDARY, "test_nothing_inside_the_package_imports_its_public_root"),
      "defect": "a command line helper imports the package root inside a function",
      "edits": [
         (
            EXITS,
            EXITS_TAIL,
            EXITS_TAIL
            + "\n\ndef _root() -> object:\n   import dumpstagram\n\n   return dumpstagram\n",
         )
      ],
   },
   {
      "gate": gate(BOUNDARY, "test_only_the_assembly_imports_private_from_outside_core"),
      "defect": "the blocking facade imports the transport directly",
      "edits": [
         (
            CLIENT,
            "from dumpstagram._core.loop_thread import _LoopThread\n",
            "from dumpstagram._core.loop_thread import _LoopThread\n"
            "from dumpstagram._private.transport import Request\n",
         )
      ],
   },
   {
      "gate": gate(
         BOUNDARY, "test_the_public_surface_exposes_nothing_defined_behind_an_underscore"
      ),
      "defect": "the listener module re-exports the internal buffer",
      "edits": [
         (
            LISTENER,
            '__all__ = ["EventListener"]\n',
            '__all__ = ["EventListener", "EventBuffer"]\n',
         )
      ],
   },
   {
      "gate": gate(
         BOUNDARY, "test_the_public_surface_exposes_nothing_defined_behind_an_underscore"
      ),
      "defect": "a public signature returns the internal buffer",
      "edits": [
         (
            LISTENER,
            "   def drain(self) -> list[Event]:\n",
            "   def drain(self) -> EventBuffer:\n",
         )
      ],
   },
   {
      "gate": gate(DISTRIBUTION, "test_the_wheel_carries_the_package_and_nothing_else"),
      "defect": "the snapshot file is forced into the wheel",
      "edits": [
         (
            PYPROJECT,
            WHEEL_PACKAGES,
            WHEEL_PACKAGES + "\n[tool.hatch.build.targets.wheel.force-include]\n"
            '"tests/public_surface.txt" = "dumpstagram/public_surface.txt"\n',
         )
      ],
   },
   {
      "gate": gate(DISTRIBUTION, "test_the_wheel_carries_the_package_and_nothing_else"),
      "defect": "the models subpackage is left out of the wheel",
      "edits": [(PYPROJECT, WHEEL_PACKAGES, WHEEL_PACKAGES + 'exclude = ["dumpstagram/models"]\n')],
   },
   {
      "gate": gate(
         DISTRIBUTION, "test_the_wheel_carries_py_typed_and_a_consumer_type_checks_against_it"
      ),
      "defect": "the typing marker is left out of the wheel",
      "edits": [
         (PYPROJECT, WHEEL_PACKAGES, WHEEL_PACKAGES + 'exclude = ["dumpstagram/py.typed"]\n')
      ],
   },
   {
      "gate": gate(
         DISTRIBUTION,
         "test_a_consumer_outside_the_checkout_imports_constructs_and_runs_the_command",
      ),
      "defect": "the models subpackage is left out of the wheel",
      "edits": [(PYPROJECT, WHEEL_PACKAGES, WHEEL_PACKAGES + 'exclude = ["dumpstagram/models"]\n')],
   },
   {
      "gate": gate(
         DISTRIBUTION,
         "test_a_consumer_outside_the_checkout_imports_constructs_and_runs_the_command",
      ),
      "defect": "the console script points at a name the command line does not export",
      "edits": [
         (
            PYPROJECT,
            'dumpsta = "dumpstagram._cli:main"\n',
            'dumpsta = "dumpstagram._cli:missing"\n',
         )
      ],
   },
   {
      "gate": gate(DISTRIBUTION, "test_the_sdist_ships_nothing_the_repository_keeps_local"),
      "defect": "the whole docs directory goes into the sdist again",
      "edits": [(PYPROJECT, '   "docs/overview.md",\n', '   "docs",\n   "docs/overview.md",\n')],
   },
   {
      "gate": gate(DISTRIBUTION, "test_the_sdist_ships_nothing_the_repository_keeps_local"),
      "defect": "the oracle fixtures are no longer excluded from the sdist",
      "edits": [(PYPROJECT, 'exclude = ["tests/fixtures/thread_oracle"]\n', "")],
   },
   {
      "gate": gate(DISTRIBUTION, "test_every_script_a_shipped_gate_loads_is_in_the_sdist"),
      "defect": "the scripts directory is left out of the sdist",
      "edits": [(PYPROJECT, '   "tests",\n   "scripts",\n', '   "tests",\n')],
   },
   {
      "gate": gate(DISTRIBUTION, "test_no_credential_this_machine_holds_is_inside_either_archive"),
      "defect": "the saved session directory goes into the sdist",
      "edits": [(PYPROJECT, '   ".python-version",\n', '   ".python-version",\n   "state",\n')],
   },
   {
      "gate": gate(DISTRIBUTION, "test_no_credential_this_machine_holds_is_inside_either_archive"),
      "defect": "the saved session file is forced into the wheel",
      "edits": [
         (
            PYPROJECT,
            WHEEL_PACKAGES,
            WHEEL_PACKAGES + "\n[tool.hatch.build.targets.wheel.force-include]\n"
            '"state/session.json" = "dumpstagram/state.json"\n',
         )
      ],
   },
   {
      "gate": gate(EVENTS, "test_a_worker_thread_drains_and_waits_while_the_loop_thread_is_busy"),
      "defect": "drain hands its take to the loop thread and waits for it",
      "edits": [
         (
            LISTENER,
            LISTENER_DRAIN,
            "      self._refuse_with_a_handler()\n\n"
            "      assert self._loop is not None\n\n"
            "      return self._loop.run(\n"
            '         asyncio.sleep(0, self._buffer.drain()), operation="EventListener.drain"\n'
            "      )\n",
         )
      ],
   },
   {
      "gate": gate(EVENTS, "test_a_worker_thread_drains_and_waits_while_the_loop_thread_is_busy"),
      "defect": "wait_for_events checks in with the loop thread before it waits",
      "edits": [
         (
            LISTENER,
            LISTENER_WAIT,
            "      assert self._loop is not None\n"
            '      self._loop.run(asyncio.sleep(0), operation="EventListener.wait_for_events")\n\n'
            + LISTENER_WAIT,
         )
      ],
   },
   {
      "gate": gate(BLOCKING, "test_nothing_in_the_library_blocks_on_input"),
      "defect": "the cookie intake prompts for a missing value",
      "edits": [
         (
            COOKIE_SOURCES,
            "def session_from(source: Mapping[str, str]) -> Session:\n",
            "def _prompt() -> str:\n   return input()\n\n\n"
            "def session_from(source: Mapping[str, str]) -> Session:\n",
         )
      ],
   },
   {
      "gate": gate(BLOCKING, "test_nothing_in_the_library_blocks_on_input"),
      "defect": "the cookie intake imports getpass",
      "edits": [
         (
            COOKIE_SOURCES,
            "from collections.abc import Mapping\n",
            "import getpass\nfrom collections.abc import Mapping\n",
         )
      ],
   },
   {
      "gate": gate(SESSION_GATES, "test_a_version_one_file_written_out_in_full_still_loads"),
      "defect": "the session schema moves to version 2 with no migration",
      "edits": [(SESSION, "SCHEMA_VERSION = 1\n", "SCHEMA_VERSION = 2\n")],
   },
   {
      "gate": gate(SURFACE, "test_committed_snapshot_matches_the_package"),
      "defect": "the session schema moves to version 2 with no migration",
      "edits": [(SESSION, "SCHEMA_VERSION = 1\n", "SCHEMA_VERSION = 2\n")],
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
   log_path = LOG_DIR / f"mutation-release-{stamp}.json"
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
