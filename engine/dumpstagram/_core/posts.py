"""One post, read by its shortcode or its media pk, the accounts listed as liking it, and the
more posts from its author, asynchronously.

Both public surfaces call this, and the like capability's docstrings name it as the read that
confirms a like or reconciles one whose outcome is unknown. Nothing here knows the upstream
speaks GraphQL: the adapter in `_private/web/` builds the request and maps the answer.

A browser reads a post inside a post page load, beside the page's document and its companion
queries. That burst has not been recorded, because ruling 23 allowed no browser load when this
read was verified, so the engine sends the post query alone, a recorded departure in
`engine/docs/web-request-contract.md`.

The three reads E2 batch 4 added are each one query sent alone with the site root as referer,
because each is handed an identifier and not the shortcode a post page address needs (W62 to
W64).
"""

from __future__ import annotations

from dumpstagram._core.comments import refuse_what_is_not_a_media_pk
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse.media import (
   parse_likers,
   parse_more_from_author,
   parse_post_by_media_id,
   parse_post_detail,
)
from dumpstagram._private.web.requests.media import (
   build_likers_request,
   build_more_from_author_request,
   build_post_by_id_request,
   build_post_request,
)
from dumpstagram._private.web.requests.profiles import refuse_what_is_not_a_user_id
from dumpstagram.models import PostDetail, PostThumbnail, ProfileSummary
from dumpstagram.session import Session

__all__ = ["read_likers", "read_more_from_author", "read_post", "read_post_by_id"]


async def read_post(
   sender: PacedSender,
   session: Session,
   code: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> PostDetail:
   """Read the post whose shortcode is ``code`` and return it typed.

   One live request when the session already carries usable tokens, two when it has to
   bootstrap first.
   """

   async def attempt() -> PostDetail:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_post_request(session, code, user_agent=user_agent)
      response = await sender.send(request)

      return parse_post_detail(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


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
