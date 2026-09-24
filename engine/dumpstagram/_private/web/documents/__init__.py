"""The registry of persisted GraphQL query ids, one module per domain.

One name per query, defined once. A ``doc_id`` written inline at a call site is the literal
this repository's provenance gate exists to catch, and a rotated one returns an error envelope
under HTTP 200, so nothing downstream would notice the drift.

Rotation is the most fragile thing in the system. When a query starts failing, the first
suspect is the id in this registry, and the fix is a replay through the `reverse-engineer`
skill rather than an edit here.

Every entry names the finding it came from, in
``skills/reverse-engineer/knowledge/endpoints/``. :mod:`.common` holds the two paths a query
answers on and :class:`~dumpstagram._private.web.documents.common.PersistedQuery` itself.
"""
