"""The viewer's own account commands: the pending follow requests, the activity feed, the saved
posts and collections, and the close friends list. None marks anything seen or changes
anything."""

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
   resolve_session_path,
)
from dumpstagram._cli.exits import EXIT_OK
from dumpstagram._cli.render.account import (
   describe_activity_feed,
   describe_close_friends,
   describe_follow_requests,
   describe_saved_collections,
   describe_saved_posts,
   render_activity_feed,
   render_close_friends,
   render_follow_requests,
   render_saved_collections,
   render_saved_posts,
)

__all__ = [
   "ACCOUNT_COMMANDS",
   "add_account_parsers",
   "run_account_command",
]

ACCOUNT_COMMANDS = ("follow-requests", "activity", "saved", "collections", "close-friends")


def _account_result(client: Client, arguments: argparse.Namespace) -> tuple[dict[str, Any], str]:
   if arguments.command == "follow-requests":
      requests = client.account.follow_requests()
      payload = {"command": "follow-requests", **describe_follow_requests(requests)}

      return payload, render_follow_requests(requests)

   if arguments.command == "saved":
      saved = client.account.saved()

      return {"command": "saved", **describe_saved_posts(saved)}, render_saved_posts(saved)

   if arguments.command == "collections":
      collections = client.account.collections()
      payload = {"command": "collections", **describe_saved_collections(collections)}

      return payload, render_saved_collections(collections)

   if arguments.command == "close-friends":
      accounts = client.account.close_friends()
      payload = {"command": "close-friends", **describe_close_friends(accounts)}

      return payload, render_close_friends(accounts)

   feed = client.account.activity()

   return {"command": "activity", **describe_activity_feed(feed)}, render_activity_feed(feed)


def run_account_command(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_read = client.session.fb_dtsg

   try:
      payload, text = _account_result(client, arguments)

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_read
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   emit(payload, text, as_json=arguments.json, stream=stdout)

   return EXIT_OK


def add_account_parsers(commands: Subcommands) -> None:
   follow_requests = commands.add_parser(
      "follow-requests",
      help="list the accounts asking to follow you, one live request",
      description=(
         "Lists the accounts waiting for you to accept their follow request, the first page "
         "of them, and says whether more exist. Only a private account receives requests."
      ),
   )
   add_request_options(follow_requests)

   activity = commands.add_parser(
      "activity",
      help="read your activity feed, one live request, nothing marked seen",
      description=(
         "Reads the likes, follows, comments and requests your notifications page lists, "
         "in the upstream's order. It does not mark them seen, so your notifications badge "
         "is left as it was."
      ),
   )
   add_request_options(activity)

   saved = commands.add_parser(
      "saved",
      help="list the posts you saved, one live request",
      description=(
         "Lists the first page of your saved posts, the All posts view, in the upstream's "
         "order, and says whether more exist. A saved post carries no comment count."
      ),
   )
   add_request_options(saved)

   collections = commands.add_parser(
      "collections",
      help="list your saved collections, one live request",
      description=(
         "Lists the collections your saved tab shows, the All posts and Audio collections "
         "among them, with how many posts each holds where the upstream says."
      ),
   )
   add_request_options(collections)

   close_friends = commands.add_parser(
      "close-friends",
      help="list your close friends, one live request, nothing changed",
      description=(
         "Lists the accounts on your close friends list, in the order its settings screen "
         "shows them. Nothing is added, removed or recounted."
      ),
   )
   add_request_options(close_friends)
