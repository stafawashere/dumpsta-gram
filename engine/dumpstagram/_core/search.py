"""The recent searches, both typeaheads, a hashtag's header and the keyword grid, asynchronously.

Each read is one request sent alone. A browser reads the recent searches when the search panel
opens, the typeahead as the viewer types, and the hashtag header and the keyword grid inside the
load of the keyword page; the panel and the page load are not modelled, a named departure from
ADR-0013 as every read before these. None of them changes anything another person can see.

Which typeahead a search sends is :attr:`~dumpstagram.behavior.Behavior.typeahead_route` (W102).
"""

from __future__ import annotations

from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse.search import (
   accounts_in_order,
   parse_hashtag_header,
   parse_keyword_results,
   parse_non_personalised_typeahead,
   parse_personalised_typeahead,
   parse_recent_searches,
   results_of_accounts,
)
from dumpstagram._private.web.requests.search import (
   build_hashtag_header_request,
   build_keyword_results_request,
   build_non_personalised_typeahead_request,
   build_personalised_typeahead_request,
   build_recent_searches_request,
   new_search_session_id,
   refuse_what_is_not_a_query,
   refuse_what_is_not_a_tag,
)
from dumpstagram.behavior import TypeaheadRoute
from dumpstagram.models import (
   Hashtag,
   KeywordResults,
   ProfileSummary,
   RecentSearch,
   SearchResults,
)
from dumpstagram.session import Session

__all__ = [
   "read_hashtag_header",
   "read_keyword_results",
   "read_non_personalised_typeahead",
   "read_personalised_typeahead",
   "read_recent_searches",
   "read_top_results",
   "read_typeahead_accounts",
]


async def read_recent_searches(
   sender: PacedSender,
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> tuple[RecentSearch, ...]:
   """The viewer's recent searches, one live request (W82)."""

   async def attempt() -> tuple[RecentSearch, ...]:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_recent_searches_request(session, user_agent=user_agent)
      response = await sender.send(request)

      return parse_recent_searches(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_non_personalised_typeahead(
   sender: PacedSender,
   session: Session,
   query: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> tuple[ProfileSummary, ...]:
   """The accounts ``query`` matches, ranked without the viewer's profile, one live request
   (W83)."""

   refuse_what_is_not_a_query(query)

   async def attempt() -> tuple[ProfileSummary, ...]:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_non_personalised_typeahead_request(session, query, user_agent=user_agent)
      response = await sender.send(request)

      return parse_non_personalised_typeahead(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_hashtag_header(
   sender: PacedSender,
   session: Session,
   tag: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> Hashtag:
   """The header of the hashtag ``tag``, one live request (W84)."""

   refuse_what_is_not_a_tag(tag)

   async def attempt() -> Hashtag:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_hashtag_header_request(session, tag, user_agent=user_agent)
      response = await sender.send(request)

      return parse_hashtag_header(classify(response), tag)

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_personalised_typeahead(
   sender: PacedSender,
   session: Session,
   query: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> SearchResults:
   """What the search box offers for ``query``, ranked with the viewer's profile, one live
   request, the first query of a search session of its own (W102)."""

   refuse_what_is_not_a_query(query)
   search_session_id = new_search_session_id()

   async def attempt() -> SearchResults:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_personalised_typeahead_request(
         session, query, search_session_id=search_session_id, user_agent=user_agent
      )
      response = await sender.send(request)

      return parse_personalised_typeahead(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_top_results(
   sender: PacedSender,
   session: Session,
   query: str,
   *,
   route: TypeaheadRoute = TypeaheadRoute.PERSONALISED,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> SearchResults:
   """What the search box offers for ``query`` on ``route``, one live request (W102).

   The non-personalised route answers accounts only, so its results are accounts with no
   position.
   """

   if route is TypeaheadRoute.NON_PERSONALISED:
      accounts = await read_non_personalised_typeahead(
         sender, session, query, user_agent=user_agent, deadline=deadline
      )

      return results_of_accounts(accounts)

   return await read_personalised_typeahead(
      sender, session, query, user_agent=user_agent, deadline=deadline
   )


async def read_typeahead_accounts(
   sender: PacedSender,
   session: Session,
   query: str,
   *,
   route: TypeaheadRoute = TypeaheadRoute.PERSONALISED,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> tuple[ProfileSummary, ...]:
   """The accounts ``query`` matches on ``route``, one live request (W102)."""

   if route is TypeaheadRoute.NON_PERSONALISED:
      return await read_non_personalised_typeahead(
         sender, session, query, user_agent=user_agent, deadline=deadline
      )

   results = await read_personalised_typeahead(
      sender, session, query, user_agent=user_agent, deadline=deadline
   )

   return accounts_in_order(results)


async def read_keyword_results(
   sender: PacedSender,
   session: Session,
   query: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> KeywordResults:
   """The first page of the keyword grid for ``query``, one live request, on a page session id of
   its own (W103)."""

   refuse_what_is_not_a_query(query)
   search_session_id = new_search_session_id()

   async def attempt() -> KeywordResults:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_keyword_results_request(
         session, query, search_session_id=search_session_id, user_agent=user_agent
      )
      response = await sender.send(request)

      return parse_keyword_results(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)
