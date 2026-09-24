"""The post queries: one post by shortcode, like and unlike, a comment page, and commenting and
deleting a comment.
"""

from __future__ import annotations

from dumpstagram._private.web.documents.common import PersistedQuery

__all__ = [
   "COMMENT_PAGE",
   "CREATE_COMMENT",
   "DELETE_COMMENT",
   "LIKE_MEDIA",
   "POST_BY_SHORTCODE",
   "UNLIKE_MEDIA",
]

POST_BY_SHORTCODE = PersistedQuery(
   doc_id="27830990013244856",
   friendly_name="PolarisPostRootQuery",
   finding_id="read-a-post-by-shortcode",
)
"""One post, keyed on the shortcode in its web address, as the post page reads it.

The item carries both of the post's identifiers, ``pk`` and ``id`` in the ``<pk>_<owner id>``
form, and ``has_liked`` and ``like_count`` for the viewer. It does not carry ``is_seen``, which
the timeline's media node does.

Read off the compiled Relay artifact on 2026-09-23 and verified by four engine reads the same
day, under ruling 23, which allowed no browser load. The post page's own burst is unrecorded.
"""

LIKE_MEDIA = PersistedQuery(
   doc_id="27182485238052618",
   friendly_name="usePolarisLikeMediaXIGLikeMutation",
   finding_id="like-a-post",
)
"""Like one post, keyed on the media ``pk``. The like button on a post and in the feed holds it.

The answer echoes the media under its other identifier, ``<pk>_<owner id>``, with
``has_liked``. Liking a post that is already liked answers the same way and changes nothing,
observed once on 2026-09-23. Verified by two engine sends that day, under ruling 23.
"""

UNLIKE_MEDIA = PersistedQuery(
   doc_id="27345296031770102",
   friendly_name="usePolarisLikeMediaXIGUnlikeMutation",
   finding_id="unlike-a-post",
)
"""Unlike one post, the same input as :data:`LIKE_MEDIA` under its own id and root field.

Unliking a post that is not liked answers ``has_liked`` false and changes nothing, observed
once on 2026-09-23. Verified by two engine sends that day, under ruling 23.
"""

COMMENT_PAGE = PersistedQuery(
   doc_id="28169471862682868",
   friendly_name="PolarisPostCommentsPaginationQuery",
   finding_id="read-a-post-comment-page",
)
"""One page of a post's comments, keyed on the media ``pk``, pages chained by ``end_cursor``.

The post page reads its first page with another query and pages on with this one. The engine
sends this one for every page, which the four engine reads of 2026-09-23 did, under ruling 23.
None of them saw a second page, so the ``after`` path has not been observed answering.
"""

CREATE_COMMENT = PersistedQuery(
   doc_id="27261905640092552",
   friendly_name="PolarisPostCommentInputRevampedMutation",
   finding_id="comment-on-a-post",
)
"""Add a comment to a post, keyed on the media ``pk``. The comment box on a post page holds it.

The answer carries the created comment under ``comment_dict``, whose ``pk`` is the id the
comment page lists and the delete takes. Verified by two engine sends on 2026-09-23, under
ruling 23, each deleted in the same run.
"""

DELETE_COMMENT = PersistedQuery(
   doc_id="27034318419564986",
   friendly_name="usePolarisPostDeleteCommentMutation",
   finding_id="delete-my-own-comment",
)
"""Delete one comment, keyed on the comment id and the media ``pk`` together.

A real delete answers its root field with an object. A delete naming no comment answered it
null with no error, so a null root is not a delete. Verified by two engine sends on 2026-09-23,
each confirmed by a comment page read, under ruling 23.
"""
