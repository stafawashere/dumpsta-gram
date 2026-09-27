"""The replies under a comment, a post's likers, the more posts from its author and a whole post
page, in both output forms."""

from __future__ import annotations

from typing import Any

from dumpstagram._cli.render.media import (
   describe_comment,
   describe_comment_page,
   describe_post_detail,
   render_comment_page,
   render_post_detail,
)
from dumpstagram._cli.render.profiles import describe_profile_summary, render_profile_summaries
from dumpstagram.models import Comment, Page, PostPage, PostThumbnail, ProfileSummary

__all__ = [
   "describe_likers",
   "describe_post_page",
   "describe_post_thumbnail",
   "describe_reply_pages",
   "render_likers",
   "render_post_page",
   "render_post_thumbnails",
   "render_reply_pages",
]


def describe_reply_pages(pages: list[Page[Comment]]) -> dict[str, Any]:
   """What was read, with the last page's own terminator and cursor, never a count of replies."""

   last_page = pages[-1] if pages else None

   return {
      "pages_read": len(pages),
      "reply_count": sum(len(page.items) for page in pages),
      "more_available": last_page.has_next_page if last_page is not None else False,
      "end_cursor": last_page.end_cursor if last_page is not None else None,
      "replies": [describe_comment(reply) for page in pages for reply in page.items],
   }


def render_reply_pages(pages: list[Page[Comment]]) -> str:
   """One line per reply, oldest first, then the trailer and the cursor to go on from."""

   lines = [
      f"{reply.created_at.isoformat()}  {reply.id}  {reply.author.username}  {reply.text}"
      for page in pages
      for reply in page.items
   ]
   trailer = describe_reply_pages(pages)
   lines.append(
      f"pages_read: {trailer['pages_read']}  replies: {trailer['reply_count']}  "
      f"more_available: {trailer['more_available']}"
   )

   if trailer["end_cursor"]:
      lines.append(f"next_cursor: {trailer['end_cursor']}")

   return "\n".join(lines)


def describe_likers(likers: tuple[ProfileSummary, ...]) -> dict[str, Any]:
   """The accounts as listed, and how many, which is not the post's like count."""

   return {
      "account_count": len(likers),
      "accounts": [describe_profile_summary(account) for account in likers],
   }


def render_likers(likers: tuple[ProfileSummary, ...]) -> str:
   return render_profile_summaries(likers)


def describe_post_thumbnail(thumbnail: PostThumbnail) -> dict[str, Any]:
   """The JSON form of one post in the "more posts from" strip. Every key is part of the CLI's
   contract."""

   return {
      "id": thumbnail.id,
      "pk": thumbnail.pk,
      "code": thumbnail.code,
      "author_id": thumbnail.author_id,
      "author_username": thumbnail.author_username,
      "media_type": thumbnail.media_type,
      "product_type": thumbnail.product_type,
      "like_count": thumbnail.like_count,
      "comment_count": thumbnail.comment_count,
      "like_and_view_counts_disabled": thumbnail.like_and_view_counts_disabled,
      "caption": thumbnail.caption,
      "carousel_media_count": thumbnail.carousel_media_count,
      "images": [
         {"url": image.url, "width": image.width, "height": image.height}
         for image in thumbnail.images
      ],
   }


def render_post_thumbnails(thumbnails: tuple[PostThumbnail, ...]) -> str:
   """One line per post in the strip's order, then how many."""

   lines = []

   for thumbnail in thumbnails:
      caption = thumbnail.caption.splitlines()[0] if thumbnail.caption else ""
      lines.append(
         f"{thumbnail.code}  pk {thumbnail.pk}  likes {thumbnail.like_count}  "
         f"comments {thumbnail.comment_count}  {caption}"
      )

   lines.append(f"posts: {len(thumbnails)}")

   return "\n".join(lines)


def describe_post_page(page: PostPage) -> dict[str, Any]:
   """The post, its first comments with their terminator, and the author's grid. Every key is
   part of the CLI's contract."""

   return {
      "post": describe_post_detail(page.post),
      "comments": describe_comment_page(page.comments),
      "author_grid": [describe_post_thumbnail(thumbnail) for thumbnail in page.author_grid],
   }


def render_post_page(page: PostPage) -> str:
   """The post, a blank line, its first comments, a blank line, then the author's grid."""

   sections = [
      render_post_detail(page.post),
      render_comment_page(page.comments),
      render_post_thumbnails(page.author_grid),
   ]

   return "\n\n".join(sections)
