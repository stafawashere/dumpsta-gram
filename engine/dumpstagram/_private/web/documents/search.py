"""The search queries: the viewer's recent searches, both typeaheads, a hashtag's header and the
keyword grid.

The search box's container query, ``PolarisSearchBoxContainerQuery``, was not sent by the
browser the capture night observed, which sent the refetchable query on typing, so it stays
unregistered (W102).
"""

from __future__ import annotations

from dumpstagram._private.web.documents.common import PersistedQuery

__all__ = [
   "HASHTAG_HEADER",
   "KEYWORD_RESULTS",
   "NON_PERSONALISED_TYPEAHEAD",
   "PERSONALISED_TYPEAHEAD",
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


PERSONALISED_TYPEAHEAD = PersistedQuery(
   doc_id="27706427925724183",
   friendly_name="PolarisSearchBoxRefetchableQuery",
   finding_id="search-typeahead-personalised-as-sent",
)
"""The search box's typeahead as a signed-in browser sends it on typing, keyed on ``data.query``
with a client made ``search_session_id``, an empty ``rank_token`` and three constants, and
``hasQuery`` true. Root ``xdt_api__v1__fbsearch__topsearch_connection``, carrying ``users``,
``hashtags``, ``places``, the keyword suggestions under ``see_more``, ``inform_module`` and a
``rank_token``; 5 accounts, 1 keyword and no hashtag or place on both replays of 2026-09-27
(W102)."""

KEYWORD_RESULTS = PersistedQuery(
   doc_id="37324993597144881",
   friendly_name="PolarisKeywordSearchExplorePageRelayQuery",
   finding_id="read-keyword-search-results",
)
"""The keyword grid's first page, keyed on ``query`` and one client made uuid sent as both
``search_session_id`` and ``serp_session_id``. Root ``xdt_fbsearch__top_serp_graphql`` beside
``xdt_viewer``; 11 rows, 24 posts and ``has_next_page`` true on both replays of 2026-09-27
(W103)."""
