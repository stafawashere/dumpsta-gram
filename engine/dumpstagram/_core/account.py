"""The viewer's own pending follow requests and activity feed, asynchronously.

Each read is one REST request sent alone, where a browser sends both inside its direct inbox
load, and marks nothing seen. A browser's inbox load follows the activity feed with
``news/inbox_seen``, which clears the viewer's own notifications badge; that request has never
been sent or observed answering, so the engine does not send it, W74's named departure from
ADR-0013 until a verified finding exists.
"""

from __future__ import annotations

from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse.account import parse_activity_feed, parse_follow_requests
from dumpstagram._private.web.requests.account import (
   build_activity_feed_request,
   build_follow_requests_request,
)
from dumpstagram._private.web.requests.profiles import new_web_session_id
from dumpstagram.models import ActivityFeed, FollowRequests
from dumpstagram.session import Session

__all__ = ["read_activity_feed", "read_follow_requests"]


async def read_follow_requests(
   sender: PacedSender,
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> FollowRequests:
   """The accounts asking to follow the viewer, one live request (W73).

   The GET carries no page token, so no bootstrap is spent on it, as with the followers page.
   """

   async def attempt() -> FollowRequests:
      request = build_follow_requests_request(
         session, web_session_id=new_web_session_id(), user_agent=user_agent
      )
      response = await sender.send(request)

      return parse_follow_requests(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_activity_feed(
   sender: PacedSender,
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> ActivityFeed:
   """The viewer's activity feed, one live request and a bootstrap when no token is held (W74)."""

   async def attempt() -> ActivityFeed:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_activity_feed_request(
         session, web_session_id=new_web_session_id(), user_agent=user_agent
      )
      response = await sender.send(request)

      return parse_activity_feed(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)
