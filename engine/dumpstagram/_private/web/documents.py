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
   "GRAPHQL_QUERY_URL",
   "HOME_TIMELINE_FEED",
   "PROFILE_BY_ID",
   "THREAD_MESSAGE_PAGE",
   "USER_ID_BY_USERNAME",
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
   """

   doc_id: str
   friendly_name: str
   finding_id: str
   url: str = API_GRAPHQL_URL


THREAD_MESSAGE_PAGE = PersistedQuery(
   doc_id="27502152406082940",
   friendly_name="useIGDMessageListPaginationQuery",
   finding_id="direct-thread-message-page",
)
"""One page of messages in one direct thread, 20 edges, capped server side.

Observed live on 2026-09-20 and again on 2026-09-21.
"""


PROFILE_BY_ID = PersistedQuery(
   doc_id="28036671149327607",
   friendly_name="PolarisProfilePageContentQuery",
   finding_id="read-a-user-profile",
)
"""One account's profile, keyed on the numeric account id.

This query takes no username. Its compiled Relay artifact declares ``id`` as its only caller
argument and roots at ``fetch__XDTUserDict(id: $id)``, which is why a caller holding a
username has to resolve it through :data:`USER_ID_BY_USERNAME` first.

Observed live on 2026-09-21.
"""

USER_ID_BY_USERNAME = PersistedQuery(
   doc_id="28821682214127849",
   friendly_name="PolarisProfilePostsQuery",
   finding_id="resolve-a-username-to-a-user-id",
)
"""The account id behind a username, read out of the first post on that account's timeline.

This is the media timeline query and it is used here for the one thing it has that the
profile query does not, which is a ``username`` argument. Resolution therefore comes off a
post node, so an account with nothing visible to the viewer resolves to nothing at all. That
is a real limit of this route rather than a gap in the mapping, and the capability reports it
as :class:`~dumpstagram.errors.NotFound`.

The obvious alternative, ``GET /api/v1/users/web_profile_info/?username=``, answered 429 with
an HTML body on its first and only attempt on 2026-09-21, so it is not used.

Observed live on 2026-09-21.
"""


HOME_TIMELINE_FEED = PersistedQuery(
   doc_id="27932834733065642",
   friendly_name="PolarisFeedRootPaginationCachedQuery_subscribe",
   finding_id="home-timeline-feed-page",
   url=GRAPHQL_QUERY_URL,
)
"""One page of the signed-in account's home timeline.

The only query in this registry that does not answer on :data:`API_GRAPHQL_URL`. The same
operation paginates and fetches the first page, with ``after`` null for the first, so there
is no first-page variant of it.

Observed live on 2026-09-21.
"""
