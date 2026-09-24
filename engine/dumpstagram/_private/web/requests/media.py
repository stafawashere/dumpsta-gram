"""The post requests: one post by shortcode, like and unlike, a comment page, and commenting and
deleting a comment.
"""

from __future__ import annotations

import re
from typing import Any

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, ORIGIN
from dumpstagram._private.web.documents.media import (
   COMMENT_PAGE,
   CREATE_COMMENT,
   DELETE_COMMENT,
   LIKE_MEDIA,
   POST_BY_SHORTCODE,
   UNLIKE_MEDIA,
)
from dumpstagram._private.web.requests.common import build_graphql_request
from dumpstagram.errors import NotFound
from dumpstagram.session import Session

__all__ = [
   "COMMENT_PAGE_SIZE",
   "build_comment_page_request",
   "build_create_comment_request",
   "build_delete_comment_request",
   "build_like_request",
   "build_post_request",
   "build_unlike_request",
   "is_a_comment_id",
   "is_a_media_pk",
   "post_url",
]

_SHORTCODE = re.compile(r"[A-Za-z0-9_-]{1,64}")

_MEDIA_PK = re.compile(r"[0-9]{1,30}")

_COMMENT_ID = re.compile(r"[0-9]{1,30}")

COMMENT_PAGE_SIZE = 10
"""How many comments a page asks for, chosen by the engine.

The value the post page asks for has not been observed, so this is an ASSUMPTION and a
difference a fingerprint check could read. Four engine reads sent it and were answered.
"""


def post_url(code: str) -> str:
   """The post page a browser navigates to for the shortcode ``code``.

   The shortcode becomes a path segment, so anything outside the characters one is written in
   is refused before it is sent, as a post that cannot exist.
   """

   is_a_possible_shortcode = _SHORTCODE.fullmatch(code) is not None

   if not is_a_possible_shortcode:
      raise NotFound(f"{code!r} cannot be a post shortcode")

   return f"{ORIGIN}/p/{code}/"


def build_post_request(
   session: Session,
   code: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """One post, read by its shortcode the way the post page reads it.

   The two provider values are the ones the profile timeline query was captured sending, and
   the engine replays of this query carried the same pair.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/read-a-post-by-shortcode.md``.
   """

   return build_graphql_request(
      session,
      POST_BY_SHORTCODE,
      {
         "shortcode": code,
         "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": False,
         "__relay_internal__pv__PolarisMultiCaptionCarouselEnabledrelayprovider": True,
      },
      referer=post_url(code),
      user_agent=user_agent,
   )


def is_a_media_pk(value: str) -> bool:
   """Whether ``value`` has the shape of a media ``pk``, digits only.

   The other identifier a post carries, ``<pk>_<owner id>``, fails this, and so does anything
   else a caller might hand over by mistake.
   """

   return _MEDIA_PK.fullmatch(value) is not None


def build_like_request(
   session: Session,
   post_pk: str,
   *,
   client_mutation_id: str,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Like the post whose media ``pk`` is ``post_pk``.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/like-a-post.md``.
   """

   return build_graphql_request(
      session,
      LIKE_MEDIA,
      _like_variables(post_pk, client_mutation_id),
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )


def build_unlike_request(
   session: Session,
   post_pk: str,
   *,
   client_mutation_id: str,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Unlike the post whose media ``pk`` is ``post_pk``.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/unlike-a-post.md``.
   """

   return build_graphql_request(
      session,
      UNLIKE_MEDIA,
      _like_variables(post_pk, client_mutation_id),
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )


def _like_variables(post_pk: str, client_mutation_id: str) -> dict[str, Any]:
   """The input both mutations take, as the engine replays sent it.

   ``media_id`` is the ``pk``, never the ``<pk>_<owner id>`` form, observed on six sends.
   ``tracking_token`` is null because the engine is handed an identifier and not the feed item
   whose ``organic_tracking_token`` a browser would pass, and the Relay network layer's
   ``actor_id`` is absent because the session does not hold it. Both departures were in every
   observed send, and each is recorded in ``engine/docs/web-request-contract.md``.
   """

   return {
      "input": {
         "client_mutation_id": client_mutation_id,
         "media_id": post_pk,
         "tracking_token": None,
      }
   }


def build_comment_page_request(
   session: Session,
   post_pk: str,
   *,
   after: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """One page of the comments on the post whose media ``pk`` is ``post_pk``.

   ``sort_order`` is the value the post page's own first page query has compiled in. The
   referer is the home page, as every engine read carried, because the capability is handed
   a ``pk`` and not the shortcode a post page address needs.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/read-a-post-comment-page.md``.
   """

   return build_graphql_request(
      session,
      COMMENT_PAGE,
      {
         "after": after,
         "before": None,
         "first": COMMENT_PAGE_SIZE,
         "last": None,
         "media_id": post_pk,
         "sort_order": "popular",
         "__relay_internal__pv__PolarisIsLoggedInrelayprovider": True,
      },
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )


def build_create_comment_request(
   session: Session,
   post_pk: str,
   text: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Comment ``text`` on the post whose media ``pk`` is ``post_pk``.

   The variable is ``data`` rather than ``input``, so the Relay network layer adds no
   ``client_mutation_id``. ``connections`` is a handle into the browser's own store, which the
   engine does not have, and the empty list it sends was accepted on both engine sends.
   ``replied_to_comment_id`` and ``tracking_token`` are left out, as a browser leaves out a value
   it does not have.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/comment-on-a-post.md``.
   """

   return build_graphql_request(
      session,
      CREATE_COMMENT,
      {"connections": [], "data": {"comment_text": text, "media_id": post_pk}},
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )


def is_a_comment_id(value: str) -> bool:
   """Whether ``value`` has the shape of a comment id, digits only, 17 on every one observed."""

   return _COMMENT_ID.fullmatch(value) is not None


def build_delete_comment_request(
   session: Session,
   post_pk: str,
   comment_id: str,
   *,
   client_mutation_id: str,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Delete the comment ``comment_id`` on the post whose media ``pk`` is ``post_pk``.

   The input field names are not in the compiled artifact. An input carrying neither was
   refused as noncoercible, and one carrying ``comment_id`` and ``media_id`` was accepted, on
   2026-09-23, and two real deletes with them were confirmed by the comment read.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/delete-my-own-comment.md``.
   """

   return build_graphql_request(
      session,
      DELETE_COMMENT,
      {
         "input": {
            "client_mutation_id": client_mutation_id,
            "comment_id": comment_id,
            "media_id": post_pk,
         }
      },
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )
