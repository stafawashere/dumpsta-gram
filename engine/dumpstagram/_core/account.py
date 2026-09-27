"""The viewer's own pending follow requests, activity feed, saved posts and collections, and
close friends list, asynchronously.

Each read is one REST request sent alone, where a browser sends both inside its direct inbox
load, and marks nothing seen. A browser's inbox load follows the activity feed with
``news/inbox_seen``, which clears the viewer's own notifications badge; that request has never
been sent or observed answering, so the engine does not send it, W74's named departure from
ADR-0013 until a verified finding exists.

The close friends list is read from the settings screen's Bloks app fetch, sent once. A browser's
page load sends the fetch twice, the settings side menu query before it and a
``close_friend_count_updater`` action after it, whose effect is UNRESOLVED; none of those three
is sent (W107).

The blocked list is the settings screen's two Bloks fetches in one action, the screen's app and
then the reloader action its answer names, as the page sends both on load with no click (W110).
"""

from __future__ import annotations

from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse.account import (
   parse_activity_feed,
   parse_blocked_accounts,
   parse_blocked_accounts_screen,
   parse_close_friends,
   parse_follow_requests,
   parse_saved_collections,
   parse_saved_posts,
)
from dumpstagram._private.web.requests.account import (
   build_activity_feed_request,
   build_blocked_accounts_reloader_request,
   build_blocked_accounts_screen_request,
   build_close_friends_request,
   build_follow_requests_request,
   build_saved_collections_request,
   build_saved_posts_request,
)
from dumpstagram._private.web.requests.profiles import new_web_session_id
from dumpstagram.models import (
   ActivityFeed,
   BlockedAccount,
   FollowRequests,
   ProfileSummary,
   SavedCollections,
   SavedPosts,
)
from dumpstagram.session import Session

__all__ = [
   "read_activity_feed",
   "read_blocked_accounts",
   "read_close_friends",
   "read_follow_requests",
   "read_saved_collections",
   "read_saved_posts",
]


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


async def read_saved_posts(
   sender: PacedSender,
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> SavedPosts:
   """The first page of the viewer's saved "All posts" view, one live request (W105).

   The GET carries no page token, so no bootstrap is spent on it, as with the follow requests.
   """

   async def attempt() -> SavedPosts:
      request = build_saved_posts_request(
         session, web_session_id=new_web_session_id(), user_agent=user_agent
      )
      response = await sender.send(request)

      return parse_saved_posts(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_saved_collections(
   sender: PacedSender,
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> SavedCollections:
   """The viewer's saved tab, its first page, one live request and a bootstrap when no token is
   held (W106)."""

   async def attempt() -> SavedCollections:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_saved_collections_request(session, user_agent=user_agent)
      response = await sender.send(request)

      return parse_saved_collections(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_close_friends(
   sender: PacedSender,
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> tuple[ProfileSummary, ...]:
   """The viewer's close friends, one live request and a bootstrap when the session holds no page
   token or no Bloks version id (W107)."""

   async def attempt() -> tuple[ProfileSummary, ...]:
      lacks_page_tokens = not session.fb_dtsg or not session.bloks_version_id

      if lacks_page_tokens:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_close_friends_request(session, user_agent=user_agent)
      response = await sender.send(request)

      return parse_close_friends(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_blocked_accounts(
   sender: PacedSender,
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> tuple[BlockedAccount, ...]:
   """The accounts the viewer has blocked, two live requests in one action and a bootstrap when
   the session holds no page token or no Bloks version id (W110).

   The screen's answer names the two container ids the reloader action takes, so the action is
   built from it and sent in the same slot, as the page sends it about 170 ms later.
   """

   async def attempt() -> tuple[BlockedAccount, ...]:
      lacks_page_tokens = not session.fb_dtsg or not session.bloks_version_id

      if lacks_page_tokens:
         await bootstrap(sender, session, user_agent=user_agent)

      async with sender.action() as action:
         screen_request = build_blocked_accounts_screen_request(session, user_agent=user_agent)
         screen = await action.send(screen_request)
         containers = parse_blocked_accounts_screen(classify(screen))
         reloader_request = build_blocked_accounts_reloader_request(
            session,
            list_id=containers.list_id,
            rows_id=containers.rows_id,
            user_agent=user_agent,
         )
         answer = await action.send(reloader_request)

      return parse_blocked_accounts(classify(answer), containers)

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)
