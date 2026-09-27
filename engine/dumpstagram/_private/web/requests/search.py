"""The search reads: the recent searches, the non-personalised typeahead, and a hashtag's header.

All three are persisted queries on ``/api/graphql``. The recent searches and the typeahead carry
the site root as referer and the hashtag header the tag's page, as ``probes/e2_search.py`` sent
them.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, ORIGIN
from dumpstagram._private.web.documents.search import (
   HASHTAG_HEADER,
   NON_PERSONALISED_TYPEAHEAD,
   RECENT_SEARCHES,
)
from dumpstagram._private.web.requests.common import build_graphql_request
from dumpstagram.session import Session

__all__ = [
   "build_hashtag_header_request",
   "build_non_personalised_typeahead_request",
   "build_recent_searches_request",
   "hashtag_page_url",
   "refuse_what_is_not_a_query",
   "refuse_what_is_not_a_tag",
]

_TAG = re.compile(r"\w+")


def refuse_what_is_not_a_query(query: str) -> None:
   """Raise :class:`ValueError` for a query with no text, before anything is built or sent.

   The typeahead was answered for a nine character query, and what it answers for an empty one
   is unobserved.
   """

   has_text = bool(query.strip())

   if not has_text:
      raise ValueError("a search needs query text, and this one is empty")


def refuse_what_is_not_a_tag(tag: str) -> None:
   """Raise :class:`ValueError` for anything but letters, digits and underscores, before anything
   is built or sent.

   A leading ``#`` is refused rather than stripped, so the tag a caller passes is the tag that is
   sent (W84).
   """

   is_a_tag = _TAG.fullmatch(tag) is not None

   if not is_a_tag:
      raise ValueError(
         f"{tag!r} is not a hashtag name. Pass the tag without its '#', letters, digits and "
         "underscores only"
      )


def hashtag_page_url(tag: str) -> str:
   """The tag's page, the header's referer, its name escaped as a browser's address bar does."""

   return f"{ORIGIN}/explore/tags/{quote(tag, safe='')}/"


def build_recent_searches_request(
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The viewer's recent searches, no variables, the site root as referer.

   Finding: ``read-recent-searches``.
   """

   return build_graphql_request(
      session,
      RECENT_SEARCHES,
      {},
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )


def build_non_personalised_typeahead_request(
   session: Session,
   query: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The accounts ``query`` matches, ranked without the viewer's profile, with ``hasQuery``
   true as both replays sent it.

   Finding: ``search-typeahead-non-personalised``.
   """

   return build_graphql_request(
      session,
      NON_PERSONALISED_TYPEAHEAD,
      {"hasQuery": True, "query": query},
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )


def build_hashtag_header_request(
   session: Session,
   tag: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The header of the hashtag ``tag``, named without its ``#``.

   Finding: ``read-a-hashtag-header``.
   """

   return build_graphql_request(
      session,
      HASHTAG_HEADER,
      {"tag_name": tag},
      referer=hashtag_page_url(tag),
      user_agent=user_agent,
   )
