"""One page of a post's comments, asynchronously.

Both public surfaces call this, and the comment capability's docstrings name it as the read
that confirms a comment or a delete and reconciles one whose outcome is unknown. Nothing here
knows the upstream speaks GraphQL: the adapter in `_private/web/` builds the request and maps
the answer.

A browser reads comments inside a post page load, the first page with a query of its own. That
burst has not been recorded, because ruling 23 allowed no browser load when this read was
verified, so the engine sends the pagination query alone for every page, a recorded departure
in `engine/docs/web-request-contract.md`.
"""

from __future__ import annotations

from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse.media import parse_comment_page
from dumpstagram._private.web.requests.media import build_comment_page_request, is_a_media_pk
from dumpstagram.models import Comment, Page
from dumpstagram.session import Session

__all__ = ["read_comment_page"]


async def read_comment_page(
   sender: PacedSender,
   session: Session,
   post_pk: str,
   *,
   after: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> Page[Comment]:
   """Read one page of the comments on the post whose media ``pk`` is ``post_pk``.

   One live request when the session already carries usable tokens, two when it has to
   bootstrap first. ``after`` is the previous page's ``end_cursor``.
   """

   if not is_a_media_pk(post_pk):
      raise ValueError(
         f"{post_pk!r} is not a media pk. Pass Post.pk or PostDetail.pk, not the id form"
      )

   async def attempt() -> Page[Comment]:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_comment_page_request(session, post_pk, after=after, user_agent=user_agent)
      response = await sender.send(request)

      return parse_comment_page(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)
