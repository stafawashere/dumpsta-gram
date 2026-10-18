"""One post: its media model, its comments by page and by item, and a rendition downloaded.

Live requests: 1 for the post and 1 for its first comment page, plus 1 when the iterator reads a
second page. Without --code the post is the first one in the home feed, which adds that feed
read, about 6 under parity or 1 with --quick. --download adds 1 CDN fetch that takes no pacer
slot and carries no cookie.

   uv run python docs/demo/post.py --quick
   uv run python docs/demo/post.py --code CODE --download media/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _common import SHOWN_ITEMS, Demo, build_parser, line, preview, run, show_call, yes_no

from dumpstagram import FeedItemKind, MediaImage, PostDetail, SyncClient

FEED_SEARCH_LIMIT = 30

MEDIA_KINDS = {1: "photo", 2: "video", 8: "carousel"}


def first_post_code(client: SyncClient) -> str | None:
   for item in client.feeds.iter_home(limit=FEED_SEARCH_LIMIT):
      is_post = item.kind is FeedItemKind.POST

      if is_post and item.post is not None:
         return item.post.code

   return None


def describe_media(post: PostDetail) -> None:
   kind = MEDIA_KINDS.get(post.media_type, f"media type {post.media_type}")

   line(f"{kind}, {post.product_type}, taken {post.taken_at:%Y-%m-%d %H:%M}")
   line(
      f"{post.like_count:,} likes, {post.comment_count:,} comments, liked {yes_no(post.has_liked)}"
   )
   line(f"{len(post.images)} image renditions, {len(post.videos)} video renditions")

   if post.video_duration is not None:
      line(f"{post.video_duration:.1f} s long, audio {yes_no(post.has_audio)}")

   if post.audio is not None:
      line(f"audio is {post.audio.kind.name}: {preview(post.audio.title)}")

   if not post.carousel_children:
      return

   slide_kinds: dict[str, int] = {}

   for child in post.carousel_children:
      child_kind = MEDIA_KINDS.get(child.media_type, str(child.media_type))
      slide_kinds[child_kind] = slide_kinds.get(child_kind, 0) + 1

   slide_summary = ", ".join(f"{count} {kind}" for kind, count in slide_kinds.items())
   first_slide = post.carousel_children[0]

   line(f"{len(post.carousel_children)} slides: {slide_summary}")
   line(
      f"slide 1 has {len(first_slide.images)} image and {len(first_slide.videos)} video renditions"
   )


def largest_image(post: PostDetail) -> MediaImage | None:
   images = list(post.images)

   for child in post.carousel_children:
      images.extend(child.images)

   if not images:
      return None

   return max(images, key=lambda image: image.width * image.height)


def show_comments(demo: Demo, client: SyncClient, post: PostDetail, limit: int) -> None:
   demo.tour.section("Comments", "page = client.media.comments(post.pk)")

   comments = client.media.comments(post.pk)
   line(f"Page[Comment], {len(comments.items)} comments, has_next_page={comments.has_next_page}")

   for comment in comments.items[:SHOWN_ITEMS]:
      replies = f", {comment.reply_count} replies" if comment.reply_count else ""
      line(f"@{comment.author.username:<18} {preview(comment.text)}{replies}", depth=2)

   demo.report["comments_page_one"] = len(comments.items)

   if not comments.has_next_page:
      return

   print()
   show_call(f"client.media.iter_comments(post.pk, limit={limit}, after=page.end_cursor)")

   walk = client.media.iter_comments(post.pk, limit=limit, after=comments.end_cursor)
   walked = list(walk)

   line(f"{len(walked)} more comments walked")
   demo.report["comments_iterated"] = len(walked)


def download(demo: Demo, client: SyncClient, post: PostDetail, directory: Path) -> None:
   demo.tour.section(
      "Download",
      "image = max(post.images, key=lambda image: image.width * image.height)",
      f'client.media.download(image, "{directory}/{post.code}.jpg", overwrite=True)',
   )

   image = largest_image(post)

   if image is None:
      line("the post carries no image rendition")
      return

   directory.mkdir(parents=True, exist_ok=True)
   saved = client.media.download(image, directory / f"{post.code}.jpg", overwrite=True)
   size = saved.stat().st_size

   line(f"{image.width}x{image.height}, {size:,} bytes to {saved}")
   demo.report["downloaded_bytes"] = size


def tour(demo: Demo, arguments: argparse.Namespace) -> None:
   with demo.client() as client:
      code = arguments.code

      if code is None:
         demo.tour.section(
            "Find a post",
            f"for item in client.feeds.iter_home(limit={FEED_SEARCH_LIMIT}): ...",
         )

         code = first_post_code(client)

         if code is None:
            line(f"no post in the first {FEED_SEARCH_LIMIT} feed items")
            return

         line(f"first post is {code}, and breaking out of the loop reads no page ahead")

      demo.tour.section("One post", f'post = client.media.by_code("{code}")')

      post = client.media.by_code(code)
      line(f"@{post.author.username}  {preview(post.caption)}")
      describe_media(post)
      demo.report["post_read"] = True

      show_comments(demo, client, post, arguments.limit)

      if arguments.download:
         download(demo, client, post, arguments.download)


if __name__ == "__main__":
   parser = build_parser("Read one post, its comments, and download a rendition.")
   parser.add_argument("--code", help="the post's shortcode, default the first post in the feed")
   parser.add_argument("--limit", type=int, default=5, help="comments the iterator walks")
   parser.add_argument("--download", metavar="DIR", type=Path, help="save the largest image here")

   sys.exit(run("post", parser, tour))
