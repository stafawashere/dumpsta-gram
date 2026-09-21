"""Build the GraphQL request the web client sends, byte shape included.

Ablation on 33 single-removal requests found that exactly three of roughly 38 items sent are
validated: the ``fb_dtsg`` body field, the ``sec-fetch-site`` header, and the ``content-type``
header. Everything else can be dropped without the upstream noticing.

They are sent anyway, and that is a deliberate choice rather than an oversight. A request
carrying only what is validated is a request no browser has ever sent, which makes it
trivially distinguishable from one. The three validated items are named in
:data:`VALIDATED_BODY_FIELDS` and :data:`VALIDATED_HEADERS`, and a gate fails if one stops
being sent.

``jazoest`` is computed rather than scraped: the string ``"2"`` followed by the sum of the
character codes of ``fb_dtsg``.

Nothing above this module knows any of it. ``_core`` passes an intent and typed parameters.

Finding: ``skills/reverse-engineer/knowledge/endpoints/direct-thread-message-page.md``.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, ORIGIN
from dumpstagram._private.web.documents import (
   PROFILE_BY_ID,
   THREAD_MESSAGE_PAGE,
   USER_ID_BY_USERNAME,
   PersistedQuery,
)
from dumpstagram.errors import AuthenticationFailed
from dumpstagram.session import Session

__all__ = [
   "GRAPHQL_URL",
   "PAGE_SIZE",
   "RESOLUTION_PAGE_SIZE",
   "VALIDATED_BODY_FIELDS",
   "VALIDATED_HEADERS",
   "build_graphql_request",
   "build_profile_request",
   "build_thread_page_request",
   "build_username_resolution_request",
   "jazoest_for",
]

GRAPHQL_URL = "https://www.instagram.com/api/graphql"

PAGE_SIZE = 20
"""Capped server side.

Requesting 20, 50 and 200 each returned exactly 20, so a larger number here buys nothing and
the cost of an operation is a fixed function of how much data it covers.
"""

RESOLUTION_PAGE_SIZE = 1
"""One post is enough to read the account id off, and asking for twelve the way the web client
does would move about 200 kB to learn an eleven-digit number."""

VALIDATED_BODY_FIELDS = ("fb_dtsg",)
"""The only body field the upstream was observed to check. Dropping it returns the HTML shell."""

VALIDATED_HEADERS = ("sec-fetch-site", "content-type")
"""The only headers the upstream was observed to check."""

_CONTENT_TYPE = "application/x-www-form-urlencoded"


def jazoest_for(fb_dtsg: str) -> str:
   """``"2"`` followed by the sum of the character codes of ``fb_dtsg``.

   Not a checksum the upstream verifies. It is reproduced because the browser sends it and a
   wrong or absent value is a difference a fingerprint check can read.
   """

   return "2" + str(sum(ord(character) for character in fb_dtsg))


def build_graphql_request(
   session: Session,
   query: PersistedQuery,
   variables: dict[str, Any],
   *,
   referer: str,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """One persisted-query POST, shaped the way the web client shapes it.

   Raises :class:`~dumpstagram.errors.AuthenticationFailed` when the session carries no
   ``fb_dtsg``, because sending an empty one returns the HTML application shell under HTTP
   200 and the caller would be told the schema changed.
   """

   if not session.fb_dtsg:
      raise AuthenticationFailed(
         "session has no fb_dtsg, so it has not been bootstrapped since it was loaded"
      )

   spin = session.spin
   revision = spin.revision if spin is not None else None
   branch = spin.branch if spin is not None else None
   spin_timestamp = spin.timestamp if spin is not None else None

   body = {
      "av": session.ds_user_id,
      "__d": "www",
      "__user": "0",
      "__a": "1",
      "__req": "1",
      "__hs": session.haste_session or "",
      "dpr": "2",
      "__ccg": "EXCELLENT",
      "__rev": revision or "",
      "__hsi": session.hsi or "",
      "__comet_req": "7",
      "fb_dtsg": session.fb_dtsg,
      "jazoest": jazoest_for(session.fb_dtsg),
      "lsd": session.lsd or "",
      "__spin_r": revision or "",
      "__spin_b": branch or "",
      "__spin_t": spin_timestamp or "",
      "fb_api_caller_class": "RelayModern",
      "fb_api_req_friendly_name": query.friendly_name,
      "server_timestamps": "true",
      "doc_id": query.doc_id,
      "variables": json.dumps(variables),
   }

   headers = {
      "content-type": _CONTENT_TYPE,
      "sec-fetch-site": "same-origin",
      "sec-fetch-mode": "cors",
      "sec-fetch-dest": "empty",
      "user-agent": user_agent,
      "x-ig-app-id": session.app_id or "",
      "x-csrftoken": session.csrftoken,
      "x-fb-lsd": session.lsd or "",
      "x-fb-friendly-name": query.friendly_name,
      "x-asbd-id": "359341",
      "origin": ORIGIN,
      "referer": referer,
      "accept": "*/*",
      "accept-language": "en-US,en;q=0.9",
   }

   return Request(
      method="POST",
      url=GRAPHQL_URL,
      headers=headers,
      content=urlencode(body).encode("utf-8"),
      follow_redirects=False,
   )


def build_thread_page_request(
   session: Session,
   thread_fbid: str,
   *,
   after: str | None = None,
   newer_than_message_id: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """One page of one direct thread.

   ``thread_fbid`` is the thread's ``fbid``, which is one of three ids the same thread has.
   Passing the wrong one returns an empty result rather than an error, so the identifier kind
   is part of the signature rather than something a caller works out.

   ``newer_than_message_id`` fetches only what has arrived since a message already seen,
   which is what makes a polling listener a top-up rather than a full re-read.
   """

   variables = {
      "after": after,
      "before": None,
      "first": PAGE_SIZE,
      "last": None,
      "newer_than_message_id": newer_than_message_id,
      "older_than_message_id": None,
      "id": thread_fbid,
      "__relay_internal__pv__IGDInitialMessagePageCountrelayprovider": PAGE_SIZE,
   }

   return build_graphql_request(
      session,
      THREAD_MESSAGE_PAGE,
      variables,
      referer=f"{ORIGIN}/direct/t/{thread_fbid}/",
      user_agent=user_agent,
   )


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
      "__relay_internal__pv__PolarisRepostsConsumptionEnabledrelayprovider": False,
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


def build_username_resolution_request(
   session: Session,
   username: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The account id behind a username, asked for as one post of that account's timeline.

   This is the timeline query. It is used here because it is the only call on the profile
   surface observed to accept a username, and the id comes back on the post's own author
   stub. ``count`` is one rather than the twelve the web client asks for, because the answer
   wanted is on every node equally and the rest is transfer.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/resolve-a-username-to-a-user-id.md``.
   """

   variables = {
      "data": {
         "count": RESOLUTION_PAGE_SIZE,
         "include_reel_media_seen_timestamp": False,
         "include_relationship_info": True,
         "latest_besties_reel_media": False,
         "latest_reel_media": False,
      },
      "username": username,
      "__relay_internal__pv__PolarisMultiCaptionCarouselEnabledrelayprovider": True,
      "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": False,
      "__relay_internal__pv__PolarisReelsRecoDebugOverlayEnabledrelayprovider": False,
   }

   return build_graphql_request(
      session,
      USER_ID_BY_USERNAME,
      variables,
      referer=f"{ORIGIN}/{username}/",
      user_agent=user_agent,
   )
