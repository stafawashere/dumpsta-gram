"""The home timeline query, the one query in the registry on the ``/graphql/query`` path."""

from __future__ import annotations

from dumpstagram._private.web.documents.common import GRAPHQL_QUERY_URL, PersistedQuery

__all__ = [
   "HOME_TIMELINE_FEED",
]

HOME_TIMELINE_FEED = PersistedQuery(
   doc_id="28639462595647642",
   friendly_name="PolarisFeedRootPaginationCachedQuery_subscribe",
   finding_id="home-timeline-feed-page",
   url=GRAPHQL_QUERY_URL,
   root_field="xdt_api__v1__feed__timeline__connection",
)
"""One page of the signed-in account's home timeline.

The only query in this registry that does not answer on
:data:`~dumpstagram._private.web.documents.common.API_GRAPHQL_URL`. The same operation paginates
and fetches the first page, with ``after`` null for the first, so there is no first-page variant
of it.

Observed live on 2026-09-21. On 2026-09-23 a browser's page two scroll sent a new id and the
engine moved to it. The old id still answered that day, so a rotation does not announce itself
and a passing request is no evidence that the id is current.
"""
