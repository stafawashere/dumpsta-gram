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

__all__ = ["PROFILE_BY_ID", "THREAD_MESSAGE_PAGE", "USER_ID_BY_USERNAME", "PersistedQuery"]


@dataclass(frozen=True)
class PersistedQuery:
   """One persisted Relay query, identified the way the upstream identifies it.

   ``friendly_name`` is sent twice, as the ``fb_api_req_friendly_name`` body field and as the
   ``x-fb-friendly-name`` header. The upstream validated neither under ablation. They are sent
   because a request that omits what a browser sends is a fingerprint.
   """

   doc_id: str
   friendly_name: str
   finding_id: str


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
