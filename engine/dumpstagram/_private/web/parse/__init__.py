"""Map one GraphQL payload into typed models, one module per domain.

This is the only package that knows both the upstream field names and the public models, and
that is deliberate: ADR-0007 requires GraphQL shapes to stop before ``_core``, so the mapping
happens on the surface adapter rather than one layer up.

Mapping is explicit and total. Every field is read by name, a missing required key raises
:class:`~dumpstagram.errors.SchemaChanged` carrying the path that was missing, and unknown
keys are ignored. Nothing is splatted into a constructor, because a permissive mapper turns
an upstream rename into silently degraded records rather than an error.
"""
