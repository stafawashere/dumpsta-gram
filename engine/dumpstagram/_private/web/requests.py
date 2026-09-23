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
from dumpstagram._private.web.bootstrap import BOOTSTRAP_URL, DEFAULT_USER_AGENT, ORIGIN
from dumpstagram._private.web.documents import (
   BADGE_COUNT,
   CHAT_TABS_JEWEL,
   COMMENT_PAGE,
   CREATE_COMMENT,
   CREATE_NOTE,
   DELETE_COMMENT,
   DELETE_NOTE,
   DIRECT_INBOX,
   DIRECT_TEXT_SEND,
   DIRECT_UNSEND,
   FOLLOW_USER,
   HOME_TIMELINE_FEED,
   INBOX_TRAY,
   LIKE_MEDIA,
   OMNI_PICKER_NULL_STATE,
   POST_BY_SHORTCODE,
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
   UNFOLLOW_USER,
   UNLIKE_MEDIA,
   PersistedQuery,
)
from dumpstagram.errors import AuthenticationFailed, NotFound, SchemaChanged
from dumpstagram.session import Session

__all__ = [
   "COMMENT_PAGE_SIZE",
   "FEED_DEVICE_ID",
   "FEED_PAGE_SIZE",
   "INBOX_ROW_MESSAGES",
   "PAGE_SIZE",
   "PROFILE_PAGE_POSTS",
   "RESOLUTION_PAGE_SIZE",
   "SEND_ATTRIBUTION",
   "VALIDATED_BODY_FIELDS",
   "VALIDATED_HEADERS",
   "build_comment_page_request",
   "build_create_comment_request",
   "build_create_note_request",
   "build_delete_comment_request",
   "build_delete_note_request",
   "build_direct_text_send_request",
   "build_direct_unsend_request",
   "build_feed_page_request",
   "build_follow_request",
   "build_graphql_request",
   "build_home_page_load_companions",
   "build_inbox_listing_request",
   "build_inbox_tray_request",
   "build_like_request",
   "build_post_request",
   "build_profile_page_load_companions",
   "build_profile_page_requests",
   "build_profile_request",
   "build_thread_detail_request",
   "build_thread_older_page_request",
   "build_thread_page_request",
   "build_unfollow_request",
   "build_unlike_request",
   "build_username_resolution_request",
   "is_a_comment_id",
   "is_a_media_pk",
   "is_a_note_id",
   "is_a_thread_fbid",
   "is_a_user_id",
   "jazoest_for",
   "offline_threading_id",
   "post_url",
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

_SHORTCODE = re.compile(r"[A-Za-z0-9_-]{1,64}")

_MEDIA_PK = re.compile(r"[0-9]{1,30}")

_COMMENT_ID = re.compile(r"[0-9]{1,30}")

_NOTE_ID = re.compile(r"[0-9]{1,30}")

_USER_ID = re.compile(r"[0-9]{1,30}")

SEND_ATTRIBUTION = "igd_web_chat_tab:in_thread"
"""What the composer names as the origin of a text send, a literal in its source.

The same string was compiled on a thread page and sent from the chat tab a profile page opens.
"""

_OFFLINE_THREADING_ID_BITS = 63
_OFFLINE_THREADING_RANDOM_BITS = 22

NOTE_STYLE_TEXT = 0
"""The ``note_style`` of a plain text note, the only style a create has sent."""

COMMENT_PAGE_SIZE = 10
"""How many comments a page asks for, chosen by the engine.

The value the post page asks for has not been observed, so this is an ASSUMPTION and a
difference a fingerprint check could read. Four engine reads sent it and were answered.
"""

INBOX_ROW_MESSAGES = 5
"""How many of its newest messages each inbox row carries, as every captured inbox load asked."""

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
   ``newer_than_message_id``. A null ``after`` was replayed twice and answered. The engine sends
   a ``newer_than_message_id`` too, which a browser never did: with a live base the answer holds
   only newer messages, the newest twenty first, and ``after`` with the same base pages back to
   the base and ends there with ``has_next_page`` false.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/direct-thread-older-page-offmsys.md``.
   """

   return build_graphql_request(
      session,
      THREAD_OLDER_PAGE,
      _thread_page_variables(thread_fbid, after, newer_than_message_id),
      referer=thread_url(thread_fbid),
      user_agent=user_agent,
   )


def build_inbox_tray_request(
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The notes tray, asked for the way the inbox asks for it: no variables, the inbox as referer.

   The query goes to ``/api/graphql`` and carries neither path header, as on every captured
   inbox load.

   Finding: ``read-the-notes-tray-on-the-direct-inbox`` in the knowledge base.
   """

   return build_graphql_request(
      session,
      INBOX_TRAY,
      {},
      referer=BOOTSTRAP_URL,
      user_agent=user_agent,
   )


def build_inbox_listing_request(
   session: Session,
   *,
   device_id: str,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The inbox's first page of threads, asked for the way an inbox load asks for it.

   ``device_id`` is the ``clientId`` of ``IGDMqttWebDeviceID`` in the inbox document, which a
   browser mints fresh on every load. A replay with a random uuid4 the page never issued
   answered the same way, so a listener holds one for its lifetime as one open inbox would.

   The four provider flags are the values every captured inbox load sent for this account.
   ``IGDMaxUnreadMessagesCountrelayprovider`` is what makes each row carry its newest five
   messages, and so the newest message id a poll compares.

   Finding: ``direct-inbox-thread-list`` in the knowledge base.
   """

   variables = {
      "device_id_for_iris_subscription": device_id,
      "__relay_internal__pv__IGDIsProfessionalAccountGKrelayprovider": False,
      "__relay_internal__pv__IGDPinnedThreadsRenderEnabledGKrelayprovider": True,
      "__relay_internal__pv__IGDMaxUnreadMessagesCountrelayprovider": INBOX_ROW_MESSAGES,
      "__relay_internal__pv__IGDThreadListActionsEnabledGKrelayprovider": True,
   }

   return build_graphql_request(
      session,
      DIRECT_INBOX,
      variables,
      referer=BOOTSTRAP_URL,
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


def post_url(code: str) -> str:
   """The post page a browser navigates to for the shortcode ``code``.

   The shortcode becomes a path segment, so anything outside the characters one is written in
   is refused before it is sent, as a post that cannot exist.
   """

   is_a_possible_shortcode = _SHORTCODE.fullmatch(code) is not None

   if not is_a_possible_shortcode:
      raise NotFound(f"{code!r} cannot be a post shortcode")

   return f"{ORIGIN}/p/{code}/"


def build_post_request(
   session: Session,
   code: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """One post, read by its shortcode the way the post page reads it.

   The two provider values are the ones the profile timeline query was captured sending, and
   the engine replays of this query carried the same pair.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/read-a-post-by-shortcode.md``.
   """

   return build_graphql_request(
      session,
      POST_BY_SHORTCODE,
      {
         "shortcode": code,
         "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": False,
         "__relay_internal__pv__PolarisMultiCaptionCarouselEnabledrelayprovider": True,
      },
      referer=post_url(code),
      user_agent=user_agent,
   )


def is_a_media_pk(value: str) -> bool:
   """Whether ``value`` has the shape of a media ``pk``, digits only.

   The other identifier a post carries, ``<pk>_<owner id>``, fails this, and so does anything
   else a caller might hand over by mistake.
   """

   return _MEDIA_PK.fullmatch(value) is not None


def build_like_request(
   session: Session,
   post_pk: str,
   *,
   client_mutation_id: str,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Like the post whose media ``pk`` is ``post_pk``.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/like-a-post.md``.
   """

   return build_graphql_request(
      session,
      LIKE_MEDIA,
      _like_variables(post_pk, client_mutation_id),
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )


def build_unlike_request(
   session: Session,
   post_pk: str,
   *,
   client_mutation_id: str,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Unlike the post whose media ``pk`` is ``post_pk``.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/unlike-a-post.md``.
   """

   return build_graphql_request(
      session,
      UNLIKE_MEDIA,
      _like_variables(post_pk, client_mutation_id),
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )


def _like_variables(post_pk: str, client_mutation_id: str) -> dict[str, Any]:
   """The input both mutations take, as the engine replays sent it.

   ``media_id`` is the ``pk``, never the ``<pk>_<owner id>`` form, observed on six sends.
   ``tracking_token`` is null because the engine is handed an identifier and not the feed item
   whose ``organic_tracking_token`` a browser would pass, and the Relay network layer's
   ``actor_id`` is absent because the session does not hold it. Both departures were in every
   observed send, and each is recorded in ``engine/docs/web-request-contract.md``.
   """

   return {
      "input": {
         "client_mutation_id": client_mutation_id,
         "media_id": post_pk,
         "tracking_token": None,
      }
   }


def build_comment_page_request(
   session: Session,
   post_pk: str,
   *,
   after: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """One page of the comments on the post whose media ``pk`` is ``post_pk``.

   ``sort_order`` is the value the post page's own first page query has compiled in. The
   referer is the home page, as every engine read carried, because the capability is handed
   a ``pk`` and not the shortcode a post page address needs.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/read-a-post-comment-page.md``.
   """

   return build_graphql_request(
      session,
      COMMENT_PAGE,
      {
         "after": after,
         "before": None,
         "first": COMMENT_PAGE_SIZE,
         "last": None,
         "media_id": post_pk,
         "sort_order": "popular",
         "__relay_internal__pv__PolarisIsLoggedInrelayprovider": True,
      },
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )


def build_create_comment_request(
   session: Session,
   post_pk: str,
   text: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Comment ``text`` on the post whose media ``pk`` is ``post_pk``.

   The variable is ``data`` rather than ``input``, so the Relay network layer adds no
   ``client_mutation_id``. ``connections`` is a handle into the browser's own store, which the
   engine does not have, and the empty list it sends was accepted on both engine sends.
   ``replied_to_comment_id`` and ``tracking_token`` are left out, as a browser leaves out a value
   it does not have.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/comment-on-a-post.md``.
   """

   return build_graphql_request(
      session,
      CREATE_COMMENT,
      {"connections": [], "data": {"comment_text": text, "media_id": post_pk}},
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )


def is_a_comment_id(value: str) -> bool:
   """Whether ``value`` has the shape of a comment id, digits only, 17 on every one observed."""

   return _COMMENT_ID.fullmatch(value) is not None


def build_delete_comment_request(
   session: Session,
   post_pk: str,
   comment_id: str,
   *,
   client_mutation_id: str,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Delete the comment ``comment_id`` on the post whose media ``pk`` is ``post_pk``.

   The input field names are not in the compiled artifact. An input carrying neither was
   refused as noncoercible, and one carrying ``comment_id`` and ``media_id`` was accepted, on
   2026-09-23, and two real deletes with them were confirmed by the comment read.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/delete-my-own-comment.md``.
   """

   return build_graphql_request(
      session,
      DELETE_COMMENT,
      {
         "input": {
            "client_mutation_id": client_mutation_id,
            "comment_id": comment_id,
            "media_id": post_pk,
         }
      },
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )


def build_create_note_request(
   session: Session,
   text: str,
   audience: int,
   *,
   client_mutation_id: str,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Set the viewer's note to ``text`` for ``audience``, 0 for followers followed back, 1 for
   close friends.

   ``actor_id`` is the account's Facebook-side id from the bootstrap page, and never
   ``ds_user_id``, which the finding records as a different number for the same account. A
   session that has not read it raises :class:`~dumpstagram.errors.SchemaChanged`, because the
   capability bootstraps before building, so a missing id means the page stopped carrying it.
   The referer is the inbox, where the composer lives.

   Finding: ``set-my-own-note-on-the-direct-inbox`` in the knowledge base.
   """

   if not session.actor_id:
      raise SchemaChanged(
         "the bootstrap page carried no RelayAPIConfigDefaults actorID, so the actor_id a note "
         "create needs cannot be sent",
         path="RelayAPIConfigDefaults.actorID",
      )

   return build_graphql_request(
      session,
      CREATE_NOTE,
      {
         "input": {
            "actor_id": session.actor_id,
            "additional_params": {
               "note_create_params": {"note_style": NOTE_STYLE_TEXT, "text": text}
            },
            "audience": audience,
            "client_mutation_id": client_mutation_id,
            "inbox_tray_item_type": "note",
         }
      },
      referer=BOOTSTRAP_URL,
      user_agent=user_agent,
   )


def is_a_note_id(value: str) -> bool:
   """Whether ``value`` has the shape of a tray item id, digits only, 17 on every one observed."""

   return _NOTE_ID.fullmatch(value) is not None


def build_delete_note_request(
   session: Session,
   note_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Delete the note whose tray item id is ``note_id``.

   The one variable is the tray item id, not wrapped in ``input``, so the Relay network layer
   adds no ``client_mutation_id``.

   Finding: ``delete-my-own-note-on-the-direct-inbox`` in the knowledge base.
   """

   return build_graphql_request(
      session,
      DELETE_NOTE,
      {"inbox_tray_item_id": note_id},
      referer=BOOTSTRAP_URL,
      user_agent=user_agent,
   )


def is_a_thread_fbid(value: str) -> bool:
   """Whether ``value`` has the shape of a ``thread_fbid``, digits only, at most 30 of them.

   The two measured were 16 and 17 digits. The thread's 39-digit ``thread_id`` fails this,
   which is the mix-up it catches, since the unsend takes that id and the send does not. The
   ``thread_key`` passes, and nothing here can tell it apart by shape.
   """

   return _USER_ID.fullmatch(value) is not None


def is_a_user_id(value: str) -> bool:
   """Whether ``value`` has the shape of a numeric account id, digits only.

   A username fails this, which is the mistake it exists to catch: the follow mutations take
   the id, and what they do with a username is unobserved.
   """

   return _USER_ID.fullmatch(value) is not None


def build_follow_request(
   session: Session,
   user_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Follow the account whose numeric id is ``user_id``.

   The one variable is ``target_user_id``, not wrapped in ``input``, so the Relay network layer
   adds no ``client_mutation_id``. The referer is the home page, where the compiled artifact was
   read off a suggested account's Follow button, and where both engine sends came from.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/follow-a-user.md``.
   """

   return build_graphql_request(
      session,
      FOLLOW_USER,
      {"target_user_id": user_id},
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )


def build_unfollow_request(
   session: Session,
   user_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Unfollow the account whose numeric id is ``user_id``.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/unfollow-a-user.md``.
   """

   return build_graphql_request(
      session,
      UNFOLLOW_USER,
      {"target_user_id": user_id},
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )


def offline_threading_id(now_ms: int, random_bits: int) -> str:
   """The client-generated identifier a text send carries, built as the browser builds it.

   ``IGDOfflineThreadingID.generateOfflineThreadingID`` writes the millisecond clock in binary,
   appends the low 22 bits of a random 32-bit number, keeps the last 63 binary digits and
   renders them in decimal. That is the clock shifted left by 22 with the random bits below it,
   cut to 63 bits. A thread read echoes it on the new message's node, which is what makes a
   reconciling read exact.
   """

   random_mask = (1 << _OFFLINE_THREADING_RANDOM_BITS) - 1
   combined = (now_ms << _OFFLINE_THREADING_RANDOM_BITS) | (random_bits & random_mask)

   return str(combined & ((1 << _OFFLINE_THREADING_ID_BITS) - 1))


def build_direct_text_send_request(
   session: Session,
   thread_fbid: str,
   text: str,
   threading_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Send ``text`` into the thread whose ``thread_fbid`` is ``thread_fbid``.

   The fourteen variables in the order and with the values the browser's composer sent for a
   plain text message: no reply, no mention, no command, not forwarded. ``recipient_igids`` is
   what the composer sends in place of ``ig_thread_igid`` when no thread exists, and that shape
   is not built here because it was never sent. ``sampled`` and ``replied_to_client_context``
   are never set by the composer and leave as Relay's default null. The text travels wrapped as
   ``sensitive_string_value``.

   The referer is the thread page. The observed browser send came from the chat tab a profile
   page opens and carried the profile page, which the engine cannot name from a thread id, a
   departure recorded in ``docs/web-request-contract.md``.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/send-a-direct-text-message.md``.
   """

   variables: dict[str, Any] = {
      "ig_thread_igid": thread_fbid,
      "offline_threading_id": threading_id,
      "recipient_igids": None,
      "replied_to_client_context": None,
      "replied_to_item_id": None,
      "reply_to_message_id": None,
      "sampled": None,
      "text": {"sensitive_string_value": text},
      "mentions": [],
      "mentioned_user_ids": [],
      "commands": None,
      "forwarded_from_thread_id": None,
      "is_forwarded_from_own_message": None,
      "send_attribution": SEND_ATTRIBUTION,
   }

   return build_graphql_request(
      session,
      DIRECT_TEXT_SEND,
      variables,
      referer=thread_url(thread_fbid),
      user_agent=user_agent,
   )


def build_direct_unsend_request(
   session: Session,
   thread_fbid: str,
   thread_id: str,
   message_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Unsend the viewer's message ``message_id`` from the thread whose long id is ``thread_id``.

   ``thread_id`` is the thread's 39-digit id, which the unsend takes under ``send_data``, and
   ``thread_fbid`` only names the referer, the thread page.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/unsend-a-direct-message.md``.
   """

   return build_graphql_request(
      session,
      DIRECT_UNSEND,
      {"message_id": message_id, "send_data": {"thread_id": thread_id}},
      referer=thread_url(thread_fbid),
      user_agent=user_agent,
   )
