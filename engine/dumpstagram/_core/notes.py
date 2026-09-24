"""The notes tray, read once, asynchronously.

Both public surfaces call this. Nothing here knows the upstream speaks GraphQL: the adapter in
`_private/web/` builds the request and maps the answer.

A browser reads the tray as one of the ten queries an inbox page load sends together, beside
the inbox document, the page's common companions and its cookie sync tail. The engine does not
model the inbox load's direct block yet, so it sends the tray query alone, which is a recorded
departure in `engine/docs/web-request-contract.md` rather than a setting, because there is no
parity route for a setting to choose.

Setting and deleting a note are writes, and they belong in `_core/writes/`.
"""

from __future__ import annotations

from collections.abc import Iterable

from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse.notes import parse_inbox_tray
from dumpstagram._private.web.requests.notes import build_inbox_tray_request
from dumpstagram.models import Note
from dumpstagram.session import Session

__all__ = ["find_own_note", "read_notes"]


async def read_notes(
   sender: PacedSender,
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> tuple[Note, ...]:
   """Read the whole notes tray and return it typed, in the tray's order.

   One live request when the session already carries usable tokens, two when it has to
   bootstrap first. The tray is unpaged, so there is no cursor to pass.
   """

   async def attempt() -> tuple[Note, ...]:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_inbox_tray_request(session, user_agent=user_agent)
      response = await sender.send(request)

      return parse_inbox_tray(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


def find_own_note(notes: Iterable[Note], viewer_id: str) -> Note | None:
   """The viewer's own note, or ``None`` when the viewer has none in the tray.

   ``viewer_id`` is the session's ``ds_user_id``. The tray names a note's author by the
   numeric Instagram id, which is that cookie's value, and never by the Facebook-side id a
   note create sends as ``actor_id``, so the two must not be swapped.
   """

   for note in notes:
      is_the_viewers = note.author_id == viewer_id

      if is_the_viewers:
         return note

   return None
