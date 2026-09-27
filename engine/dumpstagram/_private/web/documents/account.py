"""The viewer's own account queries: the saved tab's collections.

The pending follow requests, the activity feed, the saved posts and the close friends list are
REST or Bloks reads and have no entry here.
"""

from __future__ import annotations

from dumpstagram._private.web.documents.common import PersistedQuery

__all__ = ["SAVED_COLLECTIONS"]

SAVED_COLLECTIONS = PersistedQuery(
   doc_id="27584326974521636",
   friendly_name="PolarisProfileSavedTabContentQuery",
   finding_id="read-saved-posts",
)
"""The saved tab's first page, the collections it lists, keyed on the constant
``collection_types`` list of three values with ``first`` 12. Root
``viewer.collections_unified_with_auto_collections``. Replayed twice on 2026-09-27, 32148 bytes
each: the "All posts" and "Audio" automatic collections and ``has_next_page`` false (W106).
"""
