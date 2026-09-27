"""What a page load sends after its document, and the cookie sync's ``fr`` exchange.

They are sent because a browser sends them. One of them, :data:`STORIES_TRAY`, also backs a
capability, since ``stories.tray`` reads it on its own from E2 batch 5. The six direct inbox
queries at the end are the part of an inbox load's direct block that no capability reads, sent
since E2 batch 9 beside the four that ``direct.notes``, ``direct.inbox`` and
``direct.unread_counts`` read. Each of the six was seen in the inbox cold loads of
``run-2026-09-23-022159`` and ``run-2026-09-23-045256``, and replayed in the first.
"""

from __future__ import annotations

from dumpstagram._private.web.documents.common import PersistedQuery

__all__ = [
   "AUTOMATIC_PREVIEWS_SETTING",
   "BADGE_COUNT",
   "CHAT_TABS_JEWEL",
   "FEATURE_LIMITS",
   "GET_FR_COOKIE",
   "INBOX_QP_INTERSTITIAL",
   "OMNI_PICKER_NULL_STATE",
   "PRESENCE_SETUP",
   "QUICK_PROMOTION",
   "STORIES_TRAY",
   "THREAD_LIST_ACCOUNT_SWITCHER",
   "VIEWER_SETTINGS",
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

AUTOMATIC_PREVIEWS_SETTING = PersistedQuery(
   doc_id="36445470711719123",
   friendly_name="PolarisAutomaticPreviewsDisabledContextProviderQuery",
   finding_id="direct-inbox-automatic-previews-setting",
)
"""Whether automatic previews are off, the first of an inbox load's direct block. No variables."""

FEATURE_LIMITS = PersistedQuery(
   doc_id="35236077379370476",
   friendly_name="useFeatureLimitsOffMsysQuery",
   finding_id="direct-feature-limits",
)
"""The direct feature limits and polling intervals, second in the direct block. No variables."""

PRESENCE_SETUP = PersistedQuery(
   doc_id="28134060952867396",
   friendly_name="IGPresenceUnifiedSetupQuery",
   finding_id="direct-presence-setup",
)
"""Whether presence is off, a read and not a presence write. No variables."""

INBOX_QP_INTERSTITIAL = PersistedQuery(
   doc_id="28066018679757800",
   friendly_name="PolarisDirectInboxQPInterstitialQuery",
   finding_id="direct-inbox-qp-interstitial",
)
"""The inbox's own quick promotion interstitial. No variables."""

THREAD_LIST_ACCOUNT_SWITCHER = PersistedQuery(
   doc_id="27105976072392132",
   friendly_name="IGDThreadListHeaderAccountSwitcherOffMsysQuery",
   finding_id="direct-thread-list-header-account-switcher",
)
"""The account switcher in the thread list header. No variables."""

VIEWER_SETTINGS = PersistedQuery(
   doc_id="26685322771120877",
   friendly_name="PolarisViewerSettingsQuery",
   finding_id="viewer-settings",
)
"""The viewer's settings, which answered only the reduce motion flag. No variables. Seen on
inbox and thread loads, never on home or profile loads."""
