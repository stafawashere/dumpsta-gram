"""The post queries: one post by shortcode or by media pk, like and unlike, a comment page, the
replies under a comment, the likers, the more posts from the author, and commenting and deleting
a comment.
"""

from __future__ import annotations

from dumpstagram._private.web.documents.common import GRAPHQL_QUERY_URL, PersistedQuery

__all__ = [
   "COMMENT_PAGE",
   "COMMENT_REPLIES",
   "COMMENT_REPLIES_NEXT_PAGE",
   "CREATE_COMMENT",
   "DELETE_COMMENT",
   "LIKE_MEDIA",
   "MORE_FROM_AUTHOR",
   "POST_BY_MEDIA_ID",
   "POST_BY_SHORTCODE",
   "POST_LIKERS",
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

COMMENT_REPLIES = PersistedQuery(
   doc_id="28027289793632076",
   friendly_name="PolarisPostChildCommentsQuery",
   finding_id="read-comment-replies",
)
"""The first replies under one comment, keyed on the media ``pk`` and the parent comment's id.

Replayed three times on 2026-09-27. It answered 9 replies with ``has_next_page`` false on a
comment with 9, and 11 with a cursor on a comment with 52, both with ``first`` 3, so ``first``
does not set how many come back.
"""

COMMENT_REPLIES_NEXT_PAGE = PersistedQuery(
   doc_id="27229753410037873",
   friendly_name="PolarisPostCommentsChildrenPaginationtQuery",
   finding_id="read-comment-replies-next-page",
)
"""The replies past their first page, keyed as :data:`COMMENT_REPLIES` is plus the previous
page's cursor. The name carries the upstream's own typo.

Replayed twice on 2026-09-27: 12 new replies, none of them on the first page, and a cursor.
"""

POST_LIKERS = PersistedQuery(
   doc_id="27928626103504365",
   friendly_name="PolarisPostLikedByListDialogQuery",
   finding_id="read-a-post-s-likers",
)
"""The accounts listed as liking one post, keyed on the media ``pk``, as the likes dialog lists
them. Root ``fetch__XDTMediaDict``, whose ``likers_connection`` carries ``nodes`` and no page
info.

Replayed twice on 2026-09-27: 98 accounts both times, on a post counting 193647 likes.
"""

POST_BY_MEDIA_ID = PersistedQuery(
   doc_id="28007559615590940",
   friendly_name="PolarisPostActionLoadPostQueryMediaIdQuery",
   finding_id="read-a-post-by-media-id",
   url=GRAPHQL_QUERY_URL,
   root_field="xdt_api__v1__media__media_id_web_info",
)
"""One post keyed on its media ``pk``, an item of the same family as :data:`POST_BY_SHORTCODE`.

Replayed twice on 2026-09-27, the first answer beside twelve field errors under the item and the
second with none.
"""

MORE_FROM_AUTHOR = PersistedQuery(
   doc_id="27764946129846908",
   friendly_name="PolarisDesktopPostPageRelatedMediaGridQuery",
   finding_id="read-more-posts-from-an-account",
   url=GRAPHQL_QUERY_URL,
   root_field="xdt_api__v1__profile_timeline",
)
"""The "more posts from" strip under a post, keyed on the author's numeric id and a count, and on
no post.

Replayed twice on 2026-09-27 with ``count`` 6: six posts, the same six in the same order both
times, none of them the post the author id was read from.
"""
