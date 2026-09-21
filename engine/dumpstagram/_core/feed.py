"""The home timeline capability, written once, asynchronously.

Both public surfaces call this. ``SyncClient`` reaches it across the loop thread and
``AsyncClient`` awaits it directly, and neither adds behavior on the way, which is what
ADR-0001 means by one implementation and two doors.

Nothing here knows the upstream speaks GraphQL, or that this particular query answers on a
different path from every other one. The adapter in `_private/web/` owns all of it.

One method covers the whole connection, because the upstream's first page and its later pages
are the same query with one variable changed. A caller asks for a page and passes the previous
page's cursor back, and there is no first-page variant to get wrong.
"""

from __future__ import annotations

from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse import parse_feed_page
from dumpstagram._private.web.requests import build_feed_page_request
from dumpstagram.models import FeedItem, Page
from dumpstagram.session import Session

__all__ = ["read_feed_page"]


async def read_feed_page(
   sender: PacedSender,
   session: Session,
   *,
   after: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> Page[FeedItem]:
   """One page of the signed-in account's home timeline, in one live request.

   ``after`` is the previous page's ``end_cursor``, and ``None`` asks for the first page.

   The page's length is the upstream's decision rather than a parameter. Three measured pages
   carried 14, 12 and 5 items for the same request, and most items on each were not posts, so
   a caller counting posts has to keep asking and must stop on
   :attr:`~dumpstagram.models.Page.has_next_page` rather than on a page looking short.
   """

   async def attempt() -> Page[FeedItem]:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_feed_page_request(session, after=after, user_agent=user_agent)
      response = await sender.send(request)

      return parse_feed_page(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)
