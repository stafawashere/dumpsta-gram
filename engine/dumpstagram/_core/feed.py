"""The home timeline capability, written once, asynchronously.

Both public surfaces call this. ``SyncClient`` reaches it across the loop thread and
``AsyncClient`` awaits it directly, and neither adds behavior on the way, which is what
ADR-0001 means by one implementation and two doors.

Nothing here knows the upstream speaks GraphQL, or that this particular query answers on a
different path from every other one. The adapter in `_private/web/` owns all of it.

One method covers the whole connection. A caller asks for a page and passes the previous
page's cursor back, and there is no first-page variant to get wrong.

Underneath there are two routes to the first page. A browser loads the home document and reads
the first page the server preloaded into it, and :attr:`FeedFirstPage.DOCUMENT` does the same.
:attr:`FeedFirstPage.QUERY` asks the pagination query instead, which is the departure. Every
later page goes through the pagination query either way, which is what the browser does when
the feed scrolls.
"""

from __future__ import annotations

from dumpstagram._core.pacer import run_with_retries
from dumpstagram._core.page_load import send_companions
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._private.web.bootstrap import (
   DEFAULT_USER_AGENT,
   apply_tokens,
   bootstrap,
   build_document_request,
   tokens_from,
)
from dumpstagram._private.web.classify import classify, classify_preloaded
from dumpstagram._private.web.parse import parse_feed_page
from dumpstagram._private.web.preload import (
   FEED_TIMELINE_PRELOADER,
   HOME_DOCUMENT_URL,
   read_iris_device_id,
   read_preloaded_result,
)
from dumpstagram._private.web.requests import (
   build_feed_page_request,
   build_home_page_load_companions,
)
from dumpstagram.behavior import FeedFirstPage
from dumpstagram.models import FeedItem, Page
from dumpstagram.session import Session

__all__ = ["read_feed_page", "read_first_feed_page_from_document"]


async def read_feed_page(
   sender: PacedSender,
   session: Session,
   *,
   after: str | None = None,
   first_page: FeedFirstPage = FeedFirstPage.QUERY,
   companions: bool = False,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> Page[FeedItem]:
   """One page of the signed-in account's home timeline, in one live request.

   ``after`` is the previous page's ``end_cursor``, and ``None`` asks for the first page.

   The page's length is the upstream's decision rather than a parameter. Three measured pages
   carried 14, 12 and 5 items for the same request, and most items on each were not posts, so
   a caller counting posts has to keep asking and must stop on
   :attr:`~dumpstagram.models.Page.has_next_page` rather than on a page looking short.

   ``companions`` applies only when the first page is read from the home document, since that
   is the only page load here.
   """

   reads_the_document = after is None and first_page is FeedFirstPage.DOCUMENT

   if reads_the_document:
      return await read_first_feed_page_from_document(
         sender, session, companions=companions, user_agent=user_agent, deadline=deadline
      )

   async def attempt() -> Page[FeedItem]:
      lacks_page_tokens = not session.fb_dtsg or not session.bloks_version_id

      if lacks_page_tokens:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_feed_page_request(session, after=after, user_agent=user_agent)
      response = await sender.send(request)

      return parse_feed_page(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_first_feed_page_from_document(
   sender: PacedSender,
   session: Session,
   *,
   companions: bool = False,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> Page[FeedItem]:
   """The first feed page, read out of the home document the way a browser gets it.

   The document is one navigation and needs no page token, so there is no stale token to
   recover from. It carries fresh ones, and they are written onto the session, which is the
   same thing a browser's page load does to its own. A logged-out document carries no
   ``fb_dtsg``, so a dead session fails here as
   :class:`~dumpstagram.errors.AuthenticationFailed` before the preload is looked for.

   With ``companions`` the document and the home page load companions are one action, and the
   companions go out after the document's tokens are on the session and before the preload is
   read, as a page's do whether or not its feed renders.
   """

   async def attempt() -> Page[FeedItem]:
      async with sender.action() as action:
         response = await action.send(build_document_request(HOME_DOCUMENT_URL, user_agent))

         apply_tokens(session, tokens_from(response))

         if companions:
            groups = build_home_page_load_companions(
               session,
               device_id=read_iris_device_id(response.text),
               user_agent=user_agent,
            )
            await send_companions(action, groups)

      result = read_preloaded_result(response.text, FEED_TIMELINE_PRELOADER)

      return parse_feed_page(classify_preloaded(result))

   return await run_with_retries(attempt, pacer=sender.pacer, deadline=deadline)
