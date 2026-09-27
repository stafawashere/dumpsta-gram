"""The recent searches, the non-personalised typeahead and a hashtag's header, asynchronously.

Each read is one request sent alone. A browser reads the recent searches when the search panel
opens, the typeahead as the viewer types, and the hashtag header inside the load of
``/explore/tags/<tag>/``; the panel and the page load are not modelled, a named departure from
ADR-0013 as every read before these. None of them changes anything another person can see.
"""

from __future__ import annotations

from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse.search import (
   parse_hashtag_header,
   parse_non_personalised_typeahead,
   parse_recent_searches,
)
from dumpstagram._private.web.requests.search import (
   build_hashtag_header_request,
   build_non_personalised_typeahead_request,
   build_recent_searches_request,
   refuse_what_is_not_a_query,
   refuse_what_is_not_a_tag,
)
from dumpstagram.models import Hashtag, ProfileSummary, RecentSearch
from dumpstagram.session import Session

__all__ = [
   "read_hashtag_header",
   "read_non_personalised_typeahead",
   "read_recent_searches",
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
