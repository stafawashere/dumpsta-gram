"""Comment on a post, then delete the comment. Writes.

Live requests: 3, one read and two writes, the second after the write spacing. The text comes
from `IG_COMMENT_TEXT` in `.env`.

   uv run python docs/demo/comment_cycle.py CODE
"""

from __future__ import annotations

import argparse
import sys

from _common import Demo, build_parser, line, preview, run


def tour(demo: Demo, arguments: argparse.Namespace) -> None:
   code = arguments.code
   text = demo.write_text("IG_COMMENT_TEXT")

   demo.tour.section(
      "Comment cycle",
      f'post = client.media.by_code("{code}")',
      f"comment = client.media.comment(post.pk, {preview(text)})",
      "client.media.delete_comment(post.pk, comment.id)",
   )

   with demo.client() as client:
      post = client.media.by_code(code)

      comment = client.media.comment(post.pk, text)
      line(f"Comment {comment.id} by @{comment.author.username} at {comment.created_at:%H:%M:%S}")

      client.media.delete_comment(post.pk, comment.id)
      line("deleted")
      demo.report["comment_cycle"] = True


if __name__ == "__main__":
   parser = build_parser("Comment on a post, then delete the comment.")
   parser.add_argument("code", help="the post's shortcode")

   sys.exit(run("comment-cycle", parser, tour))
