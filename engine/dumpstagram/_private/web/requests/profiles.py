"""The profile requests: one account by id, a username resolved to one, a profile page's six
queries, a page of a profile's posts grid, its reels and tagged tabs, its highlights tray, the
suggested accounts, and a page of an account's followers or of the accounts it follows, with the
viewer's relationship to each.

The follow list pages and the relationship statuses are the first REST reads on the web API, not
GraphQL. They carry the header set the browser's follow list sent, the posting publishes' set
with ``x-ig-max-touch-points`` and ``x-web-session-id`` added, and the page, a GET, without the
three a form body brings.
"""

from __future__ import annotations

import re
import secrets
import string
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlencode

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, ORIGIN
from dumpstagram._private.web.documents.common import PersistedQuery
from dumpstagram._private.web.documents.profiles import (
   PROFILE_BY_ID,
   PROFILE_HIGHLIGHTS,
   PROFILE_NOTE_BUBBLE,
   PROFILE_POSTS,
   PROFILE_POSTS_NEXT_PAGE,
   PROFILE_REELS,
   PROFILE_SCHOOL_BADGE,
   PROFILE_SUGGESTED_USERS,
   PROFILE_TAGGED,
   SUGGESTED_ACCOUNTS,
   SUGGESTED_BESIDE_PROFILE,
)
from dumpstagram._private.web.requests.common import _USER_ID, build_graphql_request, jazoest_for
from dumpstagram.errors import AuthenticationFailed, NotFound
from dumpstagram.session import Session

__all__ = [
   "FOLLOWERS_PAGE_SIZE",
   "FOLLOWING_PAGE_SIZE",
   "PROFILE_PAGE_POSTS",
   "PROFILE_TAB_PAGE_SIZE",
   "RESOLUTION_PAGE_SIZE",
   "SUGGESTED_ACCOUNTS_SHOWN",
   "build_followers_request",
   "build_following_request",
   "build_friendship_statuses_request",
   "build_highlight_tray_request",
   "build_profile_page_requests",
   "build_profile_posts_request",
   "build_profile_reels_request",
   "build_profile_request",
   "build_profile_tagged_request",
   "build_suggested_accounts_request",
   "build_suggested_beside_profile_request",
   "build_username_resolution_request",
   "new_web_session_id",
   "profile_page_url",
   "refuse_what_is_not_a_user_id",
]

RESOLUTION_PAGE_SIZE = 1
"""One post is enough to read the account id off, and asking for twelve the way the web client
does would move about 200 kB to learn an eleven-digit number."""

PROFILE_PAGE_POSTS = 12
"""How many posts a profile page asks its timeline for, in both measured loads."""

SUGGESTED_ACCOUNTS_SHOWN = 5
"""``max_number_to_display`` on the suggested accounts list, the value the recorded browse sent."""

FOLLOWERS_PAGE_SIZE = 12
"""``count`` on a followers page, the value the browser's follow list sent."""

FOLLOWING_PAGE_SIZE = 12
"""``count`` on a page of the accounts an account follows, the value the browser's list sent on
every page."""

PROFILE_TAB_PAGE_SIZE = 12
"""``page_size`` on the reels tab and ``count`` on the tagged tab, the value a browser sent on
clicking each."""

_USERNAME = re.compile(r"[A-Za-z0-9._]{1,30}")

_FOLLOWERS_URL = "https://www.instagram.com/api/v1/friendships/{user_id}/followers/"

_FOLLOWING_URL = "https://www.instagram.com/api/v1/friendships/{user_id}/following/"

_FRIENDSHIP_STATUSES_URL = "https://www.instagram.com/api/v1/friendships/show_many/"

_FOLLOW_LIST_SURFACE = "follow_list_page"

_ASBD_ID = "359341"

_WEB_SESSION_ALPHABET = string.ascii_lowercase + string.digits


