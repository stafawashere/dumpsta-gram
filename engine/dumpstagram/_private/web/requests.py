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

Each query names the path it answers on, because two were observed and posting to the wrong
one returns HTTP 200 with a null root field and no error envelope. See
:class:`~dumpstagram._private.web.documents.PersistedQuery`.

Finding: ``skills/reverse-engineer/knowledge/endpoints/direct-thread-message-page.md``.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlencode

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, ORIGIN
from dumpstagram._private.web.documents import (
   BADGE_COUNT,
   CHAT_TABS_JEWEL,
   HOME_TIMELINE_FEED,
   OMNI_PICKER_NULL_STATE,
   PROFILE_BY_ID,
   PROFILE_HIGHLIGHTS,
   PROFILE_NOTE_BUBBLE,
   PROFILE_POSTS,
   PROFILE_SCHOOL_BADGE,
   PROFILE_SUGGESTED_USERS,
   QUICK_PROMOTION,
   STORIES_TRAY,
   THREAD_DETAIL,
   THREAD_MESSAGE_PAGE,
   THREAD_OLDER_PAGE,
   PersistedQuery,
)
from dumpstagram.errors import AuthenticationFailed, NotFound, SchemaChanged
from dumpstagram.session import Session

__all__ = [
   "FEED_DEVICE_ID",
   "FEED_PAGE_SIZE",
   "PAGE_SIZE",
   "PROFILE_PAGE_POSTS",
   "RESOLUTION_PAGE_SIZE",
   "VALIDATED_BODY_FIELDS",
   "VALIDATED_HEADERS",
   "build_feed_page_request",
   "build_graphql_request",
   "build_home_page_load_companions",
   "build_profile_page_load_companions",
   "build_profile_page_requests",
   "build_profile_request",
   "build_thread_detail_request",
   "build_thread_older_page_request",
   "build_thread_page_request",
   "build_username_resolution_request",
   "jazoest_for",
   "profile_page_url",
   "thread_url",
]

PAGE_SIZE = 20
"""Capped server side.

Requesting 20, 50 and 200 each returned exactly 20, so a larger number here buys nothing and
the cost of an operation is a fixed function of how much data it covers.
"""

RESOLUTION_PAGE_SIZE = 1
"""One post is enough to read the account id off, and asking for twelve the way the web client
does would move about 200 kB to learn an eleven-digit number."""

PROFILE_PAGE_POSTS = 12
"""How many posts a profile page asks its timeline for, in both measured loads."""

_USERNAME = re.compile(r"[A-Za-z0-9._]{1,30}")

FEED_PAGE_SIZE = 12
"""What the web client asks the timeline for, and advisory rather than binding.

Three observations of this exact value returned 14, 12 and 5 edges, so the number shapes the
request and predicts nothing about the answer. The web client's value is sent because a
different one is a difference a fingerprint check can read, and because no other value has
been measured.
"""

FEED_DEVICE_ID = "0905A51C-CD35-4174-84B3-5E0C764E353B"
"""The ``device_id`` the timeline query carries.

Not a device fingerprint and not derived from anything local. It is one opaque value observed
on the measured request, reproduced because the field is required to be present and only this
value has ever been sent. Whether the upstream validates it at all is unmeasured, which is why
it is a constant here rather than something generated per session.
"""

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

   A query on ``/graphql/query`` also carries ``x-bloks-version-id`` and
   ``x-root-field-name``, and raises :class:`~dumpstagram.errors.SchemaChanged` when the session
   has no bloks version id, because the bootstrap page stopped carrying it.
   """

   if not session.fb_dtsg:
      raise AuthenticationFailed(
         "session has no fb_dtsg, so it has not been bootstrapped since it was loaded"
      )

   is_missing_bloks_version = query.sends_path_headers and not session.bloks_version_id

   if is_missing_bloks_version:
      raise SchemaChanged(
         "the bootstrap page carried no WebBloksVersioningID, so the x-bloks-version-id "
         f"header {query.friendly_name} needs cannot be sent",
         path="WebBloksVersioningID",
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

   if query.sends_path_headers:
      headers["x-bloks-version-id"] = session.bloks_version_id or ""
      headers["x-root-field-name"] = query.root_field or ""

   return Request(
      method="POST",
      url=query.url,
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

   return build_graphql_request(
      session,
      THREAD_MESSAGE_PAGE,
      _thread_page_variables(thread_fbid, after, newer_than_message_id),
      referer=thread_url(thread_fbid),
      user_agent=user_agent,
   )


def thread_url(thread_fbid: str) -> str:
   """The page a browser has open while it reads a thread, and so the referer of every read."""

   return f"{ORIGIN}/direct/t/{thread_fbid}/"


def _thread_page_variables(
   thread_fbid: str,
   after: str | None,
   newer_than_message_id: str | None,
) -> dict[str, Any]:
   return {
      "after": after,
      "before": None,
      "first": PAGE_SIZE,
      "last": None,
      "newer_than_message_id": newer_than_message_id,
      "older_than_message_id": None,
      "id": thread_fbid,
      "__relay_internal__pv__IGDInitialMessagePageCountrelayprovider": PAGE_SIZE,
   }


def build_thread_detail_request(
   session: Session,
   thread_fbid: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The query a browser sends to open a thread, which answers with its newest page.

   ``IGDEnableOffMsysChatThemesQErelayprovider`` is false because every one of the 63 requests
   a browser sent across four captures on 2026-09-23 carried false. The finding's replay
   template carries true, and that replay answered too, so the flag is not what makes the
   request succeed. It is reproduced as the browser sends it.

   ``min_uq_seq_id`` was null on all 63.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/open-a-direct-thread.md``.
   """

   variables = {
      "min_uq_seq_id": None,
      "thread_fbid": thread_fbid,
      "__relay_internal__pv__IGDEnableOffMsysChatThemesQErelayprovider": False,
      "__relay_internal__pv__IGDInitialMessagePageCountrelayprovider": PAGE_SIZE,
   }

   return build_graphql_request(
      session,
      THREAD_DETAIL,
      variables,
      referer=thread_url(thread_fbid),
      user_agent=user_agent,
   )


