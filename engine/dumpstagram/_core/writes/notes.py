"""Set and delete the viewer's own note, each sent once through ``_core/writing.py``.

Both set a state rather than append one. A set replaces whatever note the viewer has up, so a
repeat after :class:`~dumpstagram.errors.OutcomeUnknown` converges on one note with the same
text, INFERENCE from a set observed replacing an existing note. The notes tray is the read that
reconciles either write, and the engine still never sends one again on its own.

The create names the account by its Facebook-side ``actor_id``, which only a bootstrapped page
carries. A session loaded from a file saved before that id was harvested has page tokens but no
``actor_id``, so it bootstraps once first rather than failing.
"""

from __future__ import annotations

from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.writing import send_write
from dumpstagram._private.transport import WriteRequest
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.parse import parse_created_note, read_note_delete_answer
from dumpstagram._private.web.requests import (
   build_create_note_request,
   build_delete_note_request,
   is_a_note_id,
)
from dumpstagram.errors import UpstreamRejected
from dumpstagram.models import Note, NoteAudience
from dumpstagram.session import Session

__all__ = ["delete_note", "set_note"]

AUDIENCE_NOT_APPLIED = "note_audience_did_not_follow"
"""The code raised when the created note carries an audience other than the one asked for."""


async def set_note(
   sender: PacedSender,
   session: Session,
   text: str,
   *,
   audience: NoteAudience,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Note:
   """Set the viewer's note to ``text`` for ``audience`` and return the created note.

   One write, and one bootstrap first when the session carries no page token or no
   ``actor_id``. Empty text raises :class:`ValueError` before anything is built.
   """

   if not text.strip():
      raise ValueError("a note needs text")

   lacks_page_tokens = not session.fb_dtsg or not session.actor_id

   if lacks_page_tokens:
      await bootstrap(sender, session, user_agent=user_agent)

   request = build_create_note_request(
      session,
      text,
      int(audience),
      client_mutation_id=str(sender.pacer.next_write_number()),
      user_agent=user_agent,
   )
   payload = await send_write(sender, session, WriteRequest(request, "set_note"))

   created = parse_created_note(payload)
   _require_the_audience(created, wanted=audience)

   return created


async def delete_note(
   sender: PacedSender,
   session: Session,
   note_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> None:
   """Delete the note whose tray item id is ``note_id``. One write, and one bootstrap first
   when the session carries no page token."""

   if not is_a_note_id(note_id):
      raise ValueError(f"{note_id!r} is not a note id, which is digits only")

   if not session.fb_dtsg:
      await bootstrap(sender, session, user_agent=user_agent)

   request = build_delete_note_request(session, note_id, user_agent=user_agent)
   payload = await send_write(sender, session, WriteRequest(request, "delete_note"))

   read_note_delete_answer(payload)


def _require_the_audience(created: Note, *, wanted: NoteAudience) -> None:
   """Raise when the upstream answered without an error but made the note for someone else.

   Never observed. It is raised rather than ignored because a caller who asked for close
   friends and was told nothing would believe a wider audience could not see the note.
   """

   if created.audience is not wanted:
      raise UpstreamRejected(
         f"the note was created for audience {int(created.audience)} after a write asking for "
         f"{int(wanted)}",
         code=AUDIENCE_NOT_APPLIED,
      )
