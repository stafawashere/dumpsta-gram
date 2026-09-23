"""The registry of persisted GraphQL query ids.

One name per query, defined once. A ``doc_id`` written inline at a call site is the literal
this repository's provenance gate exists to catch, and a rotated one returns an error envelope
under HTTP 200, so nothing downstream would notice the drift.

Rotation is the most fragile thing in the system. When a query starts failing, the first
suspect is the id below, and the fix is a replay through the `reverse-engineer` skill rather
than an edit here.

Every entry names the finding it came from, in
``skills/reverse-engineer/knowledge/endpoints/``.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
   "API_GRAPHQL_URL",
   "BADGE_COUNT",
   "CHAT_TABS_JEWEL",
   "GRAPHQL_QUERY_URL",
   "HOME_TIMELINE_FEED",
   "OMNI_PICKER_NULL_STATE",
   "PROFILE_BY_ID",
   "PROFILE_HIGHLIGHTS",
   "PROFILE_NOTE_BUBBLE",
   "PROFILE_POSTS",
   "PROFILE_SCHOOL_BADGE",
   "PROFILE_SUGGESTED_USERS",
   "QUICK_PROMOTION",
   "STORIES_TRAY",
   "THREAD_DETAIL",
   "THREAD_MESSAGE_PAGE",
   "THREAD_OLDER_PAGE",
   "PersistedQuery",
]

API_GRAPHQL_URL = "https://www.instagram.com/api/graphql"
"""Where every query observed before the feed answered."""

GRAPHQL_QUERY_URL = "https://www.instagram.com/graphql/query"
"""Where the timeline feed answers, and the reason the path is per query rather than global.

The feed query posted to :data:`API_GRAPHQL_URL` with the same id, the same headers and the
same variables returned HTTP 200 carrying a null connection, with no ``errors`` array, no
``error`` field and no ``errorSummary``. That is a silent wrong answer rather than a failure,
and no classifier reading error envelopes would catch it, so the path is part of each query's
contract.

Observed on 2026-09-21, recorded in
``skills/reverse-engineer/knowledge/patterns/the-timeline-feed-answers-only-on-graphql-query-and-api-grap.md``.
"""


@dataclass(frozen=True)
class PersistedQuery:
   """One persisted Relay query, identified the way the upstream identifies it.

   ``friendly_name`` is sent twice, as the ``fb_api_req_friendly_name`` body field and as the
   ``x-fb-friendly-name`` header. The upstream validated neither under ablation. They are sent
   because a request that omits what a browser sends is a fingerprint.

   ``url`` is the path this particular query answers on, and it is per query because two
   paths were observed and posting to the wrong one succeeds emptily. See
   :data:`GRAPHQL_QUERY_URL`.

   ``root_field`` is the response's root field. A browser names it in the
   ``x-root-field-name`` header on every request to :data:`GRAPHQL_QUERY_URL` and on none to
   :data:`API_GRAPHQL_URL`, so a query on that path carries one.
   """

   doc_id: str
   friendly_name: str
   finding_id: str
   url: str = API_GRAPHQL_URL
   root_field: str | None = None

   @property
   def sends_path_headers(self) -> bool:
      """Whether a browser sends ``x-bloks-version-id`` and ``x-root-field-name`` with it.

      Every request to :data:`GRAPHQL_QUERY_URL` captured on 2026-09-23 carried both, and no
      request to :data:`API_GRAPHQL_URL` carried either, so the path decides it. Recorded in
      ``skills/reverse-engineer/knowledge/patterns/every-graphql-query-request-carries-x-bloks-version-id-and-x.md``.
      """

      return self.url == GRAPHQL_QUERY_URL


THREAD_MESSAGE_PAGE = PersistedQuery(
   doc_id="27502152406082940",
   friendly_name="useIGDMessageListPaginationQuery",
   finding_id="direct-thread-message-page",
)
"""One page of messages in one direct thread, 20 edges, capped server side.

Observed live on 2026-09-20 and again on 2026-09-21.
"""


THREAD_DETAIL = PersistedQuery(
   doc_id="28730473946590056",
   friendly_name="IGDThreadDetailQuery",
   finding_id="open-a-direct-thread",
)
"""What a browser sends to open a thread: the thread, with its newest 20 messages.

The messages are the same 28-key nodes :data:`THREAD_OLDER_PAGE` returns, under a different
root field, and the connection's ``end_cursor`` is what the browser's first older page sends
as ``after``.

