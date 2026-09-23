"""Break the session's fr field and the redaction it needs, watch each gate go red, restore.

Same harness and same rule as ``verify_parity_gates.py``: one mutation per gate, only the gate
that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

Run from ``engine/`` with ``uv run python scripts/verify_fr_session_gates.py``. Writes its
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


SESSION = "dumpstagram/session.py"
REDACTION = "dumpstagram/_core/redaction.py"
COOKIE_SOURCES = "dumpstagram/_cli/cookie_sources.py"
SESSION_GATES = "tests/test_session.py"
REDACTION_GATES = "tests/test_redaction.py"
CLI_GATES = "tests/test_cli.py"

QUOTED_KEY_PATTERN = """(['\\"]?\\s*[=:]\\s*)(['\\"]?)"""
BARE_KEY_PATTERN = """(\\s*[=:]\\s*)(['\\"]?)"""

MUTATIONS: list[dict[str, object]] = [
   {
      "gate": f"{SESSION_GATES}::test_round_trip_through_disk_preserves_every_field",
      "defect": "fr is saved and not loaded back",
      "edits": [(SESSION, '         fr=payload.get("fr"),\n', "")],
   },
   {
      "gate": f"{SESSION_GATES}::test_saved_format_keys_are_the_documented_set",
      "defect": "fr is never written to the session file",
      "edits": [(SESSION, '         "fr": self.fr,\n', "")],
   },
   {
      "gate": f"{SESSION_GATES}::test_a_file_saved_before_fr_existed_loads_with_none",
      "defect": "the loader demands the fr key",
      "edits": [(SESSION, 'fr=payload.get("fr"),', 'fr=payload["fr"],')],
   },
   {
      "gate": f"{SESSION_GATES}::test_repr_carries_no_credential_material",
      "defect": "the session representation prints fr",
      "edits": [
         (
            SESSION,
            'f"Session(ds_user_id={self.ds_user_id!r}, ',
            'f"Session(fr={self.fr!r}, ds_user_id={self.ds_user_id!r}, ',
         )
      ],
   },
   {
      "gate": f"{REDACTION_GATES}::test_redacts_the_fr_value",
      "defect": "fr is not a secret key",
      "edits": [(REDACTION, '   "fr",\n)', ")")],
   },
   {
      "gate": f"{REDACTION_GATES}::test_redacts_a_token_under_a_quoted_key",
      "defect": "the pattern requires the separator straight after the key",
      "edits": [(REDACTION, QUOTED_KEY_PATTERN, BARE_KEY_PATTERN)],
   },
   {
      "gate": (
         f"{CLI_GATES}::test_adopt_carries_fr_onto_the_session_and_never_into_the_cookie_jar"
      ),
      "defect": "IG_FR is dropped at intake",
      "edits": [(COOKIE_SOURCES, "      fr=source.get(FR_KEY) or None,\n", "")],
   },
   {
      "gate": (
         f"{CLI_GATES}::test_adopt_carries_fr_onto_the_session_and_never_into_the_cookie_jar"
      ),
      "defect": "IG_FR is sent as a cookie",
      "edits": [
         (
            COOKIE_SOURCES,
            'OPTIONAL_COOKIE_KEYS: Mapping[str, str] = {"IG_MID": "mid"}',
            'OPTIONAL_COOKIE_KEYS: Mapping[str, str] = {"IG_MID": "mid", "IG_FR": "fr"}',
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
   log_path = LOG_DIR / f"mutation-fr-session-{stamp}.json"
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
