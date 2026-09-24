"""The profile command, by username or by numeric account id."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import TextIO

from dumpstagram._cli.commands.common import ClientFactory, Subcommands, emit, resolve_session_path
from dumpstagram._cli.exits import EXIT_OK
from dumpstagram._cli.render.profiles import describe_profile, render_profile

__all__ = [
   "add_profile_parser",
   "run_profile",
]


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
