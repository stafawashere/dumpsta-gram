"""The direct inbox as a browser opens it: the first page, the notes tray and the unread counts.

Both public surfaces call this. Nothing here knows the upstream speaks GraphQL: the readers in
``_core/inbox.py`` and ``_core/notes.py`` own the requests and the mapping.

Under :attr:`InboxRoute.PAGE` the three are read from one inbox page load, the action a browser
sends when the inbox opens, so a caller that shows all three pays for one load rather than one
load each (W87). Under :attr:`InboxRoute.QUERIES` each read's own queries go out in turn, as
they would through the three single reads.

Every one of the three answers is read, and a failure in any of them raises: a load that
returned the threads with an empty tray in place of one that failed would be a degraded answer
indistinguishable from a correct one.
"""

from __future__ import annotations

from dumpstagram._core.cookie_sync import CookieSync
from dumpstagram._core.inbox import (
   InboxPageAnswers,
   public_inbox_page,
   read_from_inbox_page,
   read_inbox_page,
   read_unread_counts,
   unread_counts_from_rows,
)
from dumpstagram._core.notes import read_notes
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse.direct import parse_inbox_page
from dumpstagram._private.web.parse.notes import parse_inbox_tray
from dumpstagram.behavior import InboxRoute
from dumpstagram.models import InboxLoad
from dumpstagram.session import Session

__all__ = ["read_inbox_load"]


def _inbox_load(answers: InboxPageAnswers) -> InboxLoad:
   return InboxLoad(
      threads=public_inbox_page(parse_inbox_page(classify(answers.listing))),
      notes=parse_inbox_tray(classify(answers.tray)),
      unread_counts=unread_counts_from_rows(answers.inbox_unread_rows, answers.pending_unread_rows),
   )


async def read_inbox_load(
   sender: PacedSender,
   session: Session,
   *,
   route: InboxRoute = InboxRoute.QUERIES,
   companions: bool = False,
   cookie_sync: CookieSync | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> InboxLoad:
   """Read the inbox's first page, the notes tray and the unread counts together.

   Under :attr:`InboxRoute.PAGE` one inbox page load, and ``companions`` and ``cookie_sync``
   apply to it. Under ``QUERIES`` four live requests, the listing, the tray and the two folders'
   rows, with no companions. ``QUERIES`` and no companions stay the defaults at this level so
   callers below the client keep the requests they had, and the client passes its behavior down.
   """

   if route is InboxRoute.PAGE:
      return await read_from_inbox_page(
         sender,
         session,
         _inbox_load,
         companions=companions,
         cookie_sync=cookie_sync,
         user_agent=user_agent,
         deadline=deadline,
      )

   threads = await read_inbox_page(
      sender, session, route=InboxRoute.QUERIES, user_agent=user_agent, deadline=deadline
   )
   notes = await read_notes(
      sender, session, route=InboxRoute.QUERIES, user_agent=user_agent, deadline=deadline
   )
   unread_counts = await read_unread_counts(
      sender, session, route=InboxRoute.QUERIES, user_agent=user_agent, deadline=deadline
   )

   return InboxLoad(threads=threads, notes=notes, unread_counts=unread_counts)