Observed on two cold loads of a thread on 2026-09-23 and replayed twice the same day.
"""

THREAD_OLDER_PAGE = PersistedQuery(
   doc_id="28079551424999855",
   friendly_name="IGDMessageListOffMsysQuery",
   finding_id="direct-thread-older-page-offmsys",
)
"""What a browser sends for each older page of a thread as it scrolls up.

The same variables and root field as :data:`THREAD_MESSAGE_PAGE`, under a new name and id. On
2026-09-23 a browser sent this one twelve times across two captures and the old one never,
while the old one still answered a replay the same day.
"""


PROFILE_BY_ID = PersistedQuery(
   doc_id="28036671149327607",
   friendly_name="PolarisProfilePageContentQuery",
   finding_id="read-a-user-profile",
)
"""One account's profile, keyed on the numeric account id.

This query takes no username. Its compiled Relay artifact declares ``id`` as its only caller
argument and roots at ``fetch__XDTUserDict(id: $id)``, which is why a caller holding a
username reads it off the profile page first, or resolves it through :data:`PROFILE_POSTS`.

Observed live on 2026-09-21.
"""

PROFILE_POSTS = PersistedQuery(
   doc_id="29015124851429106",
   friendly_name="PolarisProfilePostsQuery",
   finding_id="resolve-a-username-to-a-user-id",
   url=GRAPHQL_QUERY_URL,
   root_field="xdt_api__v1__feed__user_timeline_graphql_connection",
)
"""The first posts on one account's timeline, keyed on the username.

A profile page sends it as one of its six queries. The engine also uses it for the one thing
it has that the profile query does not, a ``username`` argument, when a client departs from
the page route: the account id then comes off a post node, so an account with nothing visible
to the viewer resolves to nothing at all, and the capability reports that as
:class:`~dumpstagram.errors.NotFound`.

The obvious alternative, ``GET /api/v1/users/web_profile_info/?username=``, answered 429 with
an HTML body on its first and only attempt on 2026-09-21, so it is not used.

Observed live on 2026-09-21 on the other path under an older id. On 2026-09-23 both profile
cold loads sent this id to :data:`GRAPHQL_QUERY_URL`.
"""


PROFILE_NOTE_BUBBLE = PersistedQuery(
   doc_id="38260824646898178",
   friendly_name="PolarisProfileNoteBubbleQuery",
   finding_id="profile-page-note-bubble",
)
"""The note bubble over a profile picture. One of the six queries a profile page sends."""


PROFILE_HIGHLIGHTS = PersistedQuery(
   doc_id="26970053832668570",
   friendly_name="PolarisProfileStoryHighlightsTrayContentQuery",
   finding_id="profile-page-story-highlights",
)
"""The story highlights tray on a profile. One of the six queries a profile page sends."""


PROFILE_SUGGESTED_USERS = PersistedQuery(
   doc_id="27929823133325729",
   friendly_name="PolarisProfileSuggestedUsersWithPreloadableQuery",
   finding_id="profile-page-suggested-users",
)
"""Accounts suggested beside a profile. One of the six queries a profile page sends, and the
largest of the five companions, 30 kB and 117 kB in the two measured loads."""


PROFILE_SCHOOL_BADGE = PersistedQuery(
   doc_id="27862800913344283",
   friendly_name="PolarisSchoolPartnerProfileBadgeQuery",
   finding_id="profile-page-school-badge",
)
"""The school partner badge on a profile. One of the six queries a profile page sends."""


HOME_TIMELINE_FEED = PersistedQuery(
   doc_id="28639462595647642",
   friendly_name="PolarisFeedRootPaginationCachedQuery_subscribe",
   finding_id="home-timeline-feed-page",
   url=GRAPHQL_QUERY_URL,
   root_field="xdt_api__v1__feed__timeline__connection",
)
"""One page of the signed-in account's home timeline.

The only query in this registry that does not answer on :data:`API_GRAPHQL_URL`. The same
operation paginates and fetches the first page, with ``after`` null for the first, so there
is no first-page variant of it.

Observed live on 2026-09-21. On 2026-09-23 a browser's page two scroll sent a new id and the
engine moved to it. The old id still answered that day, so a rotation does not announce itself
and a passing request is no evidence that the id is current.
"""


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
carries it as a preloader instead."""
