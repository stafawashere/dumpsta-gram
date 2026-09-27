"""The search queries: the viewer's recent searches, the non-personalised typeahead, and a
hashtag's header.

The personalised typeahead, ``PolarisSearchBoxContainerQuery``, and the keyword results grid,
``PolarisKeywordSearchExplorePageRelayQuery``, carry variables never observed and are not
registered until the capture night observes them (W83).
"""

from __future__ import annotations

from dumpstagram._private.web.documents.common import PersistedQuery

__all__ = [
   "HASHTAG_HEADER",
   "NON_PERSONALISED_TYPEAHEAD",
   "RECENT_SEARCHES",
]

RECENT_SEARCHES = PersistedQuery(
   doc_id="38466302779627407",
   friendly_name="PolarisSearchNullStateQuery",
   finding_id="read-recent-searches",
)
"""The viewer's recent searches, with no variables. Root ``xig_recent_searches``, whose
``recent_searches`` held 15 entries on both replays of 2026-09-27."""

NON_PERSONALISED_TYPEAHEAD = PersistedQuery(
   doc_id="27634848489527274",
   friendly_name="PolarisSearchBoxNonProfiledRefetchableQuery",
   finding_id="search-typeahead-non-personalised",
)
"""The accounts a query text matches, ranked without the viewer's profile, keyed on ``query``
with ``hasQuery`` true. Root ``xdt_api__v1__fbsearch__non_profiled_serp``, carrying ``users``, 18
on both replays of 2026-09-27, and ``inform_module``, null on both."""

HASHTAG_HEADER = PersistedQuery(
   doc_id="35337906325853853",
   friendly_name="PolarisHashtagHeaderActionButtonsQuery",
   finding_id="read-a-hashtag-header",
)
"""A hashtag page's header, keyed on ``tag_name`` without the ``#``. Root ``fetch__XDTTagInfo``,
carrying only ``id``, 179 bytes on both replays of 2026-09-27."""
