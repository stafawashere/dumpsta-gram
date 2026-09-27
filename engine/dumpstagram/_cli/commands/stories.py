"""The stories commands: the tray, one account's live stories, and one highlight. None of them
marks anything seen."""

from __future__ import annotations

import argparse
import re
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
from dumpstagram._cli.commands.social import account_id
from dumpstagram._cli.exits import EXIT_OK
from dumpstagram._cli.render.stories import (
   describe_story_reel,
   describe_tray,
   render_story_reel,
   render_tray,
)

__all__ = [
   "STORIES_COMMANDS",
   "add_stories_parsers",
   "run_stories_command",
]

STORIES_COMMANDS = ("stories-tray", "story", "highlight")

_HIGHLIGHT_ID = re.compile(r"highlight:[0-9]+")


def highlight_id(value: str) -> str:
   is_a_highlight_id = _HIGHLIGHT_ID.fullmatch(value) is not None

   if not is_a_highlight_id:
      raise argparse.ArgumentTypeError(
         "a highlight is named by its id in the highlight:<number> form, "
         "which dumpsta highlights USER_ID prints"
      )

   return value


def _stories_result(client: Client, arguments: argparse.Namespace) -> tuple[dict[str, Any], str]:
   if arguments.command == "stories-tray":
      tray = client.stories.tray()

      return {"command": "stories-tray", **describe_tray(tray)}, render_tray(tray)

   if arguments.command == "story":
      reel = client.stories.reel(arguments.user_id)
      payload: dict[str, Any] = {
         "command": "story",
         "user_id": arguments.user_id,
         **describe_story_reel(reel),
      }

      return payload, render_story_reel(reel)

   highlight = client.stories.highlight(arguments.highlight_id)
   payload = {
      "command": "highlight",
      "highlight_id": arguments.highlight_id,
      **describe_story_reel(highlight),
   }

   return payload, render_story_reel(highlight)


def run_stories_command(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_read = client.session.fb_dtsg

   try:
      payload, text = _stories_result(client, arguments)

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_read
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   emit(payload, text, as_json=arguments.json, stream=stdout)

   return EXIT_OK


def add_stories_parsers(commands: Subcommands) -> None:
   tray = commands.add_parser(
      "stories-tray",
      help="list the accounts in the stories tray, one live request, nothing marked seen",
      description=(
         "Lists the accounts whose live stories the tray at the top of the home page shows, "
         "with when each last posted and how far you have seen it. It reads no items and marks "
         "nothing seen."
      ),
   )
   add_request_options(tray)

   story = commands.add_parser(
      "story",
      help="read one account's live stories, one live request, nothing marked seen",
      description=(
         "Reads every item in the live stories of the account whose numeric id is USER_ID. "
         "It does not mark them seen, so the account does not see you in its viewers."
      ),
   )
   story.add_argument(
      "user_id", metavar="USER_ID", type=account_id, help="the account's numeric id"
   )
   add_request_options(story)

   highlight = commands.add_parser(
      "highlight",
      help="read one highlight, one live request, nothing marked seen",
      description=(
         "Reads every item in the highlight HIGHLIGHT_ID, in the highlight:<number> form "
         "dumpsta highlights prints."
      ),
   )
   highlight.add_argument(
      "highlight_id",
      metavar="HIGHLIGHT_ID",
      type=highlight_id,
      help="the highlight's id, highlight:<number>",
   )
   add_request_options(highlight)
