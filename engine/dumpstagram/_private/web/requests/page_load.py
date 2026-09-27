"""What a home, profile or direct inbox page load sends after its document, as groups in the
page's order, and the direct block an inbox load sends first."""

from __future__ import annotations

from typing import Any

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import BOOTSTRAP_URL, DEFAULT_USER_AGENT, ORIGIN
from dumpstagram._private.web.documents.common import PersistedQuery
from dumpstagram._private.web.documents.page_load import (
   AUTOMATIC_PREVIEWS_SETTING,
   BADGE_COUNT,
   CHAT_TABS_JEWEL,
   FEATURE_LIMITS,
   INBOX_QP_INTERSTITIAL,
   OMNI_PICKER_NULL_STATE,
   PRESENCE_SETUP,
   QUICK_PROMOTION,
   STORIES_TRAY,
   THREAD_LIST_ACCOUNT_SWITCHER,
   VIEWER_SETTINGS,
)
from dumpstagram._private.web.requests.account import (
   build_activity_feed_request,
   build_follow_requests_request,
)
from dumpstagram._private.web.requests.common import build_graphql_request
from dumpstagram._private.web.requests.direct import build_thread_detail_request
from dumpstagram._private.web.requests.profiles import profile_page_url
from dumpstagram.session import Session

__all__ = [
   "INBOX_PAGE_URL",
   "build_home_page_load_companions",
   "build_inbox_block",
   "build_inbox_page_load_companions",
   "build_profile_page_load_companions",
]

INBOX_PAGE_URL = BOOTSTRAP_URL
"""The direct inbox, the page an inbox load is of and the referer of everything it sends."""

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


def _stories_tray_variables() -> dict[str, Any]:
   return {
      "data": {"is_following_feed": False},
      "suggestedUsersData": {
         "max_id": "",
         "max_number_to_display": 0,
         "module": "stories_tray",
         "paginate": False,
      },
   }


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
   stories_tray_variables = _stories_tray_variables()
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


def build_inbox_block(
   session: Session,
   *,
   tray: Request,
   listing: Request,
   inbox_unread_rows: Request,
   pending_unread_rows: Request,
   user_agent: str = DEFAULT_USER_AGENT,
) -> list[Request]:
   """The ten queries of an inbox load's direct block, in the page's order.

   The four requests a capability reads are the caller's, built with the document's device id,
   and the six with no variables are built here. Both captured inbox loads sent the ten in this
   order within 4 ms: 492 to 496 ms after the document in ``run-2026-09-23-022159`` and 532 to
   536 ms in ``run-2026-09-23-045256``.

   Findings: ``direct-inbox-automatic-previews-setting``, ``direct-feature-limits``,
   ``direct-inbox-unread-thread-count``, ``direct-inbox-thread-list``,
   ``direct-presence-setup``, ``direct-inbox-qp-interstitial``,
   ``direct-thread-list-header-account-switcher``, ``viewer-settings`` and
   ``read-the-notes-tray-on-the-direct-inbox``.
   """

   def empty(query: PersistedQuery) -> Request:
      return _companion(session, query, {}, INBOX_PAGE_URL, user_agent)

   return [
      empty(AUTOMATIC_PREVIEWS_SETTING),
      empty(FEATURE_LIMITS),
      inbox_unread_rows,
      listing,
      pending_unread_rows,
      empty(PRESENCE_SETUP),
      empty(INBOX_QP_INTERSTITIAL),
      empty(THREAD_LIST_ACCOUNT_SWITCHER),
      empty(VIEWER_SETTINGS),
      tray,
   ]


def build_inbox_page_load_companions(
   session: Session,
   *,
   device_id: str | None,
   thread_keys: tuple[str, ...],
   web_session_id: str,
   user_agent: str = DEFAULT_USER_AGENT,
) -> list[list[Request]]:
   """What a direct inbox load sends after its direct block, as groups in the page's order.

   From the cold load ``run-2026-09-23-022159``: the badge count at 519 ms, the stories tray at
   642, the login interstitial quick promotion at 849, a thread detail query for each row of
   the first page from 1039 to 1044, and the pending follow requests and the activity feed at
   3687, 0.4 ms apart. ``run-2026-09-23-045256`` sent the same up to the thread details, at 564,
   728, 897 and 1051 to 1070 ms, and no REST read at all. ``thread_keys`` is
   :func:`~dumpstagram._private.web.parse.direct.parse_thread_prefetch_keys` of the block's
   listing, and an empty one leaves that group out.

   Left out, and why: the feed timeline prefetch the page sends within 2 ms of the stories
   tray, as the profile load leaves it out; ``fxcal`` and ``/data/manifest.json``, which have no
   verified finding; and ``news/inbox_seen``, which the first load sent 2 ms before the
   pending requests and which is an unverified write that clears the viewer's own activity
   badge (W74). The inbox load sends neither the chat tabs jewel nor the omni picker, which
   are the floating chat of the pages that are not direct. ``device_id`` is the document's own,
   and ``None`` leaves out the badge count.

   Findings: ``page-load-direct-badge-count``, ``page-load-stories-tray``,
   ``page-load-quick-promotion``, ``open-a-direct-thread``, ``pending-follow-requests`` and
   ``activity-feed-inbox``.
   """

   referer = INBOX_PAGE_URL
   login_surface = _quick_promotion_variables(LOGIN_INTERSTITIAL_SURFACES, None)
   thread_details = [
      build_thread_detail_request(session, key, referer=referer, user_agent=user_agent)
      for key in thread_keys
   ]
   account_reads = [
      build_follow_requests_request(session, web_session_id=web_session_id, user_agent=user_agent),
      build_activity_feed_request(session, web_session_id=web_session_id, user_agent=user_agent),
   ]

   groups = [
      _badge_group(session, device_id, referer, user_agent),
      [_companion(session, STORIES_TRAY, _stories_tray_variables(), referer, user_agent)],
      [_companion(session, QUICK_PROMOTION, login_surface, referer, user_agent)],
      thread_details,
      account_reads,
   ]

   return [group for group in groups if group]
