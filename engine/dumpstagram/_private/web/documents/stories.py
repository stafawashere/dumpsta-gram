"""The persisted query that reads one account's live stories or one highlight.

The stories tray is :data:`~dumpstagram._private.web.documents.page_load.STORIES_TRAY`, a page
load companion that ``stories.tray`` also reads. No seen mutation is registered here or anywhere
in the registry until the arranged run of E2 batch 12 verifies one (W68).
"""

from __future__ import annotations

from dumpstagram._private.web.documents.common import GRAPHQL_QUERY_URL, PersistedQuery

__all__ = ["STORY_REEL"]

STORY_REEL = PersistedQuery(
   doc_id="29184890191114309",
   friendly_name="PolarisStoriesV3ReelPageStandaloneQuery",
   finding_id="read-one-account-s-stories-or-a-highlight",
   url=GRAPHQL_QUERY_URL,
   root_field="xdt_api__v1__feed__reels_media",
)
"""One account's live stories keyed on ``reel_ids_arr`` of its account id, or one highlight
keyed on ``reel_ids_arr`` of its ``highlight:<number>`` with ``is_highlight`` true. Root
``xdt_api__v1__feed__reels_media``, whose ``reels_media`` lists the reels answered.

Replayed on 2026-09-27: the owner's highlight twice, one reel of 18 items each time, and the
owner's own reel once, no reel, since he had no live story. The read marks nothing seen
(INFERENCE, the browser sends ``PolarisStoriesV3SeenMutation`` separately for each item).
"""
