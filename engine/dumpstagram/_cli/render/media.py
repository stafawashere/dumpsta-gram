"""A post, a post read on its own, and a page of its comments, in both output forms."""

from __future__ import annotations

from typing import Any

from dumpstagram.models import (
   Comment,
   Page,
   Post,
   PostDetail,
)

__all__ = [
   "describe_comment",
   "describe_comment_page",
   "describe_post",
   "describe_post_detail",
   "render_comment_page",
   "render_post_detail",
]


def describe_post(post: Post) -> dict[str, Any]:
   """The JSON form of one post. Every key here is part of the CLI's contract.

   ``id`` and ``pk`` are both present because they are different identifiers on this surface,
   which is unusual enough that dropping either would make a harness guess.

   ``images`` carries every rendition the upstream offered rather than one chosen here, since
   they are crops at several aspect ratios rather than one picture at several sizes.
   """

   return {
      "id": post.id,
      "pk": post.pk,
      "code": post.code,
      "taken_at": post.taken_at.isoformat(),
      "author": {
         "id": post.author.id,
         "username": post.author.username,
         "full_name": post.author.full_name,
         "is_private": post.author.is_private,
         "is_verified": post.author.is_verified,
         "profile_pic_url": post.author.profile_pic_url,
         "hd_profile_pic_url": post.author.hd_profile_pic_url,
         "is_following": post.author.is_following,
         "is_favorite": post.author.is_favorite,
      },
      "media_type": post.media_type,
      "product_type": post.product_type,
      "like_count": post.like_count,
      "comment_count": post.comment_count,
      "has_liked": post.has_liked,
      "is_seen": post.is_seen,
      "caption": post.caption,
      "accessibility_caption": post.accessibility_caption,
      "original_width": post.original_width,
      "original_height": post.original_height,
      "carousel_media_count": post.carousel_media_count,
      "images": [
         {"url": image.url, "width": image.width, "height": image.height} for image in post.images
      ],
      "is_paid_partnership": post.is_paid_partnership,
      "like_and_view_counts_disabled": post.like_and_view_counts_disabled,
   }


def describe_post_detail(post: PostDetail) -> dict[str, Any]:
   """The JSON form of one post read on its own. Every key here is part of the CLI's contract.

   The same keys as :func:`describe_post` without ``is_seen``, which this read does not carry.
   """

   described = describe_post(
      Post(
         id=post.id,
         pk=post.pk,
         code=post.code,
         taken_at=post.taken_at,
         author=post.author,
         media_type=post.media_type,
         product_type=post.product_type,
         like_count=post.like_count,
         comment_count=post.comment_count,
         has_liked=post.has_liked,
         is_seen=False,
         caption=post.caption,
         accessibility_caption=post.accessibility_caption,
         original_width=post.original_width,
         original_height=post.original_height,
         carousel_media_count=post.carousel_media_count,
         images=post.images,
         is_paid_partnership=post.is_paid_partnership,
         like_and_view_counts_disabled=post.like_and_view_counts_disabled,
      )
   )
   del described["is_seen"]

   return described


def render_post_detail(post: PostDetail) -> str:
   """The human form: the post's identifiers, then the viewer's like state and the counts."""

   caption = post.caption.splitlines()[0] if post.caption else ""

   return "\n".join(
      [
         f"{post.code}  pk {post.pk}  {post.author.username}  {post.taken_at.isoformat()}",
         f"has_liked: {post.has_liked}  likes: {post.like_count}  comments: {post.comment_count}",
         caption,
      ]
   ).rstrip("\n")


def describe_comment(comment: Comment) -> dict[str, Any]:
   """The JSON form of one comment. Every key here is part of the CLI's contract.

   The last four keys are null on a comment ``comment`` just created, because the answer to a
   new comment does not carry them.
   """

   return {
      "id": comment.id,
      "text": comment.text,
      "created_at": comment.created_at.isoformat(),
      "author": {
         "id": comment.author.id,
         "username": comment.author.username,
         "is_verified": comment.author.is_verified,
      },
      "like_count": comment.like_count,
      "reply_count": comment.reply_count,
      "parent_comment_id": comment.parent_comment_id,
      "has_liked": comment.has_liked,
   }


def describe_comment_page(page: Page[Comment]) -> dict[str, Any]:
   """One page of comments with its terminator, which is the only thing that says there is more.

   ``more_available`` is the page's own ``has_next_page``, never a guess from how many
   comments arrived.
   """

   return {
      "comment_count": len(page.items),
      "more_available": page.has_next_page,
      "end_cursor": page.end_cursor,
      "comments": [describe_comment(comment) for comment in page.items],
   }


def render_comment_page(page: Page[Comment]) -> str:
   """The human form: one line per comment in the upstream's order, then the terminator."""

   lines = [
      f"{comment.created_at.isoformat()}  {comment.id}  {comment.author.username}  {comment.text}"
      for comment in page.items
   ]
   more = f"more after {page.end_cursor}" if page.has_next_page else "no more comments"
   lines.append(f"{len(page.items)} comments, {more}")

   return "\n".join(lines)
