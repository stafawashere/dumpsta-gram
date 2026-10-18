"""Like a post, read the like back, and take it away again. Writes.

Live requests: 4, two reads and two writes. The writes wait out the write spacing, about 35 s
under parity. A post the account already liked is left alone.

   uv run python docs/demo/like_cycle.py CODE
"""

from __future__ import annotations

import argparse
import sys

from _common import Demo, build_parser, line, run


def tour(demo: Demo, arguments: argparse.Namespace) -> None:
   code = arguments.code

   demo.tour.section(
      "Like cycle",
      f'post = client.media.by_code("{code}")',
      "client.media.like(post.pk)",
      "client.media.unlike(post.pk)",
   )

   with demo.client() as client:
      post = client.media.by_code(code)

      if post.has_liked:
         line("already liked, so the cycle stops rather than take the like back")
         return

      client.media.like(post.pk)
      liked = client.media.by_code(code).has_liked
      line(f"liked, and the read back says has_liked={liked}")

      client.media.unlike(post.pk)
      line("unliked")
      demo.report["like_cycle"] = True


if __name__ == "__main__":
   parser = build_parser("Like a post, then unlike it.")
   parser.add_argument("code", help="the post's shortcode")

   sys.exit(run("like-cycle", parser, tour))
