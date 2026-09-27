"""A profile's reels tab and tagged tab, in both output forms.

They live apart from ``profiles.py`` because the tagged tab's posts are rendered as the strip
under a post renders them, and that module imports ``profiles.py``.
"""

from __future__ import annotations

from typing import Any

from dumpstagram._cli.render.post_depth import describe_post_thumbnail
from dumpstagram.models import ProfileReels, ReelThumbnail, TaggedPosts

__all__ = [
   "describe_profile_reels",
   "describe_tagged_posts",
   "render_profile_reels",
   "render_tagged_posts",
]


def describe_reel_thumbnail(reel: ReelThumbnail) -> dict[str, Any]:
   """The JSON form of one reel on a profile's reels tab. Every key is part of the CLI's
   contract."""

   return {
      "id": reel.id,
      "pk": reel.pk,
      "code": reel.code,
      "author_id": reel.author_id,
      "media_type": reel.media_type,
      "product_type": reel.product_type,
      "like_count": reel.like_count,
      "comment_count": reel.comment_count,
      "like_and_view_counts_disabled": reel.like_and_view_counts_disabled,
      "play_count": reel.play_count,
      "original_width": reel.original_width,
      "original_height": reel.original_height,
      "images": [
         {"url": image.url, "width": image.width, "height": image.height} for image in reel.images
      ],
   }


def describe_profile_reels(tab: ProfileReels) -> dict[str, Any]:
   return {
      "reel_count": len(tab.reels),
      "more_available": tab.has_more,
      "reels": [describe_reel_thumbnail(reel) for reel in tab.reels],
   }


def render_profile_reels(tab: ProfileReels) -> str:
   """One line per reel in the tab's order, then the trailer."""

   lines = [
      f"{reel.code}  plays {reel.play_count}  likes {reel.like_count}  "
      f"comments {reel.comment_count}"
      for reel in tab.reels
   ]
   lines.append(f"reels: {len(tab.reels)}  more_available: {tab.has_more}")

   return "\n".join(lines)


def describe_tagged_posts(tab: TaggedPosts) -> dict[str, Any]:
   return {
      "post_count": len(tab.posts),
      "more_available": tab.has_more,
      "posts": [describe_post_thumbnail(post) for post in tab.posts],
   }


def render_tagged_posts(tab: TaggedPosts) -> str:
   """One line per post in the tab's order, its author first, then the trailer."""

   lines = []

   for post in tab.posts:
      caption = post.caption.splitlines()[0] if post.caption else ""
      lines.append(
         f"{post.code}  {post.author_username}  likes {post.like_count}  "
         f"comments {post.comment_count}  {caption}"
      )

   lines.append(f"posts: {len(tab.posts)}  more_available: {tab.has_more}")

   return "\n".join(lines)