def build_profile_request(
   session: Session,
   user_id: str,
   *,
   username_for_referer: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """One account's profile, keyed on the numeric account id.

   ``user_id`` is the account's ``pk``, which the upstream also calls ``id``. It is not the
   ``fbid`` the same account carries inside a direct thread, and passing that one returns an
   error envelope rather than someone else's profile.

   The relay provider flags are sent with the values the web client sent them with on the
   measured request. They select experiment branches rather than data, and none was ablated,
   so they are reproduced rather than reasoned about.

   ``username_for_referer`` only shapes the ``referer`` header. The upstream did not validate
   it, and the profile origin is used when no username is known.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/read-a-user-profile.md``.
   """

   variables = {
      "enable_integrity_filters": True,
      "id": user_id,
      "__relay_internal__pv__PolarisCannesGuardianExperienceEnabledrelayprovider": True,
      "__relay_internal__pv__PolarisCASB976ProfileEnabledrelayprovider": False,
      "__relay_internal__pv__PolarisWebSchoolsEnabledrelayprovider": False,
      "__relay_internal__pv__PolarisRepostsConsumptionEnabledrelayprovider": True,
      "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": False,
   }

   referer = f"{ORIGIN}/{username_for_referer}/" if username_for_referer else f"{ORIGIN}/"

   return build_graphql_request(
      session,
      PROFILE_BY_ID,
      variables,
      referer=referer,
      user_agent=user_agent,
   )


def _profile_posts_variables(username: str, count: int) -> dict[str, Any]:
   return {
      "data": {
         "count": count,
         "include_reel_media_seen_timestamp": True,
         "include_relationship_info": True,
         "latest_besties_reel_media": True,
         "latest_reel_media": True,
      },
      "username": username,
      "__relay_internal__pv__PolarisMultiCaptionCarouselEnabledrelayprovider": True,
      "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": False,
      "__relay_internal__pv__PolarisReelsRecoDebugOverlayEnabledrelayprovider": False,
   }


def build_username_resolution_request(
   session: Session,
   username: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The account id behind a username, asked for as one post of that account's timeline.

   This is the timeline query a profile page sends, used here for its ``username`` argument
   when a client departs from the page route, and the id comes back on the post's own author
   stub. ``count`` is one rather than the twelve the page asks for, because the answer wanted
   is on every node equally and the rest is transfer.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/resolve-a-username-to-a-user-id.md``.
   """

   return build_graphql_request(
      session,
      PROFILE_POSTS,
      _profile_posts_variables(username, RESOLUTION_PAGE_SIZE),
      referer=f"{ORIGIN}/{username}/",
      user_agent=user_agent,
   )


def profile_page_url(username: str) -> str:
   """The profile page a browser navigates to for ``username``.

   The username becomes a path segment here, so anything outside the characters an Instagram
   username can hold is refused before it is sent, as an account that cannot exist.
   """

   is_a_possible_username = _USERNAME.fullmatch(username) is not None

   if not is_a_possible_username:
      raise NotFound(f"{username!r} cannot be an Instagram username")

   return f"{ORIGIN}/{username}/"


def build_profile_page_requests(
   session: Session,
   user_id: str,
   username: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> list[Request]:
   """The six queries a profile page sends once its document has loaded, in the page's order.

   Both measured cold loads sent all six within 5 ms of each other, keyed on the account id the
   document carried, with the profile page as the referer. The profile query comes first, and
   it is the only one whose answer the capability reads. The other five are sent because the
   page sends them.

   Findings: ``read-a-user-profile``, ``profile-page-note-bubble``,
   ``profile-page-story-highlights``, ``profile-page-suggested-users``,
   ``profile-page-school-badge`` and ``resolve-a-username-to-a-user-id``.
   """

   referer = profile_page_url(username)
   profile = build_profile_request(
      session, user_id, username_for_referer=username, user_agent=user_agent
   )

   companions: list[tuple[PersistedQuery, dict[str, Any]]] = [
      (PROFILE_NOTE_BUBBLE, {"user_id": user_id}),
      (PROFILE_HIGHLIGHTS, {"user_id": user_id}),
      (PROFILE_SUGGESTED_USERS, {"module": "profile", "target_id": user_id}),
      (PROFILE_SCHOOL_BADGE, {"igid": user_id}),
      (PROFILE_POSTS, _profile_posts_variables(username, PROFILE_PAGE_POSTS)),
   ]

   companion_requests = [
      build_graphql_request(session, query, variables, referer=referer, user_agent=user_agent)
      for query, variables in companions
   ]

   return [profile, *companion_requests]


def refuse_what_is_not_a_user_id(user_id: str) -> None:
   """Raise :class:`ValueError` for anything but digits, before anything is built or sent.

   The tray and the suggestions are keyed on the numeric account id, and what they answer for a
   username is unobserved.
   """

   is_a_user_id = _USER_ID.fullmatch(user_id) is not None

   if not is_a_user_id:
      raise ValueError(f"{user_id!r} is not a numeric account id. Pass Profile.id, not a username")


def _profile_posts_next_page_variables(username: str, after: str) -> dict[str, Any]:
   return {
      "after": after,
      "before": None,
      "data": {
         "count": PROFILE_PAGE_POSTS,
         "include_reel_media_seen_timestamp": True,
         "include_relationship_info": True,
         "latest_besties_reel_media": True,
         "latest_reel_media": True,
      },
      "first": PROFILE_PAGE_POSTS,
      "include_multi_captions": True,
      "last": None,
      "username": username,
      "__relay_internal__pv__PolarisMultiCaptionCarouselEnabledrelayprovider": True,
      "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": False,
      "__relay_internal__pv__PolarisReelsRecoDebugOverlayEnabledrelayprovider": False,
   }


def build_profile_posts_request(
   session: Session,
   username: str,
   *,
   after: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """One page of a profile's posts grid, twelve posts, keyed on the username.

   The first page is the timeline query a profile page sends among its six, with the page's
   variables. Every later page is ``PolarisProfilePostsTabContentQuery_connection``, which takes
   the same ``data`` and ``username`` with the previous page's ``end_cursor`` as ``after``, and
   the connection arguments its compiled artifact declares. Both have the profile page as their
   referer. The username is not checked here, as :func:`build_username_resolution_request` does
   not check it; the capability refuses one that cannot be a username with
   :func:`profile_page_url` before anything is built.

   Findings: ``resolve-a-username-to-a-user-id`` and ``profile-posts-grid-next-page``.
   """

   referer = f"{ORIGIN}/{username}/"

   if after is None:
      query = PROFILE_POSTS
      variables = _profile_posts_variables(username, PROFILE_PAGE_POSTS)
   else:
      query = PROFILE_POSTS_NEXT_PAGE
      variables = _profile_posts_next_page_variables(username, after)

   return build_graphql_request(session, query, variables, referer=referer, user_agent=user_agent)


def build_highlight_tray_request(
   session: Session,
   user_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The highlights tray on one account's profile, keyed on the numeric account id.

   The account id is not checked here; the capability refuses anything but digits with
   :func:`refuse_what_is_not_a_user_id` before anything is built. The variables are the ones a
   profile page sends. The page's referer is the profile page, which
   needs the username the caller did not give, so the site root is sent, as
   :func:`build_profile_request` does when it has no username. The profile query's referer was
   not validated; this one's has not been tested.

   Finding: ``profile-page-story-highlights``.
   """

   return build_graphql_request(
      session,
      PROFILE_HIGHLIGHTS,
      {"user_id": user_id},
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )


def build_suggested_beside_profile_request(
   session: Session,
   user_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The accounts suggested beside one account's profile, asked for on demand.

   The variables are the ones the recorded browse sent and the preloaded query a profile page
   sends carries. The referer is the site root, for the reason
   :func:`build_highlight_tray_request` gives.

   Finding: ``profile-suggested-users-on-demand``.
   """

   return build_graphql_request(
      session,
      SUGGESTED_BESIDE_PROFILE,
      {"module": "profile", "target_id": user_id},
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )


def build_suggested_accounts_request(
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The suggested accounts list, as the recorded browse asked for it, with the site root as the
   referer.

   Finding: ``home-suggested-accounts``.
   """

   variables = {
      "data": {
         "max_id": "",
         "max_number_to_display": SUGGESTED_ACCOUNTS_SHOWN,
         "module": "discover_people",
         "paginate": True,
      }
   }

   return build_graphql_request(
      session, SUGGESTED_ACCOUNTS, variables, referer=f"{ORIGIN}/", user_agent=user_agent
   )


def new_web_session_id() -> str:
   """A fresh ``x-web-session-id``: three groups of six lowercase letters and digits.

   The browser carried one value on every request of its page session that sent the header, so
   a capability draws one per read and sends it on each request of that read.
   """

   groups = ("".join(secrets.choice(_WEB_SESSION_ALPHABET) for _ in range(6)) for _ in range(3))

   return ":".join(groups)


def _rest_read_headers(session: Session, web_session_id: str, user_agent: str) -> dict[str, str]:
   return {
      "accept": "*/*",
      "accept-language": "en-US,en;q=0.9",
      "referer": f"{ORIGIN}/",
      "sec-fetch-dest": "empty",
      "sec-fetch-mode": "cors",
      "sec-fetch-site": "same-origin",
      "user-agent": user_agent,
      "x-asbd-id": _ASBD_ID,
      "x-csrftoken": session.csrftoken,
      "x-ig-app-id": session.app_id or "",
      "x-ig-max-touch-points": "0",
      "x-requested-with": "XMLHttpRequest",
      "x-web-session-id": web_session_id,
   }


def build_followers_request(
   session: Session,
   user_id: str,
   *,
   web_session_id: str,
   after: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """One page of an account's followers, keyed on the numeric account id in the path.

   The first page carries ``count`` and ``search_surface`` as the browser's follow list sent
   them. A later page carries the same two and ``max_id``, the previous page's
   ``next_max_id``, which answered the next accounts with no overlap on both replays. The
   browser's referer was the profile page, which needs the username the caller did not give, so
   the site root is sent, as :func:`build_highlight_tray_request` does. The account id is not
   checked here; the capability refuses anything but digits first.

   Finding: ``read-an-account-s-followers``.
   """

   params = {"count": str(FOLLOWERS_PAGE_SIZE), "search_surface": _FOLLOW_LIST_SURFACE}

   return _follow_list_page_request(
      session,
      _FOLLOWERS_URL.format(user_id=user_id),
      params,
      after=after,
      web_session_id=web_session_id,
      user_agent=user_agent,
   )


def build_following_request(
   session: Session,
   user_id: str,
   *,
   web_session_id: str,
   after: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """One page of the accounts an account follows, keyed on the numeric account id in the path.

   The followers page's twin with one difference the browser made: ``count`` alone, and no
   ``search_surface``. A later page carries ``max_id``, the previous page's ``next_max_id``,
   which on this list is a numeric offset as a string. The referer is the site root, for the
   reason :func:`build_followers_request` gives. The account id is not checked here.

   Finding: ``read-an-account-s-following``.
   """

   params = {"count": str(FOLLOWING_PAGE_SIZE)}

   return _follow_list_page_request(
      session,
      _FOLLOWING_URL.format(user_id=user_id),
      params,
      after=after,
      web_session_id=web_session_id,
      user_agent=user_agent,
   )


def _follow_list_page_request(
   session: Session,
   url: str,
   params: dict[str, str],
   *,
   after: str | None,
   web_session_id: str,
   user_agent: str,
) -> Request:
   if after is not None:
      params["max_id"] = after

   return Request(
      method="GET",
      url=url,
      headers=_rest_read_headers(session, web_session_id, user_agent),
      params=params,
      follow_redirects=False,
   )


def build_profile_reels_request(
   session: Session,
   user_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The first page of a profile's reels tab, keyed on the numeric account id.

   The variables are the ones a browser sent on clicking the tab: the id twice, as
   ``data.target_user_id`` and as ``user_id``, a page size of twelve, and two constants. A
   browser's referer is the profile page, which needs the username the caller did not give, so the
   site root is sent, as :func:`build_highlight_tray_request` does. The account id is not checked
   here; the capability refuses anything but digits first.

   Finding: ``read-a-profile-s-reels-tab``.
   """

   variables = {
      "data": {
         "include_feed_video": True,
         "page_size": PROFILE_TAB_PAGE_SIZE,
         "target_user_id": user_id,
      },
      "user_id": user_id,
      "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": False,
   }

   return build_graphql_request(
      session, PROFILE_REELS, variables, referer=f"{ORIGIN}/", user_agent=user_agent
   )


def build_profile_tagged_request(
   session: Session,
   user_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The first page of a profile's tagged tab, keyed on the numeric account id.

   The variables are the ones a browser sent on clicking the tab, and the referer is the site
   root for the reason :func:`build_profile_reels_request` gives.

   Finding: ``read-a-profile-s-tagged-tab``.
   """

   variables = {
      "count": PROFILE_TAB_PAGE_SIZE,
      "user_id": user_id,
      "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": False,
   }

   return build_graphql_request(
      session, PROFILE_TAGGED, variables, referer=f"{ORIGIN}/", user_agent=user_agent
   )


def build_friendship_statuses_request(
   session: Session,
   account_ids: Sequence[str],
   *,
   web_session_id: str,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The viewer's relationship to each of ``account_ids``, one POST that changes nothing.

   The body is the browser's, ``user_ids`` joined by commas in the page's order and then the
   page token, and the headers are the followers page's with the three a form POST adds.

   Finding: ``friendship-statuses-for-many-accounts``.
   """

   token = session.fb_dtsg

   if not token:
      raise AuthenticationFailed(
         "session has no fb_dtsg, so it has not been bootstrapped since it was loaded"
      )

   spin = session.spin
   revision = (spin.revision if spin is not None else None) or ""
   fields = {"user_ids": ",".join(account_ids), "jazoest": jazoest_for(token), "fb_dtsg": token}
   headers = {
      **_rest_read_headers(session, web_session_id, user_agent),
      "content-type": "application/x-www-form-urlencoded",
      "origin": ORIGIN,
      "x-instagram-ajax": revision,
   }

   return Request(
      method="POST",
      url=_FRIENDSHIP_STATUSES_URL,
      headers=headers,
      content=urlencode(fields).encode("utf-8"),
      follow_redirects=False,
   )
