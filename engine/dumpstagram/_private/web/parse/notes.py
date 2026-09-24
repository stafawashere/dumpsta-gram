"""Map the notes tray, and the answers to setting and deleting the viewer's note."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from dumpstagram._private.web.parse.common import (
   _object_at,
   _required,
   _required_flag,
   _required_integer,
   _required_string,
)
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import (
   Note,
   NoteAudience,
)

__all__ = [
   "CREATE_NOTE_ROOT",
   "DELETE_NOTE_ROOT",
   "INBOX_TRAY_PATH",
   "parse_created_note",
   "parse_inbox_tray",
   "parse_note",
   "read_note_delete_answer",
]

INBOX_TRAY_PATH = ("data", "response")
"""The path to the notes tray in an ``IGDInboxTrayQuery`` payload.

The operation's root field is ``xdt_get_inbox_tray_items``, and the query aliases it, so the
payload carries it under ``response``.
"""

CREATE_NOTE_ROOT = "xdt_create_inbox_tray_item"
"""The root field a note create answers under, carrying the item as ``inbox_tray_item``."""

DELETE_NOTE_ROOT = "xdt_delete_inbox_tray_item"
"""The root field a note delete answers under, null on every observed success."""

TRAY_PAGINATION_KEYS = frozenset(
   {"page_info", "cursor", "end_cursor", "has_next_page", "next_max_id", "max_id"}
)
"""Keys that would mean the tray had become paged.

None has been seen. Every measured tray was one flat list with no cursor anywhere, which is
why the read is one call. A tray that grew one would be returning a first page while the
engine reported the whole tray, so it raises rather than being ignored.
"""

NOTE_ITEM_TYPE = "note"


def _note_audience(note: dict[str, Any], path: str) -> NoteAudience:
   raw = _required_integer(note, "audience", path)

   try:
      return NoteAudience(raw)
   except ValueError as failure:
      raise SchemaChanged(
         f"{path}.audience holds {raw}, which no audience declares", path=f"{path}.audience"
      ) from failure


def _author_username(item: dict[str, Any], author_id: str, path: str) -> str | None:
   """The username on the tray's picture of the author, when that picture is the author.

   Every measured item carried one picture user whose id was the note's ``author_id``. A
   picture of anyone else is not the author, so it yields nothing rather than a wrong name.
   """

   pog_info = _required(item, "pog_info", path)
   pog_users = _required(pog_info, "pog_users", f"{path}.pog_info")

   if not isinstance(pog_users, list):
      raise SchemaChanged(
         f"{path}.pog_info.pog_users is not a list", path=f"{path}.pog_info.pog_users"
      )

   for index, pog_user in enumerate(pog_users):
      user_path = f"{path}.pog_info.pog_users[{index}]"
      is_the_author = _required_string(pog_user, "id", user_path) == author_id

      if is_the_author:
         return _required_string(pog_user, "username", user_path)

   return None


def parse_note(item: Any, path: str) -> Note:
   """One tray item, mapped field by field.

   ``created_at`` is whole seconds since the Unix epoch as a JSON number, the unit a post's
   ``taken_at`` uses and not the milliseconds string a message carries.

   What the upstream sends and this mapper drops, from the trays recorded on 2026-09-21 and
   2026-09-23:

   - ``note_style``, 0 or 1. Only 0 was produced by a plain text note, and 1 is a song note on
     INFERENCE, so the number has no measured meaning to model.
   - ``note_response_info``, which carries the song on a song note, and ``custom_theme``, a
     colour theme on three of thirteen items. Both belong to capabilities that do not exist.
   - ``pog_info.pog_style`` and the pictures' profile URLs and Facebook-side ids.
   """

   if not isinstance(item, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

   item_type = _required_string(item, "inbox_tray_item_type", path)

   if item_type != NOTE_ITEM_TYPE:
      raise SchemaChanged(
         f"{path}.inbox_tray_item_type is {item_type!r}, not a note",
         path=f"{path}.inbox_tray_item_type",
      )

   note_path = f"{path}.note_dict"
   note = _required(item, "note_dict", path)

   if not isinstance(note, dict):
      raise SchemaChanged(f"{note_path} is not an object", path=note_path)

   author_id = _required_string(note, "author_id", note_path)
   created_at = _required_integer(note, "created_at", note_path)

   return Note(
      id=_required_string(item, "inbox_tray_item_id", path),
      author_id=author_id,
      text=_required_string(note, "text", note_path),
      audience=_note_audience(note, note_path),
      created_at=datetime.fromtimestamp(created_at, tz=UTC),
      is_emoji_only=_required_flag(note, "is_emoji_only", note_path),
      author_username=_author_username(item, author_id, path),
   )


def parse_inbox_tray(payload: Any) -> tuple[Note, ...]:
   """One ``IGDInboxTrayQuery`` payload, mapped into the notes it carries, in the tray's order.

   The tray is the whole answer, one call with no cursor, so a pagination key appearing
   beside the items raises :class:`~dumpstagram.errors.SchemaChanged`: the engine would
   otherwise report a first page as the whole tray.

   Finding: `read-the-notes-tray-on-the-direct-inbox` in the knowledge base.
   """

   tray = _object_at(payload, INBOX_TRAY_PATH)
   tray_path = ".".join(INBOX_TRAY_PATH)

   pagination_keys = sorted(TRAY_PAGINATION_KEYS & tray.keys())

   if pagination_keys:
      raise SchemaChanged(
         f"{tray_path} carries {pagination_keys[0]}, so the tray is no longer one call",
         path=f"{tray_path}.{pagination_keys[0]}",
      )

   items = _required(tray, "inbox_tray_items", tray_path)

   if not isinstance(items, list):
      raise SchemaChanged(
         f"{tray_path}.inbox_tray_items is not a list", path=f"{tray_path}.inbox_tray_items"
      )

   return tuple(
      parse_note(item, f"{tray_path}.inbox_tray_items[{index}]") for index, item in enumerate(items)
   )


def parse_created_note(payload: Any) -> Note:
   """The note a create answered with, from ``data.xdt_create_inbox_tray_item.inbox_tray_item``.

   The item has the key set a tray item has, observed on the browser create of 2026-09-21 and
   the engine create of 2026-09-23, so it maps through :func:`parse_note`. An answer without
   it and without an ``errors`` array is a schema change rather than a quiet success.

   Finding: `set-my-own-note-on-the-direct-inbox` in the knowledge base.
   """

   item_path = ("data", CREATE_NOTE_ROOT, "inbox_tray_item")

   return parse_note(_object_at(payload, item_path), ".".join(item_path))


def read_note_delete_answer(payload: Any) -> None:
   """Accept a note delete's answer, whose root field is null on success.

   Three deletes answered ``data.xdt_delete_inbox_tray_item`` null with no error, and a tray
   read after each found the note gone, so null is the success and must not be tested for
   truthiness. A payload that lacks the root field altogether is a schema change.

   Finding: `delete-my-own-note-on-the-direct-inbox` in the knowledge base.
   """

   data = _object_at(payload, ("data",))
   _required(data, DELETE_NOTE_ROOT, "data")
