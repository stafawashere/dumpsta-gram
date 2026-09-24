"""What a home or profile page load sends after its document, as groups in the page's order."""

from __future__ import annotations

from typing import Any

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, ORIGIN
from dumpstagram._private.web.documents.common import PersistedQuery
from dumpstagram._private.web.documents.page_load import (
   BADGE_COUNT,
   CHAT_TABS_JEWEL,
   OMNI_PICKER_NULL_STATE,
   QUICK_PROMOTION,
   STORIES_TRAY,
)
from dumpstagram._private.web.requests.common import build_graphql_request
from dumpstagram._private.web.requests.profiles import profile_page_url
from dumpstagram.session import Session

__all__ = [
   "build_home_page_load_companions",
   "build_profile_page_load_companions",
]

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
