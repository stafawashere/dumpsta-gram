"""The feed command, pages of the home timeline."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import TextIO

from dumpstagram._cli.commands.common import (
   Client,
   ClientFactory,
   Subcommands,
   emit,
   page_count,
   resolve_session_path,
)
from dumpstagram._cli.exits import EXIT_OK
from dumpstagram._cli.render.feed import describe_feed_item, describe_feed_pages, render_feed
from dumpstagram.models import (
   FeedItem,
   Page,
)

__all__ = [
   "add_feed_parser",
   "read_feed_pages",
   "run_feed",
]


def read_feed_pages(client: Client, arguments: argparse.Namespace) -> list[Page[FeedItem]]:
   """Read up to ``--pages`` pages, stopping on the page's own terminator.

   The loop never stops because a page looked short. Measured pages carried 14, 12 and 5
   items for the same request, so a length is not a signal here any more than it is anywhere
   else on this surface.
   """

   pages: list[Page[FeedItem]] = []
   cursor = arguments.after

   for _ in range(arguments.pages):
      page = client.feed(after=cursor)

      pages.append(page)

      if not page.has_next_page:
         break

      cursor = page.end_cursor

   return pages


def run_feed(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_read = client.session.fb_dtsg

   try:
      pages = read_feed_pages(client, arguments)

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_read
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   items = [item for page in pages for item in page.items]
   shown = [item for item in items if item.post is not None] if arguments.posts_only else items

   payload = {
      "command": "feed",
      **describe_feed_pages(pages),
      "posts_only": arguments.posts_only,
      "items": [describe_feed_item(item) for item in shown],
   }

   emit(
      payload,
      render_feed(pages, posts_only=arguments.posts_only),
      as_json=arguments.json,
      stream=stdout,
   )

   return EXIT_OK


def add_feed_parser(commands: Subcommands) -> None:
   feed = commands.add_parser(
      "feed",
      help="read pages of the home timeline, one live request per page",
      description=(
         "Most of a timeline is not posts. Every item is reported with its kind, and only "
         "the ones whose kind is media carry a post."
      ),
   )
   feed.add_argument(
      "--pages",
      type=page_count,
      default=1,
      metavar="N",
      help="how many pages to read at most, default 1",
   )
   feed.add_argument("--after", metavar="CURSOR", help="an end_cursor from an earlier page")
   feed.add_argument(
      "--posts-only",
      action="store_true",
      help="print only the items that carry a post, and report how many were dropped",
   )
   feed.add_argument(
      "--user-agent",
      metavar="STRING",
      help="override the user agent every request claims to be",
   )
   feed.add_argument(
      "--no-session-writeback",
      action="store_true",
      help="do not save tokens harvested during this run back to the session file",
   )
