"""The discovery queries: a place's header and its grid, whether the home feed has new posts,
and the reels feed's two pages.

The explore grid is a REST read and has no entry here. The grid's next page query,
``PolarisLocationPageTabContentQuery_connection``, is not registered: on the first page's cursor
it answered that same cursor again with 20 of its 24 posts already on the first page, so nothing
here sends it (W79).
"""

from __future__ import annotations

from dumpstagram._private.web.documents.common import GRAPHQL_QUERY_URL, PersistedQuery

__all__ = [
   "LOCATION_INFO",
   "LOCATION_POSTS",
   "NEW_FEED_POSTS",
   "REELS_FEED_FIRST_PAGE",
   "REELS_FEED_NEXT_PAGE",
]

LOCATION_INFO = PersistedQuery(
   doc_id="28572807415659320",
   friendly_name="PolarisExploreLocationsContainerQuery",
   finding_id="read-a-location-s-info",
)
"""A place's header, keyed on ``location_id_str`` with ``show_nearby`` false. Root
``xdt_location_get_web_info``, whose ``native_location_data.location_info`` is the place.

Replayed twice on 2026-09-27, 521 bytes each, the same place both times.
"""

LOCATION_POSTS = PersistedQuery(
   doc_id="28211016731901625",
   friendly_name="PolarisLocationPageTabContentQuery",
   finding_id="read-a-location-page-tab",
   url=GRAPHQL_QUERY_URL,
   root_field="xdt_location_get_web_info_tab",
)
"""The first page of a place's grid, keyed on ``location_id`` and ``tab``, with ``first`` 12 and
``after`` null. Replayed twice on 2026-09-27 with ``tab`` ranked: 21 edges, ``has_next_page``
true and a 32 character cursor both times."""

NEW_FEED_POSTS = PersistedQuery(
   doc_id="29095516470048516",
   friendly_name="PolarisAPICheckNewFeedPostsExistQuery",
   finding_id="check-for-new-feed-posts",
)
"""Whether the home feed has posts newer than the viewer last loaded, with no variables. Root
``xdt_api__v1__new_feed_posts_exist``, carrying ``new_feed_posts_exist``, false on both replays
of 2026-09-27."""


REELS_FEED_FIRST_PAGE = PersistedQuery(
   doc_id="38583065568003775",
   friendly_name="PolarisClipsTabDesktopContainerQuery",
   finding_id="read-the-reels-tab-first-page",
   url=GRAPHQL_QUERY_URL,
   root_field="xdt_api__v1__clips__home__connection_v2",
)
"""The reels feed's first page as the ``/reels/`` tab sends it, keyed on the constant
``data.container_module`` with ``first`` 2. Replayed twice on 2026-09-27: 1 and 2 reels, each
with ``has_next_page`` true and a cursor (W101)."""

REELS_FEED_NEXT_PAGE = PersistedQuery(
   doc_id="28230813126620480",
   friendly_name="PolarisClipsTabDesktopPaginationQuery",
   finding_id="read-the-reels-tab-next-page",
   url=GRAPHQL_QUERY_URL,
   root_field="xdt_api__v1__clips__home__connection_v2",
)
"""The reels feed's next page, keyed on the previous page's cursor and ``data.seen_reels``, a JSON
string listing the reels already shown, with ``first`` 10. Replayed twice on 2026-09-27 on the
first page's cursor: 4 reels each, none of them on the first page (W101)."""
