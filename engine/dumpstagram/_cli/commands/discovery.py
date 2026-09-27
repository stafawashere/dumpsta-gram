"""The discovery commands: pages of the explore grid, a place's header and posts, whether the
home feed has new posts, pages of the reels feed, and pages of an audio's page."""

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
   page_count,
   resolve_session_path,
)
from dumpstagram._cli.exits import EXIT_OK
from dumpstagram._cli.render.discovery import (
   describe_audio_pages,
   describe_explore_pages,
   describe_location_posts,
   describe_place,
   describe_reels_pages,
   render_audio_pages,
   render_explore_pages,
   render_location_posts,
   render_new_posts,
   render_place,
   render_reels_pages,
)
from dumpstagram.models import AudioPage, ExploreGrid, Page, Post

__all__ = [
   "DISCOVERY_COMMANDS",
   "add_discovery_parsers",
   "run_discovery_command",
]

DISCOVERY_COMMANDS = ("explore", "place", "location", "new-posts", "reels", "audio")

_LOCATION_ID = re.compile(r"[0-9]{1,30}")

_AUDIO_ID = re.compile(r"[0-9]{1,30}")


def audio_id(value: str) -> str:
   is_an_audio_id = _AUDIO_ID.fullmatch(value) is not None

   if not is_an_audio_id:
      raise argparse.ArgumentTypeError(
         "an audio is named by its numeric id, the audio_id a reel that uses it carries"
      )

   return value


def location_id(value: str) -> str:
   is_a_location_id = _LOCATION_ID.fullmatch(value) is not None

   if not is_a_location_id:
      raise argparse.ArgumentTypeError(
         "a place is named by its numeric id, the location id a post tagged there carries"
      )

   return value


def read_reels_pages(client: Client, arguments: argparse.Namespace) -> list[Page[Post]]:
   """Read up to ``--pages`` pages of the reels feed, stopping on the page's own terminator."""

   pages: list[Page[Post]] = []
   cursor = arguments.after

   for _ in range(arguments.pages):
      page = client.feeds.reels(after=cursor)

      pages.append(page)

      if not page.has_next_page:
         break

      cursor = page.end_cursor

   return pages


def read_explore_pages(client: Client, arguments: argparse.Namespace) -> list[ExploreGrid]:
   """Read up to ``--pages`` pages of the explore grid, stopping on the page's own
   ``more_available``. The first page is asked for with no cursor unless ``--after`` gives one."""

   grids: list[ExploreGrid] = []
   cursor = arguments.after

   for _ in range(arguments.pages):
      grid = client.feeds.explore() if cursor is None else client.feeds.explore(after=cursor)

      grids.append(grid)

      if not grid.more_available:
         break

      cursor = grid.end_cursor

   return grids


def read_audio_pages(client: Client, arguments: argparse.Namespace) -> list[AudioPage]:
   """Read up to ``--pages`` pages of the audio's page, stopping on the page's own
   ``more_available``."""

   pages: list[AudioPage] = []
   cursor = arguments.after

   for _ in range(arguments.pages):
      audio_page = client.feeds.audio(arguments.audio_id, after=cursor)

      pages.append(audio_page)

      if not audio_page.more_available:
         break

      cursor = audio_page.end_cursor

   return pages


def _discovery_result(client: Client, arguments: argparse.Namespace) -> tuple[dict[str, Any], str]:
   if arguments.command == "reels":
      pages = read_reels_pages(client, arguments)

      return {"command": "reels", **describe_reels_pages(pages)}, render_reels_pages(pages)

   if arguments.command == "explore":
      grids = read_explore_pages(client, arguments)

      return {"command": "explore", **describe_explore_pages(grids)}, render_explore_pages(grids)

   if arguments.command == "audio":
      audio_pages = read_audio_pages(client, arguments)
      payload_for_audio = {
         "command": "audio",
         **describe_audio_pages(arguments.audio_id, audio_pages),
      }

      return payload_for_audio, render_audio_pages(audio_pages)

   if arguments.command == "place":
      place = client.feeds.place(arguments.location_id)

      return {"command": "place", "place": describe_place(place)}, render_place(place)

   if arguments.command == "location":
      page = client.feeds.location(arguments.location_id)
      payload: dict[str, Any] = {
         "command": "location",
         "location_id": arguments.location_id,
         **describe_location_posts(page),
      }

      return payload, render_location_posts(page)

   has_new_posts = client.feeds.has_new_posts()

   return {"command": "new-posts", "new_posts": has_new_posts}, render_new_posts(has_new_posts)


def run_discovery_command(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_read = client.session.fb_dtsg

   try:
      payload, text = _discovery_result(client, arguments)

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_read
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   emit(payload, text, as_json=arguments.json, stream=stdout)

   return EXIT_OK


def add_discovery_parsers(commands: Subcommands) -> None:
   explore = commands.add_parser(
      "explore",
      help="read pages of the explore grid, one live request per page",
      description=(
         "Reads the explore grid as the /explore/ page scrolls it, section by section, stopping "
         "on the grid's own more_available."
      ),
   )
   explore.add_argument(
      "--pages",
      type=page_count,
      default=1,
      metavar="N",
      help="how many pages to read at most, default 1",
   )
   explore.add_argument("--after", metavar="CURSOR", help="an end_cursor from an earlier page")
   add_request_options(explore)

   place = commands.add_parser(
      "place",
      help="read a place's name, address and post count, one live request",
      description="Reads the header of the page of the place whose numeric id is LOCATION_ID.",
   )
   place.add_argument(
      "location_id", metavar="LOCATION_ID", type=location_id, help="the place's numeric id"
   )
   add_request_options(place)

   location = commands.add_parser(
      "location",
      help="read the first page of the posts tagged at a place, one live request",
      description=(
         "Reads the first page of the ranked grid of the place whose numeric id is "
         "LOCATION_ID, and says whether the grid goes on. No later page is read."
      ),
   )
   location.add_argument(
      "location_id", metavar="LOCATION_ID", type=location_id, help="the place's numeric id"
   )
   add_request_options(location)

   new_posts = commands.add_parser(
      "new-posts",
      help="ask whether the home feed has new posts, one live request",
      description="Asks whether the home feed has posts newer than you last loaded.",
   )
   add_request_options(new_posts)

   reels = commands.add_parser(
      "reels",
      help="read pages of the reels feed, one live request per page",
      description=(
         "Reads the reels feed as the /reels/ tab pages it, stopping on the feed's own "
         "terminator. Nothing is played, so no view is reported."
      ),
   )
   reels.add_argument(
      "--pages",
      type=page_count,
      default=1,
      metavar="N",
      help="how many pages to read at most, default 1",
   )
   reels.add_argument("--after", metavar="CURSOR", help="an end_cursor from an earlier page")
   add_request_options(reels)

   audio = commands.add_parser(
      "audio",
      help="read pages of an audio's page, the track and the reels using it, one live request "
      "per page",
      description=(
         "Reads the /reels/audio/AUDIO_ID/ page's track and reels as the page scrolls them, "
         "stopping on the page's own more_available, which can say true before a page with no "
         "reels. Nothing is played."
      ),
   )
   audio.add_argument("audio_id", metavar="AUDIO_ID", type=audio_id, help="the audio's numeric id")
   audio.add_argument(
      "--pages",
      type=page_count,
      default=1,
      metavar="N",
      help="how many pages to read at most, default 1",
   )
   audio.add_argument("--after", metavar="CURSOR", help="an end_cursor from an earlier page")
   add_request_options(audio)
