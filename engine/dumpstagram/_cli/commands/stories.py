"""The stories commands: the tray, one account's live stories, one highlight, and marking one
item seen. The tray marks nothing. `story` and `highlight` mark the first item seen, as opening
it on the website does, unless `--no-mark-seen` is given, and `story-seen` marks the item it is
told to (W95)."""

from __future__ import annotations

import argparse
import re
from collections.abc import Mapping
from dataclasses import replace
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
from dumpstagram.errors import NotFound
from dumpstagram.models import StoryReel

__all__ = [
   "STORIES_COMMANDS",
   "add_stories_parsers",
   "run_stories_command",
]

STORIES_COMMANDS = ("stories-tray", "story", "highlight", "story-seen")

_HIGHLIGHT_ID = re.compile(r"highlight:[0-9]+")


def highlight_id(value: str) -> str:
   is_a_highlight_id = _HIGHLIGHT_ID.fullmatch(value) is not None

   if not is_a_highlight_id:
      raise argparse.ArgumentTypeError(
         "a highlight is named by its id in the highlight:<number> form, "
         "which dumpsta highlights USER_ID prints"
      )

   return value


def reel_id(value: str) -> str:
   is_an_account_id = value.isascii() and value.isdigit()
   is_a_highlight_id = _HIGHLIGHT_ID.fullmatch(value) is not None
   is_a_reel_id = is_an_account_id or is_a_highlight_id

   if not is_a_reel_id:
      raise argparse.ArgumentTypeError(
         "a reel is an account's numeric id for its live stories, or a highlight's id in the "
         "highlight:<number> form"
      )

   return value


def media_pk(value: str) -> str:
   is_all_digits = value.isascii() and value.isdigit()

   if not is_all_digits:
      raise argparse.ArgumentTypeError(
         "a story item is named by its pk, digits only, which dumpsta story --json prints"
      )

   return value


def _without_marking(client: Client) -> Client:
   return client.with_behavior(replace(client.behavior, mark_stories_seen=False))


def _read_reel(client: Client, reel: str) -> StoryReel | None:
   is_a_highlight = _HIGHLIGHT_ID.fullmatch(reel) is not None

   if is_a_highlight:
      return client.stories.highlight(reel)

   return client.stories.reel(reel)


def _mark_one_item_seen(client: Client, arguments: argparse.Namespace) -> dict[str, Any]:
   """Read the reel with marking off, so the read marks no item of its own, then mark the item
   asked for. Two live requests."""

   reader = _without_marking(client)

   try:
      reel = _read_reel(reader, arguments.reel_id)
   finally:
      reader.close()

   if reel is None:
      raise NotFound(f"the account {arguments.reel_id} has no live story")

   matching = [item for item in reel.items if item.pk == arguments.item_pk]

   if not matching:
      raise NotFound(f"no item {arguments.item_pk} in the reel {reel.id}")

   client.stories.mark_seen(matching[0], reel=reel)

   return {
      "command": "story-seen",
      "reel_id": reel.id,
      "item_pk": arguments.item_pk,
      "marked_seen": True,
   }


def _stories_result(client: Client, arguments: argparse.Namespace) -> tuple[dict[str, Any], str]:
   if arguments.command == "story-seen":
      payload = _mark_one_item_seen(client, arguments)

      return payload, f"marked seen: {payload['item_pk']} in {payload['reel_id']}"

   if arguments.command == "stories-tray":
      tray = client.stories.tray()

      return {"command": "stories-tray", **describe_tray(tray)}, render_tray(tray)

   reader = _without_marking(client) if arguments.no_mark_seen else client

   try:
      return _reel_result(reader, arguments)
   finally:
      if reader is not client:
         reader.close()


def _reel_result(client: Client, arguments: argparse.Namespace) -> tuple[dict[str, Any], str]:
   marks_first_item = client.behavior.mark_stories_seen

   if arguments.command == "story":
      reel = client.stories.reel(arguments.user_id)
      has_items = reel is not None and len(reel.items) > 0
      payload: dict[str, Any] = {
         "command": "story",
         "user_id": arguments.user_id,
         "marked_first_item_seen": marks_first_item and has_items,
         **describe_story_reel(reel),
      }

      return payload, render_story_reel(reel)

   highlight = client.stories.highlight(arguments.highlight_id)
   has_items = len(highlight.items) > 0
   payload = {
      "command": "highlight",
      "highlight_id": arguments.highlight_id,
      "marked_first_item_seen": marks_first_item and has_items,
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
      help=(
         "read one account's live stories and mark the first item seen, which the account "
         "sees, one live request and one write"
      ),
      description=(
         "Reads every item in the live stories of the account whose numeric id is USER_ID, "
         "and marks the first item seen, as opening the story on the website does, so the "
         "account sees you among that item's viewers. --no-mark-seen reads without marking."
      ),
   )
   story.add_argument(
      "user_id", metavar="USER_ID", type=account_id, help="the account's numeric id"
   )
   _add_mark_seen_option(story)
   add_request_options(story)

   highlight = commands.add_parser(
      "highlight",
      help=(
         "read one highlight and mark the first item seen, which its owner sees, one live "
         "request and one write"
      ),
      description=(
         "Reads every item in the highlight HIGHLIGHT_ID, in the highlight:<number> form "
         "dumpsta highlights prints, and marks the first item seen, as opening it on the "
         "website does. --no-mark-seen reads without marking."
      ),
   )
   highlight.add_argument(
      "highlight_id",
      metavar="HIGHLIGHT_ID",
      type=highlight_id,
      help="the highlight's id, highlight:<number>",
   )
   _add_mark_seen_option(highlight)
   add_request_options(highlight)

   story_seen = commands.add_parser(
      "story-seen",
      help="mark one story item seen, which its owner sees, one live request and one write",
      description=(
         "Reads the reel REEL_ID without marking anything, then marks its item ITEM_PK seen, "
         "so the item's owner sees you among its viewers. REEL_ID is an account's numeric id "
         "for its live stories or a highlight's id, highlight:<number>."
      ),
   )
   story_seen.add_argument(
      "reel_id",
      metavar="REEL_ID",
      type=reel_id,
      help="an account's numeric id, or a highlight's id, highlight:<number>",
   )
   story_seen.add_argument(
      "item_pk", metavar="ITEM_PK", type=media_pk, help="the item's pk, digits only"
   )
   add_request_options(story_seen)


def _add_mark_seen_option(command: argparse.ArgumentParser) -> None:
   command.add_argument(
      "--no-mark-seen",
      action="store_true",
      help="read without marking the first item seen, so no one sees you in its viewers",
   )
