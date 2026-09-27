"""The explore grid, a place's header and grid, and the new posts check, asynchronously.

Each read is one request sent alone. A browser reads the explore grid and a place's two reads
inside the page loads of ``/explore/`` and ``/explore/locations/<pk>/``, and polls the new posts
check from the home page; the page loads are not modelled, a named departure from ADR-0013 as
every read before these. None of them changes anything another person can see.
"""

from __future__ import annotations

from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse.discovery import (
   parse_explore_grid,
   parse_location_info,
   parse_location_posts,
   parse_new_feed_posts,
)
from dumpstagram._private.web.requests.discovery import (
   build_explore_grid_request,
   build_location_info_request,
   build_location_posts_request,
   build_new_feed_posts_request,
   refuse_what_is_not_a_location_id,
)
from dumpstagram._private.web.requests.profiles import new_web_session_id
from dumpstagram.models import ExploreGrid, LocationPosts, LocationTab, Place
from dumpstagram.session import Session

__all__ = [
   "read_explore_grid",
   "read_location_info",
   "read_location_posts",
   "read_new_feed_posts",
]


async def read_explore_grid(
   sender: PacedSender,
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> ExploreGrid:
   """The explore grid's first page, one live request (W77).

   The GET carries no page token, so no bootstrap is spent on it, as with the followers page.
   """

   async def attempt() -> ExploreGrid:
      request = build_explore_grid_request(
         session, web_session_id=new_web_session_id(), user_agent=user_agent
      )
      response = await sender.send(request)

      return parse_explore_grid(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_location_info(
   sender: PacedSender,
   session: Session,
   location_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> Place:
   """The header of the place whose ``pk`` is ``location_id``, one live request (W78)."""

   refuse_what_is_not_a_location_id(location_id)

   async def attempt() -> Place:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_location_info_request(session, location_id, user_agent=user_agent)
      response = await sender.send(request)

      return parse_location_info(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_location_posts(
   sender: PacedSender,
   session: Session,
   location_id: str,
   *,
   tab: LocationTab = LocationTab.RANKED,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> LocationPosts:
   """The first page of the place's grid, one live request (W79)."""

   refuse_what_is_not_a_location_id(location_id)
   tab = LocationTab(tab)

   async def attempt() -> LocationPosts:
      lacks_page_tokens = not session.fb_dtsg or not session.bloks_version_id

      if lacks_page_tokens:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_location_posts_request(session, location_id, tab=tab, user_agent=user_agent)
      response = await sender.send(request)

      return parse_location_posts(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_new_feed_posts(
   sender: PacedSender,
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> bool:
   """Whether the home feed has new posts, one live request (W80)."""

   async def attempt() -> bool:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_new_feed_posts_request(session, user_agent=user_agent)
      response = await sender.send(request)

      return parse_new_feed_posts(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)
