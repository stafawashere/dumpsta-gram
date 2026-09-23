"""The direct-message capability, written once, asynchronously.

Both public surfaces call this. ``SyncClient`` reaches it across the loop thread and
``AsyncClient`` awaits it directly, and neither adds behavior on the way, which is what ADR-0001
means by one implementation and two doors.

Nothing here knows the upstream speaks GraphQL. It builds no body, reads no header, and names
no field: the adapter in `_private/web/` owns all three and hands back typed models.

There are two routes to a thread's newest page. A browser opening a thread sends the thread
detail query, and :attr:`ThreadFirstPage.DETAIL` does the same. :attr:`ThreadFirstPage.QUERY`
asks the pagination query instead, which is the departure. Every older page, and every top-up
since a message already seen, goes through the pagination query either way.
"""

from __future__ import annotations

from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse import parse_thread_detail, parse_thread_message_page
from dumpstagram._private.web.requests import (
   build_thread_detail_request,
   build_thread_older_page_request,
)
from dumpstagram.behavior import ThreadFirstPage
from dumpstagram.models import Message, Page
from dumpstagram.session import Session

__all__ = ["read_thread_messages"]


async def read_thread_messages(
   sender: PacedSender,
   session: Session,
   thread_fbid: str,
   *,
   after: str | None = None,
   newer_than_message_id: str | None = None,
   first_page: ThreadFirstPage = ThreadFirstPage.QUERY,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> Page[Message]:
   """Read one page of one thread and return it typed.

   One live request when the session already carries usable tokens, two when it has to
   bootstrap first. The page size is not a parameter because the upstream caps it server side
   at twenty however many are asked for, so exposing the number would offer a choice the
   caller does not have.

   ``QUERY`` stays the default at this level so callers below the client keep the route they
   had, and the client passes its behavior down.
   """

   is_newest_page = after is None and newer_than_message_id is None
   opens_the_thread = is_newest_page and first_page is ThreadFirstPage.DETAIL

   async def attempt() -> Page[Message]:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      if opens_the_thread:
         request = build_thread_detail_request(session, thread_fbid, user_agent=user_agent)
         response = await sender.send(request)

         return parse_thread_detail(classify(response))

      request = build_thread_older_page_request(
         session,
         thread_fbid,
         after=after,
         newer_than_message_id=newer_than_message_id,
         user_agent=user_agent,
      )
      response = await sender.send(request)

      return parse_thread_message_page(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)
