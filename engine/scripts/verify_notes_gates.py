"""Break the notes tray read, watch each of its gates go red, restore.

Same harness and same rule as ``verify_cookie_sync_gates.py``: one mutation per line below,
only the gate that should catch it is run, and every file is restored from an in-memory copy in
a ``finally`` so an interrupted run cannot leave a mutation behind.

The Step 14 table in ``engine/docs/build-plan.md`` also has rows for the note create and delete.
Those capabilities do not exist yet, so their rows are not here.

Run from ``engine/`` with ``uv run python scripts/verify_notes_gates.py``. Writes its result to
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


PARSE = "dumpstagram/_private/web/parse.py"
REQUESTS = "dumpstagram/_private/web/requests.py"
NOTES = "dumpstagram/_core/notes.py"
MODELS = "dumpstagram/models/notes.py"
CLI = "dumpstagram/_cli/main.py"
RENDER = "dumpstagram/_cli/render.py"
GATES = "tests/test_notes.py"
CLI_GATES = "tests/test_cli.py"


def gate(name: str) -> str:
   return f"{GATES}::{name}"


MUTATIONS: list[dict[str, object]] = [
   {
      "gate": gate("test_the_item_maps_into_note_field_by_field"),
      "defect": "the text is read from the wrong key",
      "edits": [
         (
            PARSE,
            'text=_required_string(note, "text", note_path),',
            'text=_required_string(note, "author_id", note_path),',
         )
      ],
   },
   {
      "gate": gate("test_the_item_maps_into_note_field_by_field"),
      "defect": "created_at is read as milliseconds",
      "edits": [
         (
            PARSE,
            "created_at=datetime.fromtimestamp(created_at, tz=UTC),",
            "created_at=datetime.fromtimestamp(created_at / MILLISECONDS_PER_SECOND, tz=UTC),",
         )
      ],
   },
   {
      "gate": gate("test_the_audience_numbers_are_the_web_clients_own"),
      "defect": "the two audiences are swapped",
      "edits": [
         (
            MODELS,
            "   MUTUAL_FOLLOWS = 0\n   CLOSE_FRIENDS = 1\n",
            "   MUTUAL_FOLLOWS = 1\n   CLOSE_FRIENDS = 0\n",
         )
      ],
   },
   {
      "gate": gate("test_an_undeclared_audience_is_a_schema_change"),
      "defect": "an undeclared audience falls back to the default one",
      "edits": [
         (
            PARSE,
            "      return NoteAudience(raw)\n",
            "      return NoteAudience(raw) if raw in (0, 1, 2) else NoteAudience.MUTUAL_FOLLOWS\n",
         )
      ],
   },
   {
      "gate": gate("test_a_cursor_beside_the_items_is_a_schema_change"),
      "defect": "a pagination key beside the items is ignored",
      "edits": [
         (
            PARSE,
            "   pagination_keys = sorted(TRAY_PAGINATION_KEYS & tray.keys())\n",
            "   pagination_keys: list[str] = []\n",
         )
      ],
   },
   {
      "gate": gate("test_a_tray_item_that_is_not_a_note_is_a_schema_change"),
      "defect": "an item of another kind is mapped as a note",
      "edits": [(PARSE, "   if item_type != NOTE_ITEM_TYPE:\n", "   if item_type is None:\n")],
   },
   {
      "gate": gate("test_the_author_username_is_only_taken_from_the_author"),
      "defect": "the first pictured user is taken as the author",
      "edits": [
         (
            PARSE,
            'is_the_author = _required_string(pog_user, "id", user_path) == author_id',
            "is_the_author = True",
         )
      ],
   },
   {
      "gate": gate("test_the_own_note_is_the_one_authored_by_the_viewer"),
      "defect": "the own note is looked up by the item id instead of the author id",
      "edits": [
         (
            NOTES,
            "is_the_viewers = note.author_id == viewer_id",
            "is_the_viewers = note.id == viewer_id",
         )
      ],
   },
   {
      "gate": gate("test_a_tray_without_the_viewers_note_yields_none"),
      "defect": "the lookup returns the first item when the viewer has no note",
      "edits": [
         (
            NOTES,
            "      if is_the_viewers:\n         return note\n\n   return None\n",
            "      if is_the_viewers:\n         return note\n\n   return next(iter(notes), None)\n",
         )
      ],
   },
   {
      "gate": gate("test_the_tray_read_sends_the_request_the_inbox_sends"),
      "defect": "the tray query carries the home page as its referer",
      "edits": [
         (
            REQUESTS,
            "      {},\n      referer=BOOTSTRAP_URL,\n",
            '      {},\n      referer=f"{ORIGIN}/",\n',
         )
      ],
   },
   {
      "gate": gate("test_the_tray_read_sends_the_request_the_inbox_sends"),
      "defect": "the tray query carries a variable the inbox never sends",
      "edits": [
         (REQUESTS, "      INBOX_TRAY,\n      {},\n", '      INBOX_TRAY,\n      {"first": 20},\n')
      ],
   },
   {
      "gate": gate("test_the_tray_read_sends_the_request_the_inbox_sends"),
      "defect": "a request the engine does not model goes out beside the tray query",
      "edits": [
         (
            NOTES,
            "      if not session.fb_dtsg:\n         await bootstrap(",
            "      if True:\n         await bootstrap(",
         )
      ],
   },
   {
      "gate": f"{CLI_GATES}::test_the_note_list_marks_the_note_authored_by_the_viewer",
      "defect": "the CLI names the own note by the item id",
      "edits": [
         (
            CLI,
            "own_notes = [note for note in notes if note.author_id == viewer_id]",
            "own_notes = [note for note in notes if note.id == viewer_id]",
         )
      ],
   },
   {
      "gate": f"{CLI_GATES}::test_the_note_list_marks_the_note_authored_by_the_viewer",
      "defect": "the JSON form marks the own note by the item id",
      "edits": [
         (
            RENDER,
            '"is_own": note.author_id == viewer_id,',
            '"is_own": note.id == viewer_id,',
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
   log_path = LOG_DIR / f"mutation-notes-{stamp}.json"
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
