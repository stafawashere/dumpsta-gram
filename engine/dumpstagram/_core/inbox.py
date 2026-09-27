"""The direct inbox read side: its pages, the message requests and the unread counts.

Both public surfaces call this. Nothing here knows the upstream speaks GraphQL: the adapter in
`_private/web/` builds the requests and maps the answers.

A browser reads all three inside an inbox page load, beside the document, the notes tray and the
page's companions. The engine does not model the inbox load's direct block yet, so each read here
sends its own queries alone, a recorded departure in `engine/docs/web-request-contract.md`.

Nothing here opens a thread, so nothing is marked read or seen to anyone (W43).
"""

from __future__ import annotations

import time
import uuid

from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse.direct import (
   InboxPage,
   parse_folder_unread_rows,
   parse_inbox_next_page,
   parse_inbox_page,
   parse_message_requests,
)
from dumpstagram._private.web.requests.direct import (
   INBOX_FOLDER,
   PENDING_FOLDER,
   build_folder_unread_rows_request,
   build_inbox_listing_request,
   build_inbox_next_page_request,
   build_message_requests_request,
)
from dumpstagram.models import DirectThread, MessageRequests, Page, UnreadCounts
from dumpstagram.session import Session

__all__ = [
   "INBOX_CURSOR_SEPARATOR",
   "inbox_cursor",
   "read_inbox_page",
   "read_message_requests",
   "read_unread_counts",
   "split_inbox_cursor",
]

INBOX_CURSOR_SEPARATOR = ":"
"""What joins the mailbox id to the upstream's cursor in the cursor an inbox page hands out.

The next page query is keyed on both, and the mailbox id is on the first page's answer only, so
the cursor carries it (W46). Neither part was seen to hold this character: the mailbox id is
digits and the upstream's cursors were URL-safe base64.
"""


def inbox_cursor(mailbox_id: str, upstream_cursor: str) -> str:
   return f"{mailbox_id}{INBOX_CURSOR_SEPARATOR}{upstream_cursor}"


def split_inbox_cursor(after: str) -> tuple[str, str]:
   """The mailbox id and the upstream cursor an inbox page's ``end_cursor`` carries.

   Raises :class:`ValueError` for anything an inbox page did not hand out, before anything is
   sent, rather than asking the upstream a question with half its key missing.
   """

   mailbox_id, separator, upstream_cursor = after.partition(INBOX_CURSOR_SEPARATOR)
   names_a_mailbox = mailbox_id.isascii() and mailbox_id.isdigit()
   is_an_inbox_cursor = bool(separator) and names_a_mailbox and bool(upstream_cursor)

   if not is_an_inbox_cursor:
      raise ValueError(
         "an inbox cursor is the end_cursor of a page direct.inbox returned, "
         "not a cursor from another read"
      )

   return mailbox_id, upstream_cursor


def _public_page(inbox_page: InboxPage) -> Page[DirectThread]:
   page = inbox_page.page
   upstream_cursor = page.end_cursor
   end_cursor = None

   if upstream_cursor is not None:
      end_cursor = inbox_cursor(inbox_page.mailbox_id, upstream_cursor)

   return Page(items=page.items, has_next_page=page.has_next_page, end_cursor=end_cursor)


def _now_ms() -> int:
   return int(time.time() * 1000)


async def read_inbox_page(
   sender: PacedSender,
   session: Session,
   *,
   after: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> Page[DirectThread]:
   """Read one page of the direct inbox, newest activity first.

   The first page is the listing an inbox load reads, and every later one the query a browser's
   thread list pages with. One live request when the session already carries usable tokens, two
   when it has to bootstrap first. ``after`` is a previous page's ``end_cursor``.
   """

   next_page_key = None if after is None else split_inbox_cursor(after)

   async def attempt() -> Page[DirectThread]:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      if next_page_key is None:
         request = build_inbox_listing_request(
            session, device_id=str(uuid.uuid4()), user_agent=user_agent
         )
         response = await sender.send(request)

         return _public_page(parse_inbox_page(classify(response)))

      mailbox_id, upstream_cursor = next_page_key
      request = build_inbox_next_page_request(
         session, mailbox_id=mailbox_id, cursor=upstream_cursor, user_agent=user_agent
      )
      response = await sender.send(request)

      return _public_page(parse_inbox_next_page(classify(response)))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_message_requests(
   sender: PacedSender,
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> MessageRequests:
   """Read the pending and spam request folders, one page of each, in one live request."""

   async def attempt() -> MessageRequests:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_message_requests_request(
         session, iris_device_id=str(uuid.uuid4()), now_ms=_now_ms(), user_agent=user_agent
      )
      response = await sender.send(request)

      return parse_message_requests(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_unread_counts(
   sender: PacedSender,
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> UnreadCounts:
   """Count the unread threads in the inbox and in the pending requests.

   Two live requests, the inbox folder and then the pending folder, in the order an inbox load
   sends them and with one device id between them, as one document holds one.
   """

   async def attempt() -> UnreadCounts:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      device_id = str(uuid.uuid4())
      now_ms = _now_ms()
      inbox_request = build_folder_unread_rows_request(
         session,
         iris_device_id=device_id,
         folder=INBOX_FOLDER,
         now_ms=now_ms,
         user_agent=user_agent,
      )
      inbox = parse_folder_unread_rows(classify(await sender.send(inbox_request)))
      pending_request = build_folder_unread_rows_request(
         session,
         iris_device_id=device_id,
         folder=PENDING_FOLDER,
         now_ms=now_ms,
         user_agent=user_agent,
      )
      pending = parse_folder_unread_rows(classify(await sender.send(pending_request)))

      return UnreadCounts(
         inbox=inbox.unread,
         pending=pending.unread,
         inbox_has_more=inbox.has_more,
         pending_has_more=pending.has_more,
      )

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)
