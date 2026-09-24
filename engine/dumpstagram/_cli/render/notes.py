"""The notes tray, the viewer's own note marked, in both output forms."""

from __future__ import annotations

from typing import Any

from dumpstagram.models import (
   Note,
)

__all__ = [
   "describe_note",
   "render_notes",
]


def describe_note(note: Note, *, viewer_id: str) -> dict[str, Any]:
   """The JSON form of one note. Every key here is part of the CLI's contract."""

   return {
      "id": note.id,
      "author_id": note.author_id,
      "author_username": note.author_username,
      "is_own": note.author_id == viewer_id,
      "text": note.text,
      "audience": note.audience.name.lower(),
      "created_at": note.created_at.isoformat(),
      "is_emoji_only": note.is_emoji_only,
   }


def render_notes(notes: tuple[Note, ...], *, viewer_id: str) -> str:
   """The human form: one line per note, the viewer's own marked, then a count."""

   lines = []

   for note in notes:
      marker = "*" if note.author_id == viewer_id else " "
      author = note.author_username or note.author_id
      audience = note.audience.name.lower()
      lines.append(f"{marker} {note.id}  {author}  [{audience}]  {note.text}")

   has_own_note = any(note.author_id == viewer_id for note in notes)
   own_summary = "your note is marked *" if has_own_note else "you have no note"
   lines.append(f"{len(notes)} notes, {own_summary}")

   return "\n".join(lines)
