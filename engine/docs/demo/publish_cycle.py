"""Publish a photo or a carousel, read it back, and delete it. Writes, and public while up.

Live requests: one upload per image, the publish, the read back and the delete. One JPEG is a
photo, 4 requests. Two or more are a carousel, one upload each plus 3. Every write waits out the
write spacing, so a photo takes about two minutes under parity. The post is visible to anyone
who can see the account until the delete applies.

   uv run python docs/demo/publish_cycle.py photo.jpg --caption "test"
   uv run python docs/demo/publish_cycle.py one.jpg two.jpg
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _common import Demo, build_parser, line, run


def jpeg_file(value: str) -> Path:
   path = Path(value)

   if not path.is_file():
      raise argparse.ArgumentTypeError(f"no file at {value}")

   return path


def tour(demo: Demo, arguments: argparse.Namespace) -> None:
   images: list[Path] = arguments.images
   is_carousel = len(images) > 1

   if is_carousel:
      publish_call = f"client.media.publish_carousel([...{len(images)} paths], caption=...)"
   else:
      publish_call = f'client.media.publish_photo("{images[0]}", caption=...)'

   demo.tour.section(
      "Publish cycle",
      f"published = {publish_call}",
      "client.media.by_code(published.code)",
      "client.media.delete_post(published.pk, published.code)",
   )

   with demo.client() as client:
      if is_carousel:
         published = client.media.publish_carousel(images, caption=arguments.caption)
      else:
         published = client.media.publish_photo(images[0], caption=arguments.caption)

      uploads = len(published.upload_ids)
      line(f"PublishedPost {published.code}, pk {published.pk}, {uploads} uploads")

      read_back = client.media.by_code(published.code)
      slides = len(read_back.carousel_children)
      line(f"read back: media type {read_back.media_type}, {slides} slides")

      client.media.delete_post(published.pk, published.code)
      line("deleted")
      demo.report["publish_cycle"] = True
      demo.report["images"] = len(images)


if __name__ == "__main__":
   parser = build_parser("Publish a post, read it back, then delete it.")
   parser.add_argument("images", nargs="+", type=jpeg_file, metavar="JPEG", help="JPEG files")
   parser.add_argument("--caption", default="", help="the post's caption")

   sys.exit(run("publish-cycle", parser, tour))
