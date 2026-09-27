"""The direct inbox read side: its pages, the message requests and the unread counts, and the
inbox page load the notes tray is read from too.

Both public surfaces call this. Nothing here knows the upstream speaks GraphQL: the adapter in
`_private/web/` builds the requests and maps the answers.

A browser reads the inbox's first page, the unread counts and the notes tray inside an inbox
page load: the document, then the ten queries of the page's direct block at once, then the
page's companions. :attr:`InboxRoute.PAGE` does the same, since E2 batch 9, and whichever of the
three is asked for, the whole block goes out and only that read's answers are read (W87).
:attr:`InboxRoute.QUERIES` sends the read's own queries alone, the departure. Every later inbox
page and the message requests are sent alone either way, as a browser sends them when its
thread list scrolls and when its requests view opens.

The thread detail queries an inbox load prefetches read nothing a caller sees and mark nothing
seen. Nothing here opens a thread, so nothing is marked read or seen to anyone (W43).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from dumpstagram._core.cookie_sync import CookieSync
from dumpstagram._core.pacer import run_with_retries
from dumpstagram._core.page_load import raise_only_what_concerns_the_account, send_companions
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._private.transport import Response
from dumpstagram._private.web.bootstrap import (
   DEFAULT_USER_AGENT,
   apply_tokens,
   bootstrap,
   build_document_request,
   tokens_from,
)
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse.direct import (
   InboxPage,
   parse_folder_unread_rows,
   parse_inbox_next_page,
   parse_inbox_page,
   parse_message_requests,
   parse_thread_prefetch_keys,
)
from dumpstagram._private.web.preload import read_iris_device_id
from dumpstagram._private.web.requests.direct import (
   INBOX_FOLDER,
   PENDING_FOLDER,
   build_folder_unread_rows_request,
   build_inbox_listing_request,
   build_inbox_next_page_request,
   build_message_requests_request,
)
from dumpstagram._private.web.requests.notes import build_inbox_tray_request
from dumpstagram._private.web.requests.page_load import (
   INBOX_PAGE_URL,
   build_inbox_block,
   build_inbox_page_load_companions,
)
from dumpstagram._private.web.requests.profiles import new_web_session_id
from dumpstagram.behavior import InboxRoute
from dumpstagram.errors import SchemaChanged, UpstreamRejected
from dumpstagram.models import DirectThread, MessageRequests, Page, UnreadCounts
from dumpstagram.session import Session

__all__ = [
   "INBOX_CURSOR_SEPARATOR",
   "InboxPageAnswers",
   "inbox_cursor",
   "read_from_inbox_page",
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


@dataclass(frozen=True)
class InboxPageAnswers:
   """The four answers of an inbox load's direct block that a capability reads."""

   tray: Response
   listing: Response
   inbox_unread_rows: Response
   pending_unread_rows: Response


def _thread_prefetch_keys(listing: Response) -> tuple[str, ...]:
   try:
      return parse_thread_prefetch_keys(classify(listing))
   except (UpstreamRejected, SchemaChanged):
      return ()


