"""Put up a close friends note, then delete it. Writes.

Live requests: 3, the notes tray and two writes. A new note replaces the account's current one,
so the cycle stops when the tray already holds a note of the account's own. The text comes from
`IG_NOTE_TEXT` in `.env`.

   uv run python docs/demo/note_cycle.py
"""

from __future__ import annotations

import argparse
import sys

from _common import Demo, build_parser, line, preview, run, yes_no


def tour(demo: Demo, arguments: argparse.Namespace) -> None:
   text = demo.write_text("IG_NOTE_TEXT")

   demo.tour.section(
      "Note cycle",
      "client.direct.notes()",
      f"note = client.direct.set_note({preview(text)}, audience=NoteAudience.CLOSE_FRIENDS)",
      "client.direct.delete_note(note.id)",
   )

   with demo.client() as client:
      own_ids = {client.session.ds_user_id, client.session.actor_id}
      has_own_note = any(note.author_id in own_ids for note in client.direct.notes())

      if has_own_note:
         line("a note of the account's own is up and would be replaced, so the cycle stops")
         return

      note = client.direct.set_note(text)
      line(f"Note {note.id} for {note.audience.name}, emoji only {yes_no(note.is_emoji_only)}")

      client.direct.delete_note(note.id)
      line("deleted")
      demo.report["note_cycle"] = True


if __name__ == "__main__":
   parser = build_parser("Set a note, then delete it.")

   sys.exit(run("note-cycle", parser, tour))
