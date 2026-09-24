"""Break the notes tray read, set_note and delete_note, watch each gate go red, restore.

Same harness and same rule as ``verify_cookie_sync_gates.py``: one mutation per line below,
only the gate that should catch it is run, and every file is restored from an in-memory copy in
a ``finally`` so an interrupted run cannot leave a mutation behind.

The Step 14 table in ``engine/docs/build-plan.md`` is covered row by row, the tray read's rows
first and the create and delete rows after them, with the harvest of the Facebook-side id and
its place in the session file, which the create depends on.

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


COMMANDS_NOTES = "dumpstagram/_cli/commands/notes.py"
PARSE_NOTES = "dumpstagram/_private/web/parse/notes.py"
REQUESTS_NOTES = "dumpstagram/_private/web/requests/notes.py"
NOTES = "dumpstagram/_core/notes.py"
MODELS = "dumpstagram/models/notes.py"
CLI = "dumpstagram/_cli/main.py"
RENDER_NOTES = "dumpstagram/_cli/render/notes.py"
WRITES = "dumpstagram/_core/writes/notes.py"
BOOTSTRAP = "dumpstagram/_private/web/bootstrap.py"
SESSION = "dumpstagram/session.py"
FACADE = "dumpstagram/aio.py"
DIRECT_NAMESPACE = "dumpstagram/namespaces/direct.py"
GATES = "tests/test_notes.py"
CLI_GATES = "tests/test_cli.py"
SESSION_GATES = "tests/test_session.py"

SEND_SET = '   payload = await send_write(sender, session, WriteRequest(request, "set_note"))\n'
SEND_DELETE = (
   '   payload = await send_write(sender, session, WriteRequest(request, "delete_note"))\n'
)
WRITING_IMPORT = "from dumpstagram._core.writing import send_write\n"
CLASSIFY_IMPORT = "from dumpstagram._private.web.classify import classify\n"
DELETE_ROOT_READ = '   _required(data, DELETE_NOTE_ROOT, "data")\n'

PARSE_COMMON_IMPORT = "from dumpstagram._private.web.parse.common import (\n"
BOOTSTRAP_IMPORT = (
   "from dumpstagram._private.web.bootstrap import BOOTSTRAP_URL, DEFAULT_USER_AGENT\n"
)
BOOTSTRAP_IMPORT_WITH_ORIGIN = (
   "from dumpstagram._private.web.bootstrap import BOOTSTRAP_URL, DEFAULT_USER_AGENT, ORIGIN\n"
)


def gate(name: str) -> str:
   return f"{GATES}::{name}"


MUTATIONS: list[dict[str, object]] = [
   {
      "gate": gate("test_the_item_maps_into_note_field_by_field"),
      "defect": "the text is read from the wrong key",
      "edits": [
         (
            PARSE_NOTES,
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
            PARSE_NOTES,
            "created_at=datetime.fromtimestamp(created_at, tz=UTC),",
            "created_at=datetime.fromtimestamp(created_at / MILLISECONDS_PER_SECOND, tz=UTC),",
         ),
         (PARSE_NOTES, PARSE_COMMON_IMPORT, PARSE_COMMON_IMPORT + "   MILLISECONDS_PER_SECOND,\n"),
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
            PARSE_NOTES,
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
            PARSE_NOTES,
            "   pagination_keys = sorted(TRAY_PAGINATION_KEYS & tray.keys())\n",
            "   pagination_keys: list[str] = []\n",
         )
      ],
   },
   {
      "gate": gate("test_a_tray_item_that_is_not_a_note_is_a_schema_change"),
      "defect": "an item of another kind is mapped as a note",
      "edits": [
         (PARSE_NOTES, "   if item_type != NOTE_ITEM_TYPE:\n", "   if item_type is None:\n")
      ],
   },
   {
      "gate": gate("test_the_author_username_is_only_taken_from_the_author"),
      "defect": "the first pictured user is taken as the author",
      "edits": [
         (
            PARSE_NOTES,
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
            REQUESTS_NOTES,
            "      {},\n      referer=BOOTSTRAP_URL,\n",
            '      {},\n      referer=f"{ORIGIN}/",\n',
         ),
         (REQUESTS_NOTES, BOOTSTRAP_IMPORT, BOOTSTRAP_IMPORT_WITH_ORIGIN),
      ],
   },
   {
      "gate": gate("test_the_tray_read_sends_the_request_the_inbox_sends"),
      "defect": "the tray query carries a variable the inbox never sends",
      "edits": [
         (
            REQUESTS_NOTES,
            "      INBOX_TRAY,\n      {},\n",
            '      INBOX_TRAY,\n      {"first": 20},\n',
         )
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
            COMMANDS_NOTES,
            "own_notes = [note for note in notes if note.author_id == viewer_id]",
            "own_notes = [note for note in notes if note.id == viewer_id]",
         )
      ],
   },
   {
      "gate": f"{CLI_GATES}::test_the_note_list_marks_the_note_authored_by_the_viewer",
      "defect": "the CLI looks for the own note under the Facebook-side actor_id",
      "edits": [
         (
            COMMANDS_NOTES,
            "   token_before_the_read = client.session.fb_dtsg\n"
            "   viewer_id = client.session.ds_user_id\n",
            "   token_before_the_read = client.session.fb_dtsg\n"
            '   viewer_id = client.session.actor_id or ""\n',
         )
      ],
   },
   {
      "gate": f"{CLI_GATES}::test_the_note_list_marks_the_note_authored_by_the_viewer",
      "defect": "the JSON form marks the own note by the item id",
      "edits": [
         (
            RENDER_NOTES,
            '"is_own": note.author_id == viewer_id,',
            '"is_own": note.id == viewer_id,',
         )
      ],
   },
   {
      "gate": gate("test_the_created_item_maps_into_note_field_by_field"),
      "defect": "the created note's text is read from the wrong key",
      "edits": [
         (
            PARSE_NOTES,
            'text=_required_string(note, "text", note_path),',
            'text=_required_string(note, "author_id", note_path),',
         )
      ],
   },
   {
      "gate": gate("test_the_created_item_maps_into_note_field_by_field"),
      "defect": "the created note is read with the pictured user's id as its author",
      "edits": [
         (
            PARSE_NOTES,
            '   author_id = _required_string(note, "author_id", note_path)\n',
            '   author_id = _required_string(item["pog_info"]["pog_users"][0], "username", "p")\n',
         )
      ],
   },
   {
      "gate": gate("test_the_create_sends_actor_id_never_ds_user_id"),
      "defect": "the create sends ds_user_id as actor_id",
      "edits": [
         (REQUESTS_NOTES, '"actor_id": session.actor_id,', '"actor_id": session.ds_user_id,'),
      ],
   },
   {
      "gate": gate("test_the_create_sends_actor_id_never_ds_user_id"),
      "defect": "the create ignores the audience it was asked for",
      "edits": [(REQUESTS_NOTES, '"audience": audience,', '"audience": 0,')],
   },
   {
      "gate": gate("test_the_create_sends_actor_id_never_ds_user_id"),
      "defect": "the create carries the home page as its referer",
      "edits": [
         (
            REQUESTS_NOTES,
            "      },\n      referer=BOOTSTRAP_URL,\n      user_agent=user_agent,\n   )\n\n\n"
            "def is_a_note_id",
            '      },\n      referer=f"{ORIGIN}/",\n      user_agent=user_agent,\n   )\n\n\n'
            "def is_a_note_id",
         ),
         (REQUESTS_NOTES, BOOTSTRAP_IMPORT, BOOTSTRAP_IMPORT_WITH_ORIGIN),
      ],
   },
   {
      "gate": gate("test_the_bootstrap_reads_the_actor_id_and_never_falls_back_to_ds_user_id"),
      "defect": "a page without the actorID leaves ds_user_id in its place",
      "edits": [
         (
            BOOTSTRAP,
            "session.actor_id = tokens.actor_id or session.actor_id",
            "session.actor_id = tokens.actor_id or session.ds_user_id",
         )
      ],
   },
   {
      "gate": gate("test_the_bootstrap_reads_the_actor_id_and_never_falls_back_to_ds_user_id"),
      "defect": "the bootstrap never reads the actorID",
      "edits": [(BOOTSTRAP, "actor_id=_first_match(_ACTOR_ID, html),", "actor_id=None,")],
   },
   {
      "gate": gate("test_a_session_without_an_actor_id_bootstraps_before_the_create"),
      "defect": "a session with page tokens but no actor_id goes straight to the create",
      "edits": [
         (
            WRITES,
            "lacks_page_tokens = not session.fb_dtsg or not session.actor_id",
            "lacks_page_tokens = not session.fb_dtsg",
         )
      ],
   },
   {
      "gate": gate("test_a_page_without_the_actor_id_stops_the_create_before_it_is_sent"),
      "defect": "the create is built without an actor_id rather than refused",
      "edits": [(REQUESTS_NOTES, "   if not session.actor_id:\n", "   if False:\n")],
   },
   {
      "gate": gate("test_a_created_note_for_another_audience_raises"),
      "defect": "a note made for another audience is reported as done",
      "edits": [(WRITES, "   if created.audience is not wanted:\n", "   if False:\n")],
   },
   {
      "gate": gate("test_a_delete_answered_with_a_null_root_is_a_success"),
      "defect": "the delete's root field is tested for truthiness",
      "edits": [
         (
            PARSE_NOTES,
            DELETE_ROOT_READ,
            '   if not _required(data, DELETE_NOTE_ROOT, "data"):\n'
            '      raise SchemaChanged("the delete answered null", path="data")\n',
         )
      ],
   },
   {
      "gate": gate("test_a_delete_answer_without_its_root_field_is_a_schema_change"),
      "defect": "an answer without the root field is taken as a delete",
      "edits": [(PARSE_NOTES, DELETE_ROOT_READ, "   data.get(DELETE_NOTE_ROOT)\n")],
   },
   {
      "gate": gate("test_the_delete_sends_the_item_id"),
      "defect": "the delete sends the author's id",
      "edits": [
         (
            REQUESTS_NOTES,
            '{"inbox_tray_item_id": note_id},',
            '{"inbox_tray_item_id": session.ds_user_id},',
         )
      ],
   },
   {
      "gate": gate("test_the_delete_sends_the_item_id"),
      "defect": "the delete wraps its variable in an input object",
      "edits": [
         (
            REQUESTS_NOTES,
            '{"inbox_tray_item_id": note_id},',
            '{"input": {"inbox_tray_item_id": note_id}},',
         )
      ],
   },
   {
      "gate": gate("test_both_note_writes_depart_only_through_the_write_slot"),
      "defect": "the set is sent with sender.send rather than send_write",
      "edits": [
         (WRITES, WRITING_IMPORT, WRITING_IMPORT + CLASSIFY_IMPORT),
         (WRITES, SEND_SET, "   payload = classify(await sender.send(request))\n"),
      ],
   },
   {
      "gate": gate("test_both_note_writes_depart_only_through_the_write_slot"),
      "defect": "the delete is sent with sender.send rather than send_write",
      "edits": [
         (WRITES, WRITING_IMPORT, WRITING_IMPORT + CLASSIFY_IMPORT),
         (WRITES, SEND_DELETE, "   payload = classify(await sender.send(request))\n"),
      ],
   },
   {
      "gate": gate("test_an_error_envelope_on_a_set_raises_and_departs_once"),
      "defect": "the set is sent again after an error envelope",
      "edits": [
         (
            WRITES,
            SEND_SET,
            "   try:\n   " + SEND_SET + "   except UpstreamRejected:\n   " + SEND_SET,
         )
      ],
   },
   {
      "gate": gate("test_what_cannot_be_a_note_is_refused_before_anything_is_sent"),
      "defect": "empty text reaches the upstream",
      "edits": [(WRITES, "   if not text.strip():\n", "   if False:\n")],
   },
   {
      "gate": gate("test_what_cannot_be_a_note_is_refused_before_anything_is_sent"),
      "defect": "a note id that is not digits reaches the upstream",
      "edits": [(WRITES, "   if not is_a_note_id(note_id):\n", "   if False:\n")],
   },
   {
      "gate": gate("test_the_set_note_docstring_names_the_reconciling_read"),
      "defect": "the set_note docstring on client.direct stops naming the tray read",
      "edits": [
         (
            DIRECT_NAMESPACE,
            "Read :meth:`notes` first when the old one matters.",
            "Read the tray first.",
         ),
         (
            DIRECT_NAMESPACE,
            "To reconcile that, read :meth:`notes` and look for the viewer's own note",
            "To reconcile that, look for the viewer's own note",
         ),
      ],
   },
   {
      "gate": gate("test_the_set_note_docstring_names_the_reconciling_read"),
      "defect": "the flat set_note docstring stops naming the tray read",
      "edits": [
         (
            FACADE,
            "      read :meth:`notes` and look for the viewer's own note before deciding anything.",
            "      look for the viewer's own note before deciding anything.",
         ),
      ],
   },
   {
      "gate": gate("test_the_cli_sets_the_named_text_for_the_named_audience"),
      "defect": "the CLI sets every note for close friends whatever was named",
      "edits": [
         (
            COMMANDS_NOTES,
            "audience=NOTE_AUDIENCES[arguments.audience]",
            "audience=NoteAudience.CLOSE_FRIENDS",
         ),
      ],
   },
   {
      "gate": gate("test_the_cli_sets_the_named_text_for_the_named_audience"),
      "defect": "the CLI sends the audience name as the note text",
      "edits": [
         (COMMANDS_NOTES, "client.set_note(arguments.text,", "client.set_note(arguments.audience,")
      ],
   },
   {
      "gate": gate("test_the_cli_refuses_a_set_without_an_audience_before_opening_a_client"),
      "defect": "the CLI falls back to close friends when no audience is named",
      "edits": [
         (
            COMMANDS_NOTES,
            "      required=True,\n      choices=sorted(NOTE_AUDIENCES),\n",
            '      default="close-friends",\n      choices=sorted(NOTE_AUDIENCES),\n',
         )
      ],
   },
   {
      "gate": gate("test_the_cli_deletes_the_named_note"),
      "defect": "the CLI deletes by the viewer's id instead of the named note",
      "edits": [
         (COMMANDS_NOTES, "client.delete_note(arguments.note_id)", "client.delete_note(viewer_id)")
      ],
   },
   {
      "gate": gate("test_the_cli_refuses_a_note_id_that_is_not_digits_before_opening_a_client"),
      "defect": "the CLI accepts any string as a note id",
      "edits": [(COMMANDS_NOTES, "type=note_id, ", "")],
   },
   {
      "gate": f"{SESSION_GATES}::test_the_actor_id_survives_a_save_and_load",
      "defect": "the session file drops the actor_id",
      "edits": [(SESSION, '         "actor_id": self.actor_id,\n', "")],
   },
   {
      "gate": f"{SESSION_GATES}::test_a_file_saved_before_actor_id_existed_loads_with_none",
      "defect": "the loader demands the actor_id key",
      "edits": [(SESSION, 'actor_id=payload.get("actor_id"),', 'actor_id=payload["actor_id"],')],
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
