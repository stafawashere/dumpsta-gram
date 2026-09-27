"""What a page load sends after its document, and the cookie sync's ``fr`` exchange.

They are sent because a browser sends them. One of them, :data:`STORIES_TRAY`, also backs a
capability, since ``stories.tray`` reads it on its own from E2 batch 5.
"""

from __future__ import annotations

from dumpstagram._private.web.documents.common import PersistedQuery

__all__ = [
   "BADGE_COUNT",
   "CHAT_TABS_JEWEL",
   "GET_FR_COOKIE",
   "OMNI_PICKER_NULL_STATE",
   "QUICK_PROMOTION",
   "STORIES_TRAY",
]

BADGE_COUNT = PersistedQuery(
   doc_id="27393860900250970",
   friendly_name="IGDBadgeCountOffMsysQuery",
   finding_id="page-load-direct-badge-count",
)
"""The direct badge count. Every page load sends it, keyed on the document's iris device id."""

QUICK_PROMOTION = PersistedQuery(
   doc_id="28296776023244273",
   friendly_name="QuickPromotionSupportIGSchemaBatchFetchQuery",
   finding_id="page-load-quick-promotion",
)
"""Quick promotions for a list of surfaces. Every page load asks for the login interstitial, and
home and profile loads ask a second time for three more surfaces."""

CHAT_TABS_JEWEL = PersistedQuery(
   doc_id="27647971824866335",
   friendly_name="IGDChatTabsJewelOffMsysQuery",
   finding_id="page-load-chat-tabs-jewel",
)
"""The chat tabs jewel. Sent on home and profile loads, within 1 ms of
:data:`OMNI_PICKER_NULL_STATE`, and not on direct loads."""

OMNI_PICKER_NULL_STATE = PersistedQuery(
   doc_id="27657376130569675",
   friendly_name="IGDOmniPickerNullStateListQuery",
   finding_id="page-load-omni-picker-null-state",
)
"""The share sheet's null state list. Sent beside :data:`CHAT_TABS_JEWEL`."""

STORIES_TRAY = PersistedQuery(
   doc_id="27703822975903310",
   friendly_name="PolarisStoriesV3TrayContainerQuery",
   finding_id="page-load-stories-tray",
)
"""The stories tray, prefetched by every load that is not the home page. The home document
carries it as a preloader instead. ``stories.tray`` sends it alone and reads it, and a page
load's copy is still left unread. Replayed on 2026-09-27 in run ``run-2026-09-27-014102``, 33
reels, roots ``ayml``, ``xdt_api__v1__feed__reels_tray`` and ``xdt_viewer``."""

GET_FR_COOKIE = PersistedQuery(
   doc_id="27399811883030165",
   friendly_name="PolarisAPIGetFrCookieQuery",
   finding_id="get-encrypted-fr-cookie",
)
"""The page-load cookie sync's exchange of the stored ``fr`` for the current one. Sent seconds
after the document, outside its action, never inside one."""