async def read_from_inbox_page[T](
   sender: PacedSender,
   session: Session,
   read: Callable[[InboxPageAnswers], T],
   *,
   companions: bool = False,
   cookie_sync: CookieSync | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> T:
   """Load the direct inbox the way a browser does and return what ``read`` makes of it.

   One action: the inbox document, then the ten queries of its direct block at once, then with
   ``companions`` the inbox load's companions. The document needs no page token and carries
   fresh ones, which are written onto the session before the block is built, so there is no
   stale token to recover from. The block's four iris queries carry the document's device id,
   and a fresh one when the document stopped carrying it, since a replay with an id no page
   issued answered the same (W87).

   ``read`` maps the answers the caller wants, after the action. Every answer of the block is
   first checked for a checkpoint or a throttle, which concern the whole account, and otherwise
   left alone, so a query the caller does not read cannot cost it the read. The thread detail
   prefetches are keyed on the block's listing, and a listing the upstream refused sends none.

   With ``cookie_sync`` a successful read schedules the page's cookie sync tail, timed from the
   document's departure. A load or a read that raises schedules none.
   """

   async def attempt() -> T:
      async with sender.action() as action:
         loaded_at = sender.pacer.now()
         document = await action.send(build_document_request(INBOX_PAGE_URL, user_agent))

         apply_tokens(session, tokens_from(document))
         document_device_id = read_iris_device_id(document.text)
         device_id = document_device_id or str(uuid.uuid4())
         now_ms = _now_ms()

         tray = build_inbox_tray_request(session, user_agent=user_agent)
         listing = build_inbox_listing_request(session, device_id=device_id, user_agent=user_agent)
         inbox_unread_rows = build_folder_unread_rows_request(
            session,
            iris_device_id=device_id,
            folder=INBOX_FOLDER,
            now_ms=now_ms,
            user_agent=user_agent,
         )
         pending_unread_rows = build_folder_unread_rows_request(
            session,
            iris_device_id=device_id,
            folder=PENDING_FOLDER,
            now_ms=now_ms,
            user_agent=user_agent,
         )
         block = build_inbox_block(
            session,
            tray=tray,
            listing=listing,
            inbox_unread_rows=inbox_unread_rows,
            pending_unread_rows=pending_unread_rows,
            user_agent=user_agent,
         )
         responses = await action.send_together(block)

         for response in responses:
            raise_only_what_concerns_the_account(response)

         answer_to = {
            id(request): response for request, response in zip(block, responses, strict=True)
         }
         answers = InboxPageAnswers(
            tray=answer_to[id(tray)],
            listing=answer_to[id(listing)],
            inbox_unread_rows=answer_to[id(inbox_unread_rows)],
            pending_unread_rows=answer_to[id(pending_unread_rows)],
         )

         if companions:
            groups = build_inbox_page_load_companions(
               session,
               device_id=document_device_id,
               thread_keys=_thread_prefetch_keys(answers.listing),
               web_session_id=new_web_session_id(),
               user_agent=user_agent,
            )
            await send_companions(action, groups)

      result = read(answers)

      if cookie_sync is not None:
         cookie_sync.start(session, INBOX_PAGE_URL, loaded_at=loaded_at, user_agent=user_agent)

      return result

   return await run_with_retries(attempt, pacer=sender.pacer, deadline=deadline)


async def read_inbox_page(
   sender: PacedSender,
   session: Session,
   *,
   after: str | None = None,
   route: InboxRoute = InboxRoute.QUERIES,
   companions: bool = False,
   cookie_sync: CookieSync | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> Page[DirectThread]:
   """Read one page of the direct inbox, newest activity first.

   The first page is the listing an inbox load reads, and every later one the query a browser's
   thread list pages with. One live request when the session already carries usable tokens, two
   when it has to bootstrap first. ``after`` is a previous page's ``end_cursor``.

   Under :attr:`InboxRoute.PAGE` the first page is read from the inbox page load
   :func:`read_from_inbox_page` describes, and ``companions`` and ``cookie_sync`` apply only
   there. ``QUERIES`` and no companions stay the defaults at this level so callers below the
   client keep the requests they had, and the client passes its behavior down.
   """

   next_page_key = None if after is None else split_inbox_cursor(after)
   reads_the_page = next_page_key is None and route is InboxRoute.PAGE

   if reads_the_page:
      return await read_from_inbox_page(
         sender,
         session,
         lambda answers: _public_page(parse_inbox_page(classify(answers.listing))),
         companions=companions,
         cookie_sync=cookie_sync,
         user_agent=user_agent,
         deadline=deadline,
      )

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


def _unread_counts(inbox_rows: Response, pending_rows: Response) -> UnreadCounts:
   inbox = parse_folder_unread_rows(classify(inbox_rows))
   pending = parse_folder_unread_rows(classify(pending_rows))

   return UnreadCounts(
      inbox=inbox.unread,
      pending=pending.unread,
      inbox_has_more=inbox.has_more,
      pending_has_more=pending.has_more,
   )


async def read_unread_counts(
   sender: PacedSender,
   session: Session,
   *,
   route: InboxRoute = InboxRoute.QUERIES,
   companions: bool = False,
   cookie_sync: CookieSync | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> UnreadCounts:
   """Count the unread threads in the inbox and in the pending requests.

   Two live requests, the inbox folder and then the pending folder, in the order an inbox load
   sends them and with one device id between them, as one document holds one. Under
   :attr:`InboxRoute.PAGE` both are read from the inbox page load instead, and ``companions``
   and ``cookie_sync`` apply only there.
   """

   if route is InboxRoute.PAGE:
      return await read_from_inbox_page(
         sender,
         session,
         lambda answers: _unread_counts(answers.inbox_unread_rows, answers.pending_unread_rows),
         companions=companions,
         cookie_sync=cookie_sync,
         user_agent=user_agent,
         deadline=deadline,
      )

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
