"""The persisted query that reads one account's live stories or one highlight, and the mutation
that marks one story item seen.

The stories tray is :data:`~dumpstagram._private.web.documents.page_load.STORIES_TRAY`, a page
load companion that ``stories.tray`` also reads. The seen mutation is registered since E2 batch 12
(W93). Its two alternate compiled routes, ``PolarisAPIReelSeenMutation`` and
``PolarisAPIForceStorySeenMutation``, which no recorded browse sent, are not.
"""

from __future__ import annotations

from dumpstagram._private.web.documents.common import (
   API_GRAPHQL_URL,
   GRAPHQL_QUERY_URL,
   PersistedQuery,
)

__all__ = ["STORY_REEL", "STORY_SEEN"]

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


STORY_SEEN = PersistedQuery(
   doc_id="26234228992942885",
   friendly_name="PolarisStoriesV3SeenMutation",
   finding_id="mark-a-story-seen",
   url=API_GRAPHQL_URL,
)
"""Mark one story item seen, keyed on ``reelId``, ``reelMediaId``, ``reelMediaOwnerId``,
``reelMediaTakenAt`` and ``viewSeenAt``, the last two whole seconds. Root
``xdt_mark_story_reel_seen``, an ``XDTMarkSeenResponse``.

A write another person can see: the item's owner sees the viewer in its seen list. Observed on
2026-09-27, run ``run-2026-09-27-135628``, when the owner opened his own highlight: the page sent
it once, 1.3 s after the document, and it answered 196 bytes. The engine replayed it once the
same day on the second item of that highlight, same answer. A highlight read carries no seen
field, so the answer is the only confirmation there is.
"""
