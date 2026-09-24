"""Home timeline pages, every item with its kind, in both output forms."""

from __future__ import annotations

from typing import Any

from dumpstagram._cli.render.media import describe_post
from dumpstagram.models import (
   FeedItem,
   FeedItemKind,
   Page,
)

__all__ = [
   "describe_feed_item",
   "describe_feed_pages",
   "render_feed",
]


def describe_feed_item(item: FeedItem) -> dict[str, Any]:
   return {
      "kind": item.kind.value,
      "post": describe_post(item.post) if item.post is not None else None,
   }


def describe_feed_pages(pages: list[Page[FeedItem]]) -> dict[str, Any]:
   """What was read, including the terminator and the split between posts and everything else.

   ``more_available`` comes from the last page's own `has_next_page`, never from the number of
   items that arrived. ``item_count`` and ``post_count`` are both reported because they differ
   on every page measured, and reporting only one of them would make the other a guess.
   """

   last = pages[-1] if pages else None
   items = [item for page in pages for item in page.items]
   kinds: dict[str, int] = {}

   for item in items:
      kinds[item.kind.value] = kinds.get(item.kind.value, 0) + 1

   return {
      "pages_read": len(pages),
      "item_count": len(items),
      "post_count": sum(1 for item in items if item.kind is FeedItemKind.POST),
      "kinds": dict(sorted(kinds.items())),
      "more_available": last.has_next_page if last is not None else False,
      "end_cursor": last.end_cursor if last is not None else None,
   }


def render_feed(pages: list[Page[FeedItem]], *, posts_only: bool = False) -> str:
   """The human form: one line per item, in the order the upstream sent them.

   An item that is not a post is printed as its kind alone, so the shape of a real timeline
   stays visible instead of a filtered list that never explains its own length.

   ``posts_only`` drops those lines on request. The trailer still counts every item that
   arrived, so a filtered listing says how much it hid rather than looking like a short page.
   """

   lines = []

   for page in pages:
      for item in page.items:
         post = item.post

         if post is None:
            if not posts_only:
               lines.append(f"{item.kind.value}")

            continue

         caption = post.caption.splitlines()[0] if post.caption else ""
         lines.append(
            f"{post.taken_at.isoformat()}  {post.author.username}  "
            f"likes {post.like_count}  comments {post.comment_count}  {post.code}  {caption}"
         )

   trailer = describe_feed_pages(pages)
   lines.append(
      f"pages_read: {trailer['pages_read']}  items: {trailer['item_count']}  "
      f"posts: {trailer['post_count']}  more_available: {trailer['more_available']}"
   )

   if trailer["end_cursor"]:
      lines.append(f"next_cursor: {trailer['end_cursor']}")

   return "\n".join(lines)
