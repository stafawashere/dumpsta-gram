"""The profile requests: one account by id, a username resolved to one, and a profile page's six
queries.
"""

from __future__ import annotations

import re
from typing import Any

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, ORIGIN
from dumpstagram._private.web.documents.common import PersistedQuery
from dumpstagram._private.web.documents.profiles import (
   PROFILE_BY_ID,
   PROFILE_HIGHLIGHTS,
   PROFILE_NOTE_BUBBLE,
   PROFILE_POSTS,
   PROFILE_SCHOOL_BADGE,
   PROFILE_SUGGESTED_USERS,
)
from dumpstagram._private.web.requests.common import build_graphql_request
from dumpstagram.errors import NotFound
from dumpstagram.session import Session

__all__ = [
   "PROFILE_PAGE_POSTS",
   "RESOLUTION_PAGE_SIZE",
   "build_profile_page_requests",
   "build_profile_request",
   "build_username_resolution_request",
   "profile_page_url",
]

RESOLUTION_PAGE_SIZE = 1
"""One post is enough to read the account id off, and asking for twelve the way the web client
does would move about 200 kB to learn an eleven-digit number."""

PROFILE_PAGE_POSTS = 12
"""How many posts a profile page asks its timeline for, in both measured loads."""

_USERNAME = re.compile(r"[A-Za-z0-9._]{1,30}")


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
