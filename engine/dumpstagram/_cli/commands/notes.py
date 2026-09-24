"""The note command: list the tray, set the viewer's note, delete it."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import TextIO

from dumpstagram._cli.commands.common import (
   ClientFactory,
   Subcommands,
   add_request_options,
   emit,
   resolve_session_path,
)
from dumpstagram._cli.exits import EXIT_OK
from dumpstagram._cli.render.notes import describe_note, render_notes
from dumpstagram.models import (
   NoteAudience,
)

__all__ = [
   "NOTE_AUDIENCES",
   "add_note_parser",
   "note_id",
   "run_note_list",
   "run_note_write",
]


def note_id(value: str) -> str:
   is_all_digits = value.isascii() and value.isdigit()

   if not is_all_digits:
      raise argparse.ArgumentTypeError("a note is named by its tray item id, digits only")

   return value


NOTE_AUDIENCES = {
   "close-friends": NoteAudience.CLOSE_FRIENDS,
   "mutual-follows": NoteAudience.MUTUAL_FOLLOWS,
}
"""The audiences the web composer offers, by the name the command line takes."""


def run_note_list(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_read = client.session.fb_dtsg
   viewer_id = client.session.ds_user_id

   try:
      notes = client.notes()

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_read
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   own_notes = [note for note in notes if note.author_id == viewer_id]

   payload = {
      "command": "note list",
      "note_count": len(notes),
      "own_note_id": own_notes[0].id if own_notes else None,
      "notes": [describe_note(note, viewer_id=viewer_id) for note in notes],
   }

   emit(payload, render_notes(notes, viewer_id=viewer_id), as_json=arguments.json, stream=stdout)

   return EXIT_OK


def run_note_write(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_write = client.session.fb_dtsg
   actor_id_before_the_write = client.session.actor_id
   viewer_id = client.session.ds_user_id

   try:
      if arguments.note_action == "set":
         created = client.set_note(arguments.text, audience=NOTE_AUDIENCES[arguments.audience])
         payload: dict[str, object] = {
            "command": "note set",
            "note": describe_note(created, viewer_id=viewer_id),
         }
         text = f"set note {created.id}  [{created.audience.name.lower()}]"
      else:
         client.delete_note(arguments.note_id)
         payload = {"command": "note delete", "note_id": arguments.note_id, "deleted": True}
         text = f"deleted note {arguments.note_id}"

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_write
      harvested_the_actor_id = client.session.actor_id != actor_id_before_the_write
      harvested_anything = harvested_a_new_token or harvested_the_actor_id
      may_write_back = not arguments.no_session_writeback

      if harvested_anything and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   emit(payload, text, as_json=arguments.json, stream=stdout)

   return EXIT_OK


def add_note_parser(commands: Subcommands) -> None:
   note = commands.add_parser(
      "note",
      help="read the notes tray, set the viewer's note, or delete it",
      description=(
         "list reads the whole tray, one live request, and marks the viewer's own note. set and "
         "delete write to the account, one write each, sent once and never retried."
      ),
   )
   note_actions = note.add_subparsers(dest="note_action", required=True)
   note_list = note_actions.add_parser("list", help="read the whole notes tray, one live request")
   note_list.add_argument(
      "--user-agent",
      metavar="STRING",
      help="override the user agent every request claims to be",
   )
   note_list.add_argument(
      "--no-session-writeback",
      action="store_true",
      help="do not save tokens harvested during this run back to the session file",
   )

   note_set = note_actions.add_parser(
      "set",
      help="set the viewer's note, one write, sent once and never retried",
      description=(
         "Writes to the account: sets the viewer's note to TEXT for the named audience, "
         "replacing any note already up, a song note included. Prints the new note's id, which "
         "delete takes. If the outcome is unknown, read dumpsta note list before sending again."
      ),
   )
   note_set.add_argument("text", metavar="TEXT", help="the note, as it should appear")
   note_set.add_argument(
      "--audience",
      required=True,
      choices=sorted(NOTE_AUDIENCES),
      help="who sees the note: close-friends, or mutual-follows for followers followed back",
   )
   add_request_options(note_set)

   note_delete = note_actions.add_parser(
      "delete",
      help="delete the viewer's note, one write, sent once and never retried",
      description=(
         "Writes to the account: deletes the note whose tray item id is NOTE_ID. If the outcome "
         "is unknown, read dumpsta note list: a note no longer listed is gone."
      ),
   )
   note_delete.add_argument(
      "note_id", metavar="NOTE_ID", type=note_id, help="the note's tray item id, digits only"
   )
   add_request_options(note_delete)
