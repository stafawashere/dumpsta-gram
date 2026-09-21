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

__all__ = ["THREAD_MESSAGE_PAGE", "PersistedQuery"]


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
