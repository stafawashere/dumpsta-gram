"""The post depth commands: the replies under a comment, a post's likers, and the more posts from
its author."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import Any, TextIO

from dumpstagram._cli.commands.common import (
   Client,
   ClientFactory,
   Subcommands,
   add_request_options,
   emit,
   page_count,
   resolve_session_path,
)
from dumpstagram._cli.commands.media import comment_id, media_pk
from dumpstagram._cli.commands.social import account_id
from dumpstagram._cli.exits import EXIT_OK
from dumpstagram._cli.render.post_depth import (
   describe_likers,
   describe_post_thumbnail,
   describe_reply_pages,
   render_likers,
   render_post_thumbnails,
   render_reply_pages,
)
from dumpstagram.models import Comment, Page

__all__ = [
   "POST_DEPTH_COMMANDS",
   "add_post_depth_parsers",
   "read_reply_pages",
   "run_post_depth_command",
]

POST_DEPTH_COMMANDS = ("replies", "likers", "more-from-author")


def read_reply_pages(client: Client, arguments: argparse.Namespace) -> list[Page[Comment]]:
   """Read up to ``--pages`` pages of replies, stopping on the page's own terminator."""

   pages: list[Page[Comment]] = []
   cursor = arguments.after

   while len(pages) < arguments.pages:
      page = client.media.replies(arguments.pk, arguments.comment_id, after=cursor)
      pages.append(page)
      reached_the_last_page = not page.has_next_page

      if reached_the_last_page:
         break

      cursor = page.end_cursor

   return pages


def _post_depth_result(client: Client, arguments: argparse.Namespace) -> tuple[dict[str, Any], str]:
   if arguments.command == "replies":
      pages = read_reply_pages(client, arguments)
      payload: dict[str, Any] = {
         "command": "replies",
         "pk": arguments.pk,
         "comment_id": arguments.comment_id,
         **describe_reply_pages(pages),
      }

      return payload, render_reply_pages(pages)

   if arguments.command == "likers":
      likers = client.media.likers(arguments.pk)
      payload = {"command": "likers", "pk": arguments.pk, **describe_likers(likers)}

      return payload, render_likers(likers)

   thumbnails = client.media.more_from_author(arguments.author_id)
   payload = {
      "command": "more-from-author",
      "author_id": arguments.author_id,
      "post_count": len(thumbnails),
      "posts": [describe_post_thumbnail(thumbnail) for thumbnail in thumbnails],
   }

   return payload, render_post_thumbnails(thumbnails)


def run_post_depth_command(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_read = client.session.fb_dtsg

   try:
      payload, text = _post_depth_result(client, arguments)

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_read
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   emit(payload, text, as_json=arguments.json, stream=stdout)

   return EXIT_OK


def add_post_depth_parsers(commands: Subcommands) -> None:
   replies = commands.add_parser(
      "replies",
      help="read the replies under one comment, oldest first, one live request per page",
      description=(
         "Reads the replies under the comment COMMENT_ID on the post whose pk is PK, as "
         '"view replies" opens them. --after takes a next_cursor this command printed for the '
         "same comment."
      ),
   )
   replies.add_argument("pk", metavar="PK", type=media_pk, help="the post's pk, digits only")
   replies.add_argument(
      "comment_id", metavar="COMMENT_ID", type=comment_id, help="the comment's id, digits only"
   )
   replies.add_argument(
      "--pages",
      type=page_count,
      default=1,
      metavar="N",
      help="how many pages to read at most, default 1",
   )
   replies.add_argument(
      "--after", metavar="CURSOR", help="a next_cursor from an earlier replies run"
   )
   add_request_options(replies)

   likers = commands.add_parser(
      "likers",
      help="list the accounts shown as liking one post, one live request",
      description=(
         "Lists the accounts the likes dialog shows for the post whose pk is PK, with your "
         "relationship to each. On a popular post this is a sample, not every like."
      ),
   )
   likers.add_argument("pk", metavar="PK", type=media_pk, help="the post's pk, digits only")
   add_request_options(likers)

   more = commands.add_parser(
      "more-from-author",
      help="list the posts shown under a post as more from its author, one live request",
      description=(
         "Lists the strip of posts a post page shows from its author, keyed on the author's "
         "numeric id, which dumpsta --json post prints as author.id."
      ),
   )
   more.add_argument(
      "author_id", metavar="AUTHOR_ID", type=account_id, help="the author's numeric id"
   )
   add_request_options(more)
