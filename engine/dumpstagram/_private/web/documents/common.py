"""The two paths a persisted query answers on, and the record every query in the registry is.

The queries themselves live in the domain modules beside this one.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
   "API_GRAPHQL_URL",
   "GRAPHQL_QUERY_URL",
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
