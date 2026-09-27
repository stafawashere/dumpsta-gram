"""The search reads: the recent searches, both typeaheads, a hashtag's header and the keyword
grid.

All five are persisted queries on ``/api/graphql``. The recent searches and both typeaheads
carry the site root as referer, the hashtag header the tag's page and the keyword grid the
keyword page, as ``probes/e2_search.py`` and ``probes/e2_capture_replays.py --stage search`` sent
them.
"""

from __future__ import annotations

import re
import uuid
from urllib.parse import quote, urlencode

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, ORIGIN
from dumpstagram._private.web.documents.search import (
   HASHTAG_HEADER,
   KEYWORD_RESULTS,
   NON_PERSONALISED_TYPEAHEAD,
   PERSONALISED_TYPEAHEAD,
   RECENT_SEARCHES,
)
from dumpstagram._private.web.requests.common import build_graphql_request
from dumpstagram.session import Session

__all__ = [
   "TYPEAHEAD_CONSTANTS",
   "build_hashtag_header_request",
   "build_keyword_results_request",
   "build_non_personalised_typeahead_request",
   "build_personalised_typeahead_request",
   "build_recent_searches_request",
   "hashtag_page_url",
   "keyword_page_url",
   "new_search_session_id",
   "refuse_what_is_not_a_query",
   "refuse_what_is_not_a_tag",
]

_TAG = re.compile(r"\w+")

TYPEAHEAD_CONSTANTS = {
   "context": "blended",
   "include_reel": "true",
   "search_surface": "web_top_search",
}
"""The three values the personalised typeahead's ``data`` carried beside the query and the two
session values, as the browser sent them, ``include_reel`` a string."""


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


def new_search_session_id() -> str:
   """A fresh lowercase uuid4, the form of the one session id the browser's search panel and its
   keyword page each made for themselves (W102)."""

   return str(uuid.uuid4())


def build_personalised_typeahead_request(
   session: Session,
   query: str,
   *,
   search_session_id: str,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The blended results for ``query``, as the first query of a new search session sends it,
   with an empty ``rank_token``.

   Finding: ``search-typeahead-personalised-as-sent``.
   """

   data = {
      "context": TYPEAHEAD_CONSTANTS["context"],
      "include_reel": TYPEAHEAD_CONSTANTS["include_reel"],
      "query": query,
      "rank_token": "",
      "search_session_id": search_session_id,
      "search_surface": TYPEAHEAD_CONSTANTS["search_surface"],
   }

   return build_graphql_request(
      session,
      PERSONALISED_TYPEAHEAD,
      {"data": data, "hasQuery": True},
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )


def keyword_page_url(query: str) -> str:
   """The keyword page, the grid's referer, its query escaped as the browser's was, a ``#`` as
   ``%23``."""

   return f"{ORIGIN}/explore/search/keyword/?{urlencode({'q': query}, quote_via=quote)}"


def build_keyword_results_request(
   session: Session,
   query: str,
   *,
   search_session_id: str,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The keyword grid's first page for ``query``, one session id sent as both of its ids, and no
   ``first`` or ``after``, as the browser sent it.

   Finding: ``read-keyword-search-results``.
   """

   variables = {
      "query": query,
      "search_session_id": search_session_id,
      "serp_session_id": search_session_id,
   }

   return build_graphql_request(
      session,
      KEYWORD_RESULTS,
      variables,
      referer=keyword_page_url(query),
      user_agent=user_agent,
   )
