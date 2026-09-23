"""A comment on a post, as the comment page lists it and as a new comment is answered.

Every field below was present on the comment page node and on the created comment the engine
read on 2026-09-23, recorded in
`skills/reverse-engineer/knowledge/endpoints/read-a-post-comment-page.md`,
`skills/reverse-engineer/knowledge/endpoints/comment-on-a-post.md` and in
`engine/logs/comment-discovery-cycle-2026-09-23-054051.json`. The sample is the viewer's own
two comments on the viewer's own post, which is narrow: no reply, no liked comment and no
comment by anyone else has been read.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

__all__ = ["Comment", "CommentAuthor"]


@dataclass(frozen=True)
class CommentAuthor:
   """The account that wrote a comment.

   ``id`` is the numeric account identifier, the one
   :meth:`~dumpstagram.aio.AsyncClient.profile_by_id` takes. The upstream sends it as both
   ``pk`` and ``id``.
   """

   id: str
   username: str
   is_verified: bool
   profile_pic_url: str


@dataclass(frozen=True)
class Comment:
   """One comment on a post.

   ``id`` is the comment's own number, 17 digits on both observed, and the identifier
   :meth:`~dumpstagram.aio.AsyncClient.delete_comment` takes. ``created_at`` is timezone-aware
   UTC.

   The last four fields come from the comment page and are None on the comment
   :meth:`~dumpstagram.aio.AsyncClient.comment` returns, because the answer to a new comment
   does not carry them. ``like_count`` is how many accounts like the comment, ``reply_count``
   how many replies it has, ``parent_comment_id`` the comment it replies to, None for a comment
   on the post itself, and ``has_liked`` whether the viewer likes it.
   """

   id: str
   text: str
   created_at: datetime
   author: CommentAuthor
   like_count: int | None = None
   reply_count: int | None = None
   parent_comment_id: str | None = None
   has_liked: bool | None = None