def build_thread_older_page_request(
   session: Session,
   thread_fbid: str,
   *,
   after: str | None = None,
   newer_than_message_id: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """One page of one thread, as a browser asks for it when the thread scrolls up.

   The variables are the ones :func:`build_thread_page_request` sends, in the order the browser
   sends them. Every captured browser request carried a 132-character ``after`` and a null
   ``newer_than_message_id``. A null ``after`` was replayed twice and answered. A
   ``newer_than_message_id`` has not been sent on this query by anything yet.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/direct-thread-older-page-offmsys.md``.
   """

   return build_graphql_request(
      session,
      THREAD_OLDER_PAGE,
      _thread_page_variables(thread_fbid, after, newer_than_message_id),
      referer=thread_url(thread_fbid),
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


def build_feed_page_request(
   session: Session,
   *,
   after: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """One page of the signed-in account's home timeline.

   ``after`` is the previous page's ``end_cursor``, and ``None`` asks for the first page. The
   same query serves both, so there is no first-page variant to get wrong.

   The relay provider flags carry the values the web client sent on the measured request.
   They select experiment branches rather than data, and none was ablated, so they are
   reproduced rather than reasoned about.

   This request goes to a different path from every other query in the registry, which
   :data:`~dumpstagram._private.web.documents.GRAPHQL_QUERY_URL` explains.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/home-timeline-feed-page.md``.
   """

   variables = {
      "after": after,
      "before": None,
      "data": {
         "device_id": FEED_DEVICE_ID,
         "is_async_ads_double_request": "0",
         "is_async_ads_in_headload_enabled": "0",
         "is_async_ads_rti": "0",
         "rti_delivery_backend": "0",
      },
      "first": FEED_PAGE_SIZE,
      "last": None,
      "variant": "home",
      "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": False,
      "__relay_internal__pv__PolarisMultiCaptionCarouselEnabledrelayprovider": True,
      "__relay_internal__pv__PolarisReelsRecoDebugOverlayEnabledrelayprovider": False,
      "__relay_internal__pv__PolarisAdDebugToolEnabledrelayprovider": False,
   }

   return build_graphql_request(
      session,
      HOME_TIMELINE_FEED,
      variables,
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )


LOGIN_INTERSTITIAL_SURFACES = ["INSTAGRAM_FOR_WEB_LOGIN_INTERSTITIAL_QP"]
"""The quick promotion surface every captured page load asked for."""

PAGE_SURFACES = [
   "INSTAGRAM_WEB_MEGAPHONE",
   "INSTAGRAM_FOR_WEB_INTERSTITIAL_QP",
   "INSTAGRAM_FOR_WEB_TOOLTIP_QP",
]
"""The three surfaces home and profile loads ask for in a second quick promotion call."""

OMNI_PICKER_PAGE_SIZE = 20


def _quick_promotion_variables(
   surfaces: list[str], trigger_context: dict[str, Any] | None
) -> dict[str, Any]:
   return {"scale": 2, "surface_nux_ids": surfaces, "trigger_context": trigger_context}


def _companion(
   session: Session,
   query: PersistedQuery,
   variables: dict[str, Any],
   referer: str,
   user_agent: str,
) -> Request:
   return build_graphql_request(session, query, variables, referer=referer, user_agent=user_agent)


def _jewel_group(
   session: Session, device_id: str | None, referer: str, user_agent: str
) -> list[Request]:
   omni_picker_variables = {
      "input": {
         "count_per_page": OMNI_PICKER_PAGE_SIZE,
         "is_private_share": False,
         "views": ["DIRECT_USER_SEARCH_NULLSTATE"],
      }
   }
   omni_picker = _companion(
      session, OMNI_PICKER_NULL_STATE, omni_picker_variables, referer, user_agent
   )

   if device_id is None:
      return [omni_picker]

   iris = {"device_id_for_iris_subscription": device_id}
   jewel = _companion(session, CHAT_TABS_JEWEL, iris, referer, user_agent)

   return [jewel, omni_picker]


def _badge_group(
   session: Session, device_id: str | None, referer: str, user_agent: str
) -> list[Request]:
   if device_id is None:
      return []

   iris = {"device_id_for_iris_subscription": device_id}

   return [_companion(session, BADGE_COUNT, iris, referer, user_agent)]


def build_home_page_load_companions(
   session: Session,
   *,
   device_id: str | None,
   user_agent: str = DEFAULT_USER_AGENT,
) -> list[list[Request]]:
   """What a home page load sends after its document, as groups in the page's order.

   Each group went out within a few milliseconds and the groups hundreds of milliseconds
   apart, in the cold load ``run-2026-09-23-003559``: the badge count at 748 ms, the chat tabs
   jewel and the omni picker together at 1035 ms, the three-surface quick promotion call at
   1846 ms and the login interstitial one at 2149 ms. The home load prefetches no stories tray,
   because its document carries that as a preloader.

   Left out, and why: ``/data/manifest.json`` and ``/api/v1/web/fxcal/ig_sso_users/`` have no
   verified finding. ``device_id`` is the document's own, and ``None`` leaves out the two
   queries keyed on it.

   Findings: ``page-load-direct-badge-count``, ``page-load-chat-tabs-jewel``,
   ``page-load-omni-picker-null-state`` and ``page-load-quick-promotion``.
   """

   referer = f"{ORIGIN}/"
   page_surfaces = _quick_promotion_variables(PAGE_SURFACES, None)
   login_surface = _quick_promotion_variables(LOGIN_INTERSTITIAL_SURFACES, None)

   groups = [
      _badge_group(session, device_id, referer, user_agent),
      _jewel_group(session, device_id, referer, user_agent),
      [_companion(session, QUICK_PROMOTION, page_surfaces, referer, user_agent)],
      [_companion(session, QUICK_PROMOTION, login_surface, referer, user_agent)],
   ]

   return [group for group in groups if group]


def build_profile_page_load_companions(
   session: Session,
   user_id: str,
   username: str,
   *,
   device_id: str | None,
   user_agent: str = DEFAULT_USER_AGENT,
) -> list[list[Request]]:
   """What a profile page load sends after its six queries, as groups in the page's order.

   From the cold load ``run-2026-09-23-004555``: the stories tray at 871 ms, the chat tabs
   jewel and the omni picker together at 877 ms, the badge count at 1042 ms, and both quick
   promotion calls at 1329 and 1333 ms. The three-surface call carries the profile's account
   id as its trigger context, where the home load sends null.

   Left out, and why: the feed timeline prefetch the page sends within 2 ms of the stories
   tray has no finding of its own, and neither do ``/data/manifest.json`` and
   ``/api/v1/web/fxcal/ig_sso_users/``. ``device_id`` is the document's own, and ``None``
   leaves out the two queries keyed on it.

   Findings: ``page-load-stories-tray``, ``page-load-chat-tabs-jewel``,
   ``page-load-omni-picker-null-state``, ``page-load-direct-badge-count`` and
   ``page-load-quick-promotion``.
   """

   referer = profile_page_url(username)
   stories_tray_variables = {
      "data": {"is_following_feed": False},
      "suggestedUsersData": {
         "max_id": "",
         "max_number_to_display": 0,
         "module": "stories_tray",
         "paginate": False,
      },
   }
   profile_trigger = {
      "context_data_tuples": [{"context_key": "profile_igid", "context_value": user_id}]
   }
   page_surfaces = _quick_promotion_variables(PAGE_SURFACES, profile_trigger)
   login_surface = _quick_promotion_variables(LOGIN_INTERSTITIAL_SURFACES, None)

   groups = [
      [_companion(session, STORIES_TRAY, stories_tray_variables, referer, user_agent)],
      _jewel_group(session, device_id, referer, user_agent),
      _badge_group(session, device_id, referer, user_agent),
      [
         _companion(session, QUICK_PROMOTION, page_surfaces, referer, user_agent),
         _companion(session, QUICK_PROMOTION, login_surface, referer, user_agent),
      ],
   ]

   return [group for group in groups if group]
