"""One post, read by its shortcode or its media pk, the accounts listed as liking it, and the
more posts from its author, asynchronously.

Both public surfaces call this, and the like capability's docstrings name it as the read that
confirms a like or reconciles one whose outcome is unknown. Nothing here knows the upstream
speaks GraphQL: the adapter in `_private/web/` builds the request and maps the answer.

A browser reads a post inside a post page load: the document carries the post, its first
comments and its author's grid, and the page sends its companions after it. Since E2 batch 11d
:attr:`PostRoute.PAGE` does the same and reads the post out of the document, and
:attr:`PostRoute.QUERY` sends the post query alone, the named departure (W111, W112).
:func:`read_post_page` is that load with every part of it read.

The three reads E2 batch 4 added are each one query sent alone with the site root as referer,
because each is handed an identifier and not the shortcode a post page address needs (W62 to
W64).
"""

from __future__ import annotations

from collections.abc import Callable

from dumpstagram._core.comments import refuse_what_is_not_a_media_pk
from dumpstagram._core.cookie_sync import CookieSync
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
from dumpstagram._private.web.parse.media import (
   parse_comment_page,
   parse_likers,
   parse_more_from_author,
   parse_post_by_media_id,
   parse_post_detail,
)
from dumpstagram._private.web.preload import (
   POST_AUTHOR_GRID_PRELOADER,
   POST_COMMENTS_PRELOADER,
   POST_ROOT_PRELOADER,
   read_iris_device_id,
   read_preloaded_result,
)
from dumpstagram._private.web.requests.media import (
   build_likers_request,
   build_more_from_author_request,
   build_post_by_id_request,
   build_post_request,
   post_url,
)
from dumpstagram._private.web.requests.page_load import build_post_page_load_companions
from dumpstagram._private.web.requests.profiles import refuse_what_is_not_a_user_id
from dumpstagram.behavior import PostRoute
from dumpstagram.models import PostDetail, PostPage, PostThumbnail, ProfileSummary
from dumpstagram.session import Session

__all__ = [
   "read_likers",
   "read_more_from_author",
   "read_post",
   "read_post_by_id",
   "read_post_page",
]


async def read_post(
   sender: PacedSender,
   session: Session,
   code: str,
   *,
   route: PostRoute = PostRoute.QUERY,
   companions: bool = False,
   cookie_sync: CookieSync | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> PostDetail:
   """Read the post whose shortcode is ``code`` and return it typed.

   On :attr:`PostRoute.PAGE` the post page is loaded and the post read out of its document, as
   :func:`read_post_page` loads it, and only the post's preload is read, so a page whose comments
   or grid the upstream stopped preloading still answers the post.

   On :attr:`PostRoute.QUERY` one live request when the session already carries usable tokens,
   two when it has to bootstrap first. ``companions`` and ``cookie_sync`` apply only to the page.
   """

   if route is PostRoute.PAGE:
      return await _load_post_page(
         sender,
         session,
         code,
         read=_post_out_of,
         companions=companions,
         cookie_sync=cookie_sync,
         user_agent=user_agent,
         deadline=deadline,
      )

   async def attempt() -> PostDetail:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_post_request(session, code, user_agent=user_agent)
      response = await sender.send(request)

      return parse_post_detail(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_post_page(
   sender: PacedSender,
   session: Session,
   code: str,
   *,
   companions: bool = False,
   cookie_sync: CookieSync | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> PostPage:
   """The post page of the shortcode ``code``, loaded the way a browser loads it (W111).

   One action: the document, then with ``companions`` the page's companions (W112). The post,
   its first comments and its author's grid are read out of the document's preloads, and a
   document missing any of the three raises :class:`~dumpstagram.errors.SchemaChanged`.
   """

   return await _load_post_page(
      sender,
      session,
      code,
      read=_page_out_of,
      companions=companions,
      cookie_sync=cookie_sync,
      user_agent=user_agent,
      deadline=deadline,
   )


def _post_out_of(html: str) -> PostDetail:
   return parse_post_detail(classify_preloaded(read_preloaded_result(html, POST_ROOT_PRELOADER)))


def _page_out_of(html: str) -> PostPage:
   comments = classify_preloaded(read_preloaded_result(html, POST_COMMENTS_PRELOADER))
   author_grid = classify_preloaded(read_preloaded_result(html, POST_AUTHOR_GRID_PRELOADER))

   return PostPage(
      post=_post_out_of(html),
      comments=parse_comment_page(comments),
      author_grid=parse_more_from_author(author_grid),
   )


async def _load_post_page[T](
   sender: PacedSender,
   session: Session,
   code: str,
   *,
   read: Callable[[str], T],
   companions: bool,
   cookie_sync: CookieSync | None,
   user_agent: str,
   deadline: float | None,
) -> T:
   """Load the post page and hand its document to ``read``.

   The document is one navigation and needs no page token, so there is no stale token to
   recover from; it carries fresh ones, which are written onto the session before the companions
   are built. A logged-out document carries no ``fb_dtsg`` and fails as
   :class:`~dumpstagram.errors.AuthenticationFailed` before a preload is looked for. A load that
   raises schedules no cookie sync tail.
   """

   page_url = post_url(code)

   async def attempt() -> T:
      async with sender.action() as action:
         loaded_at = sender.pacer.now()
         document = await action.send(build_document_request(page_url, user_agent))

         apply_tokens(session, tokens_from(document))

         if companions:
            groups = build_post_page_load_companions(
               session,
               code,
               device_id=read_iris_device_id(document.text),
               user_agent=user_agent,
            )
            await send_companions(action, groups)

      result = read(document.text)

      if cookie_sync is not None:
         cookie_sync.start(session, page_url, loaded_at=loaded_at, user_agent=user_agent)

      return result

   return await run_with_retries(attempt, pacer=sender.pacer, deadline=deadline)


async def read_post_by_id(
   sender: PacedSender,
   session: Session,
   post_pk: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> PostDetail:
   """Read the post whose media ``pk`` is ``post_pk``, one live request (W63)."""

   refuse_what_is_not_a_media_pk(post_pk)

   async def attempt() -> PostDetail:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_post_by_id_request(session, post_pk, user_agent=user_agent)
      response = await sender.send(request)

      return parse_post_by_media_id(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_likers(
   sender: PacedSender,
   session: Session,
   post_pk: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> tuple[ProfileSummary, ...]:
   """The accounts listed as liking the post whose media ``pk`` is ``post_pk``, one live
   request (W62)."""

   refuse_what_is_not_a_media_pk(post_pk)

   async def attempt() -> tuple[ProfileSummary, ...]:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_likers_request(session, post_pk, user_agent=user_agent)
      response = await sender.send(request)

      return parse_likers(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_more_from_author(
   sender: PacedSender,
   session: Session,
   author_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> tuple[PostThumbnail, ...]:
   """The "more posts from" strip for the account whose numeric id is ``author_id``, one live
   request (W64)."""

   refuse_what_is_not_a_user_id(author_id)

   async def attempt() -> tuple[PostThumbnail, ...]:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_more_from_author_request(session, author_id, user_agent=user_agent)
      response = await sender.send(request)

      return parse_more_from_author(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)
