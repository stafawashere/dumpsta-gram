"""The profile capability, written once, asynchronously.

Both public surfaces call this. ``SyncClient`` reaches it across the loop thread and
``AsyncClient`` awaits it directly, and neither adds behavior on the way, which is what
ADR-0001 means by one implementation and two doors.

Nothing here knows the upstream speaks GraphQL. The adapter in `_private/web/` owns the
document ids, the variables and the field names, and hands back typed models.

The shape of this capability is set by the surface rather than by taste. The profile query
takes an account id and nothing else. A browser gets the id from the profile page it loads,
and :attr:`ProfileRoute.PAGE` does the same, sending the page's six queries at once as one
action. :attr:`ProfileRoute.QUERIES` resolves the id through a timeline query instead, which is
the departure. A caller that already holds an id reads the profile query alone, since no
browser page is keyed on an id.

The six queries are the one place in ``_core`` that sends concurrently. ADR-0001 keeps the core
serial unless concurrency is known to help, and here it is what makes the requests look like
the page's: both measured loads sent all six within 5 ms.

Since E2 batch 2 the profile's tabs are read here too: a page of the posts grid, the highlights
tray, and the accounts suggested beside the profile or on the suggested accounts list. Each is
one query sent alone, and the departures that makes are recorded in W53 to W55. Since E2 batch 3
an account's followers are read a page at a time, each page followed inside its action by the
viewer's relationship to the accounts on it, as the browser's follow list does (W58 to W60).
Since E2 batch 11a the reels and tagged tabs are read the same way as the grid's first page, one
query sent alone, and the accounts an account follows are read as its followers are (W97 to W100).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from dumpstagram._core.cookie_sync import CookieSync
from dumpstagram._core.pacer import run_with_retries
from dumpstagram._core.page_load import raise_only_what_concerns_the_account, send_companions
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import (
   DEFAULT_USER_AGENT,
   apply_tokens,
   bootstrap,
   build_document_request,
   tokens_from,
)
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse.profiles import (
   attach_friendship_statuses,
   parse_followers_page,
   parse_following_page,
   parse_friendship_statuses,
   parse_highlight_tray,
   parse_mutual_followers_page,
   parse_profile,
   parse_profile_posts_page,
   parse_profile_reels,
   parse_suggested_accounts,
   parse_suggested_beside_profile,
   parse_tagged_posts,
   parse_user_id,
)
from dumpstagram._private.web.preload import read_iris_device_id, read_profile_id
from dumpstagram._private.web.requests.page_load import build_profile_page_load_companions
from dumpstagram._private.web.requests.profiles import (
   build_followers_request,
   build_following_request,
   build_friendship_statuses_request,
   build_highlight_tray_request,
   build_mutual_followers_request,
   build_profile_page_requests,
   build_profile_posts_request,
   build_profile_reels_request,
   build_profile_request,
   build_profile_tagged_request,
   build_suggested_accounts_request,
   build_suggested_beside_profile_request,
   build_username_resolution_request,
   new_web_session_id,
   profile_page_url,
   refuse_what_is_not_a_user_id,
)
from dumpstagram.behavior import ProfileRoute
from dumpstagram.errors import NotFound
from dumpstagram.models import (
   HighlightTray,
   MutualFollowers,
   Page,
   Post,
   Profile,
   ProfileReels,
   ProfileSummary,
   SuggestedAccount,
   TaggedPosts,
)
from dumpstagram.session import Session

__all__ = [
   "read_followers_page",
   "read_following_page",
   "read_highlight_tray",
   "read_mutual_followers",
   "read_profile",
   "read_profile_by_id",
   "read_profile_from_page",
   "read_profile_posts_page",
   "read_profile_reels",
   "read_suggested_accounts",
   "read_suggested_beside_profile",
   "read_tagged_posts",
   "resolve_username",
]


async def resolve_username(
   sender: PacedSender,
   session: Session,
   username: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> str:
   """The numeric account id behind ``username``, in one live request.

   Raises :class:`~dumpstagram.errors.NotFound` when the upstream answers with an empty
   timeline. That covers an account that does not exist and an account whose posts the viewer
   cannot see, and the upstream does not distinguish the two on this route, so neither does
   this. An account that genuinely has no posts is reachable by id and not by username.
   """

   async def attempt() -> str:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_username_resolution_request(session, username, user_agent=user_agent)
      response = await sender.send(request)
      user_id = parse_user_id(classify(response))

      if user_id is None:
         raise NotFound(
            f"no account id came back for {username!r}, which means the account does not "
            "exist, its posts are not visible to this session, or it has none"
         )

      return user_id

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_profile_by_id(
   sender: PacedSender,
   session: Session,
   user_id: str,
   *,
   username_for_referer: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> Profile:
   """One account's profile, in one live request, keyed on the numeric account id."""

   async def attempt() -> Profile:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_profile_request(
         session,
         user_id,
         username_for_referer=username_for_referer,
         user_agent=user_agent,
      )
      response = await sender.send(request)

      return parse_profile(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_profile(
   sender: PacedSender,
   session: Session,
   username: str,
   *,
   route: ProfileRoute = ProfileRoute.QUERIES,
   companions: bool = False,
   cookie_sync: CookieSync | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> Profile:
   """One account's profile, found by username.

   Under :attr:`ProfileRoute.QUERIES` that is two live requests, serial because the second
   needs the first one's answer. Under :attr:`ProfileRoute.PAGE` it is the page load
   :func:`read_profile_from_page` describes, and ``companions`` and ``cookie_sync`` apply only
   there. ``QUERIES``
   and no companions stay the defaults at this level so callers below the client keep the
   requests they had, and the client passes its behavior down.
   """

   if route is ProfileRoute.PAGE:
      return await read_profile_from_page(
         sender,
         session,
         username,
         companions=companions,
         cookie_sync=cookie_sync,
         user_agent=user_agent,
         deadline=deadline,
      )

   user_id = await resolve_username(
      sender, session, username, user_agent=user_agent, deadline=deadline
   )

   return await read_profile_by_id(
      sender,
      session,
      user_id,
      username_for_referer=username,
      user_agent=user_agent,
      deadline=deadline,
   )


async def read_profile_from_page(
   sender: PacedSender,
   session: Session,
   username: str,
   *,
   companions: bool = False,
   cookie_sync: CookieSync | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> Profile:
   """One account's profile, read the way a browser's profile page reads it.

   One action: the profile page document, then its six queries at once, then with
   ``companions`` the page load companions ``_core/page_load.py`` sends. The document needs no
   page token and carries fresh ones, which are written onto the session before the queries
   are built, so there is no stale token to recover from.

   Raises :class:`~dumpstagram.errors.NotFound` when the page is about no account, which is
   how the upstream answered for a username nobody holds. Unlike the timeline route, an
   account with no visible posts is found.

   Only the profile query's answer is read. The other five are checked for a checkpoint or a
   throttle, which concern the whole account, and otherwise left alone, so a companion the
   upstream stops answering does not cost the caller the profile.

   With ``cookie_sync`` a successful load schedules the page's cookie sync tail, timed from the
   document's departure. A load that raises schedules none.
   """

   page_url = profile_page_url(username)

   async def attempt() -> Profile:
      async with sender.action() as action:
         loaded_at = sender.pacer.now()
         document = await action.send(build_document_request(page_url, user_agent))

         apply_tokens(session, tokens_from(document))
         user_id = read_profile_id(document.text)

         if user_id is None:
            raise NotFound(f"no account has the username {username!r}")

         requests = build_profile_page_requests(session, user_id, username, user_agent=user_agent)
         profile_response, *companion_responses = await action.send_together(requests)

         for companion in companion_responses:
            raise_only_what_concerns_the_account(companion)

         if companions:
            groups = build_profile_page_load_companions(
               session,
               user_id,
               username,
               device_id=read_iris_device_id(document.text),
               user_agent=user_agent,
            )
            await send_companions(action, groups)

      profile = parse_profile(classify(profile_response))

      if cookie_sync is not None:
         cookie_sync.start(session, page_url, loaded_at=loaded_at, user_agent=user_agent)

      return profile

   return await run_with_retries(attempt, pacer=sender.pacer, deadline=deadline)


async def read_profile_posts_page(
   sender: PacedSender,
   session: Session,
   username: str,
   *,
   after: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> Page[Post]:
   """One page of a profile's posts grid, one live request, the first when ``after`` is None.

   The first page is sent alone rather than inside the profile page load it belongs to, a
   recorded departure (W53). A later page is what a browser sends as the grid is scrolled.
   """

   profile_page_url(username)

   async def attempt() -> Page[Post]:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_profile_posts_request(session, username, after=after, user_agent=user_agent)
      response = await sender.send(request)

      return parse_profile_posts_page(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_highlight_tray(
   sender: PacedSender,
   session: Session,
   user_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> HighlightTray:
   """One account's highlights tray, its first page, one live request, sent alone (W54)."""

   refuse_what_is_not_a_user_id(user_id)

   async def attempt() -> HighlightTray:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_highlight_tray_request(session, user_id, user_agent=user_agent)
      response = await sender.send(request)

      return parse_highlight_tray(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_suggested_beside_profile(
   sender: PacedSender,
   session: Session,
   user_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> tuple[ProfileSummary, ...]:
   """The accounts suggested beside one account's profile, one live request (W55)."""

   refuse_what_is_not_a_user_id(user_id)

   async def attempt() -> tuple[ProfileSummary, ...]:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_suggested_beside_profile_request(session, user_id, user_agent=user_agent)
      response = await sender.send(request)

      return parse_suggested_beside_profile(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_suggested_accounts(
   sender: PacedSender,
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> tuple[SuggestedAccount, ...]:
   """The suggested accounts list, one live request (W55)."""

   async def attempt() -> tuple[SuggestedAccount, ...]:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_suggested_accounts_request(session, user_agent=user_agent)
      response = await sender.send(request)

      return parse_suggested_accounts(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_followers_page(
   sender: PacedSender,
   session: Session,
   user_id: str,
   *,
   after: str | None = None,
   with_statuses: bool = True,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> Page[ProfileSummary]:
   """One page of an account's followers, one action of one or two live requests.

   The page is read first, then, when ``with_statuses`` is on and the page lists anyone, the
   viewer's relationship to every account on it, which fills each row's ``friendship_status``.
   A bootstrap is needed only for the second request, which carries the page token.
   """

   return await _read_follow_list_page(
      sender,
      session,
      user_id,
      build_page=build_followers_request,
      parse_page=parse_followers_page,
      after=after,
      with_statuses=with_statuses,
      user_agent=user_agent,
      deadline=deadline,
   )


async def read_following_page(
   sender: PacedSender,
   session: Session,
   user_id: str,
   *,
   after: str | None = None,
   with_statuses: bool = True,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> Page[ProfileSummary]:
   """One page of the accounts an account follows, one action of one or two live requests, the
   followers page's twin in every step (W99)."""

   return await _read_follow_list_page(
      sender,
      session,
      user_id,
      build_page=build_following_request,
      parse_page=parse_following_page,
      after=after,
      with_statuses=with_statuses,
      user_agent=user_agent,
      deadline=deadline,
   )


async def _read_follow_list_page(
   sender: PacedSender,
   session: Session,
   user_id: str,
   *,
   build_page: Callable[..., Request],
   parse_page: Callable[[Any], Page[ProfileSummary]],
   after: str | None,
   with_statuses: bool,
   user_agent: str,
   deadline: float | None,
) -> Page[ProfileSummary]:
   refuse_what_is_not_a_user_id(user_id)

   async def attempt() -> Page[ProfileSummary]:
      needs_a_token = with_statuses and not session.fb_dtsg

      if needs_a_token:
         await bootstrap(sender, session, user_agent=user_agent)

      web_session_id = new_web_session_id()

      async with sender.action() as action:
         page_request = build_page(
            session, user_id, after=after, web_session_id=web_session_id, user_agent=user_agent
         )
         page = parse_page(classify(await action.send(page_request)))
         asks_for_statuses = with_statuses and bool(page.items)

         if not asks_for_statuses:
            return page

         statuses_request = build_friendship_statuses_request(
            session,
            [account.id for account in page.items],
            web_session_id=web_session_id,
            user_agent=user_agent,
         )
         statuses = parse_friendship_statuses(classify(await action.send(statuses_request)))

      return attach_friendship_statuses(page, statuses)

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_mutual_followers(
   sender: PacedSender,
   session: Session,
   user_id: str,
   *,
   with_statuses: bool = True,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> MutualFollowers:
   """The first page of the accounts following both the viewer and ``user_id``, one action of one
   or two live requests, the follow lists' steps (W117).

   The page is read first, then, when ``with_statuses`` is on and the page lists anyone, the
   viewer's relationship to every account on it, as the browser's list sent it beside the page.
   """

   def build_page(
      session: Session,
      user_id: str,
      *,
      after: str | None,
      web_session_id: str,
      user_agent: str,
   ) -> Request:
      return build_mutual_followers_request(
         session, user_id, web_session_id=web_session_id, user_agent=user_agent
      )

   page = await _read_follow_list_page(
      sender,
      session,
      user_id,
      build_page=build_page,
      parse_page=parse_mutual_followers_page,
      after=None,
      with_statuses=with_statuses,
      user_agent=user_agent,
      deadline=deadline,
   )

   return MutualFollowers(accounts=page.items, has_more=page.has_next_page)


async def read_profile_reels(
   sender: PacedSender,
   session: Session,
   user_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> ProfileReels:
   """One account's reels tab, its first page, one live request, sent alone (W97)."""

   refuse_what_is_not_a_user_id(user_id)

   async def attempt() -> ProfileReels:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_profile_reels_request(session, user_id, user_agent=user_agent)
      response = await sender.send(request)

      return parse_profile_reels(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_tagged_posts(
   sender: PacedSender,
   session: Session,
   user_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> TaggedPosts:
   """One account's tagged tab, its first page, one live request, sent alone (W98)."""

   refuse_what_is_not_a_user_id(user_id)

   async def attempt() -> TaggedPosts:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_profile_tagged_request(session, user_id, user_agent=user_agent)
      response = await sender.send(request)

      return parse_tagged_posts(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)
