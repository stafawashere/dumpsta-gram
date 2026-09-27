"""The profile command, by username or by numeric account id, and the profile tab commands: the
posts grid, the highlights tray, the followers, and the suggested accounts."""

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
from dumpstagram._cli.commands.social import account_id
from dumpstagram._cli.exits import EXIT_OK
from dumpstagram._cli.render.profiles import (
   describe_follower_pages,
   describe_grid_pages,
   describe_highlight_tray,
   describe_profile,
   describe_profile_summary,
   describe_suggested_account,
   render_followers,
   render_grid,
   render_highlight_tray,
   render_profile,
   render_profile_summaries,
   render_suggested_accounts,
)
from dumpstagram.models import Page, Post, ProfileSummary

__all__ = [
   "PROFILE_TAB_COMMANDS",
   "add_profile_parser",
   "add_profile_tab_parsers",
   "read_follower_pages",
   "read_grid_pages",
   "run_profile",
   "run_profile_tab_command",
]

PROFILE_TAB_COMMANDS = ("posts", "highlights", "followers", "suggested", "suggested-for-you")


def run_profile(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_read = client.session.fb_dtsg

   try:
      if arguments.by_id:
         profile = client.profile_by_id(arguments.who)
      else:
         profile = client.profile(arguments.who)

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_read
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   payload = {
      "command": "profile",
      "requests_spent": 1 if arguments.by_id else 2,
      "profile": describe_profile(profile),
   }

   emit(payload, render_profile(profile), as_json=arguments.json, stream=stdout)

   return EXIT_OK


def add_profile_parser(commands: Subcommands) -> None:
   profile = commands.add_parser(
      "profile",
      help="read one account's profile, a page load by username and one request by id",
      description=(
         "By username the profile page is loaded and its six queries sent together, seven "
         "live requests in one action, as a browser does. --by-id spends one live request."
      ),
   )
   profile.add_argument(
      "who",
      metavar="USERNAME",
      help="the username to read, or the numeric account id when --by-id is passed",
   )
   profile.add_argument(
      "--by-id",
      action="store_true",
      help="treat the argument as a numeric account id and read the profile query alone",
   )
   profile.add_argument(
      "--user-agent",
      metavar="STRING",
      help="override the user agent every request claims to be",
   )
   profile.add_argument(
      "--no-session-writeback",
      action="store_true",
      help="do not save tokens harvested during this run back to the session file",
   )


def read_grid_pages(client: Client, arguments: argparse.Namespace) -> list[Page[Post]]:
   """Read up to ``--pages`` grid pages, stopping on the page's own terminator."""

   pages: list[Page[Post]] = []
   cursor = arguments.after

   for _ in range(arguments.pages):
      page = client.profiles.posts(arguments.username, after=cursor)
      pages.append(page)

      if not page.has_next_page:
         break

      cursor = page.end_cursor

   return pages


def read_follower_pages(
   client: Client, arguments: argparse.Namespace
) -> list[Page[ProfileSummary]]:
   """Read up to ``--pages`` followers pages, stopping on the page's own ``has_more``."""

   pages: list[Page[ProfileSummary]] = []
   next_max_id = arguments.after

   while len(pages) < arguments.pages:
      page = client.profiles.followers(arguments.user_id, after=next_max_id)
      pages.append(page)
      reached_the_last_page = not page.has_next_page

      if reached_the_last_page:
         break

      next_max_id = page.end_cursor

   return pages


def _profile_tab_result(
   client: Client, arguments: argparse.Namespace
) -> tuple[dict[str, Any], str]:
   if arguments.command == "posts":
      pages = read_grid_pages(client, arguments)
      payload: dict[str, Any] = {"command": "posts", **describe_grid_pages(pages)}

      return payload, render_grid(pages)

   if arguments.command == "highlights":
      tray = client.profiles.highlights(arguments.user_id)
      payload = {"command": "highlights", **describe_highlight_tray(tray)}

      return payload, render_highlight_tray(tray)

   if arguments.command == "followers":
      follower_pages = read_follower_pages(client, arguments)
      payload = {"command": "followers", **describe_follower_pages(follower_pages)}

      return payload, render_followers(follower_pages)

   if arguments.command == "suggested":
      accounts = client.profiles.suggested(arguments.user_id)
      payload = {
         "command": "suggested",
         "accounts": [describe_profile_summary(account) for account in accounts],
      }

      return payload, render_profile_summaries(accounts)

   suggestions = client.profiles.suggested_for_you()
   payload = {
      "command": "suggested-for-you",
      "accounts": [describe_suggested_account(suggestion) for suggestion in suggestions],
   }

   return payload, render_suggested_accounts(suggestions)


def run_profile_tab_command(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_read = client.session.fb_dtsg

   try:
      payload, text = _profile_tab_result(client, arguments)

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_read
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   emit(payload, text, as_json=arguments.json, stream=stdout)

   return EXIT_OK


def add_profile_tab_parsers(commands: Subcommands) -> None:
   posts = commands.add_parser(
      "posts",
      help="read an account's posts grid, twelve posts a page, one live request per page",
      description=(
         "Reads the grid a profile shows, newest first with pinned posts at the top. --after "
         "takes a next_cursor this command printed for the same account."
      ),
   )
   posts.add_argument("username", metavar="USERNAME", help="the account's username")
   posts.add_argument(
      "--pages",
      type=page_count,
      default=1,
      metavar="N",
      help="how many pages to read at most, default 1",
   )
   posts.add_argument("--after", metavar="CURSOR", help="a next_cursor from an earlier posts run")
   add_request_options(posts)

   highlights = commands.add_parser(
      "highlights",
      help="list an account's story highlights, the tray's first page, one live request",
      description=(
         "Lists each highlight's id and title. Only the tray's first page can be read, and "
         "more_available says when there is more. No story is opened or marked seen."
      ),
   )
   highlights.add_argument(
      "user_id", metavar="USER_ID", type=account_id, help="the account's numeric id"
   )
   add_request_options(highlights)

   followers = commands.add_parser(
      "followers",
      help="list an account's followers with your relationship to each, two live requests a page",
      description=(
         "Reads the list a profile's follower count opens, in the upstream's order, and asks "
         "for your relationship to the accounts on each page, as the website does. --after "
         "takes a next_cursor this command printed for the same account."
      ),
   )
   followers.add_argument(
      "user_id", metavar="USER_ID", type=account_id, help="the account's numeric id"
   )
   followers.add_argument(
      "--pages",
      type=page_count,
      default=1,
      metavar="N",
      help="how many pages to read at most, default 1",
   )
   followers.add_argument(
      "--after", metavar="CURSOR", help="a next_cursor from an earlier followers run"
   )
   add_request_options(followers)

   suggested = commands.add_parser(
      "suggested",
      help="list the accounts suggested beside an account's profile, one live request",
   )
   suggested.add_argument(
      "user_id", metavar="USER_ID", type=account_id, help="the account's numeric id"
   )
   add_request_options(suggested)

   for_you = commands.add_parser(
      "suggested-for-you",
      help="list the accounts suggested to you, with the reason shown for each, one live request",
   )
   add_request_options(for_you)
