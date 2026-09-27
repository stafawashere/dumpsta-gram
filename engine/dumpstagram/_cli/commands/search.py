"""The search commands: the recent searches, the accounts a query matches, what the search box
offers for a query, a hashtag's header, and the keyword grid."""

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
from dumpstagram._cli.exits import EXIT_OK
from dumpstagram._cli.render.search import (
   describe_hashtag,
   describe_keyword_results,
   describe_recent_searches,
   describe_search_accounts,
   describe_search_results,
   render_hashtag,
   render_keyword_results,
   render_recent_searches,
   render_search_accounts,
   render_search_results,
)
from dumpstagram.behavior import TypeaheadRoute

__all__ = [
   "SEARCH_COMMANDS",
   "add_search_parsers",
   "run_search_command",
]

SEARCH_COMMANDS = ("recent-searches", "search", "search-top", "hashtag", "keyword")

_TAG = re.compile(r"\w+")


def search_query(value: str) -> str:
   has_text = bool(value.strip())

   if not has_text:
      raise argparse.ArgumentTypeError("a search needs query text")

   return value


def hashtag_name(value: str) -> str:
   is_a_tag = _TAG.fullmatch(value) is not None

   if not is_a_tag:
      raise argparse.ArgumentTypeError(
         "a hashtag is named without its '#', in letters, digits and underscores"
      )

   return value


def _on_the_chosen_route(client: Client, arguments: argparse.Namespace) -> Client:
   """``client``, or a twin of it sending the non-personalised typeahead when asked (W102)."""

   if not arguments.non_personalised:
      return client

   route = TypeaheadRoute.NON_PERSONALISED

   return client.with_behavior(replace(client.behavior, typeahead_route=route))


def _search_result(client: Client, arguments: argparse.Namespace) -> tuple[dict[str, Any], str]:
   if arguments.command == "recent-searches":
      entries = client.search.recent()
      payload = {"command": "recent-searches", **describe_recent_searches(entries)}

      return payload, render_recent_searches(entries)

   if arguments.command == "search":
      accounts = _on_the_chosen_route(client, arguments).search.accounts(arguments.query)
      payload = {
         "command": "search",
         "query": arguments.query,
         **describe_search_accounts(accounts),
      }

      return payload, render_search_accounts(accounts)

   if arguments.command == "search-top":
      results = _on_the_chosen_route(client, arguments).search.top(arguments.query)
      payload = {
         "command": "search-top",
         "query": arguments.query,
         **describe_search_results(results),
      }

      return payload, render_search_results(results)

   if arguments.command == "keyword":
      grid = client.search.keyword(arguments.query)
      payload = {"command": "keyword", "query": arguments.query, **describe_keyword_results(grid)}

      return payload, render_keyword_results(grid)

   hashtag = client.search.hashtag(arguments.tag)

   return {"command": "hashtag", "hashtag": describe_hashtag(hashtag)}, render_hashtag(hashtag)


def run_search_command(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_read = client.session.fb_dtsg

   try:
      payload, text = _search_result(client, arguments)

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_read
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   emit(payload, text, as_json=arguments.json, stream=stdout)

   return EXIT_OK


def add_route_option(command: argparse.ArgumentParser) -> None:
   command.add_argument(
      "--non-personalised",
      action="store_true",
      help="send the non-personalised typeahead, accounts only, ranked without your profile",
   )


def add_search_parsers(commands: Subcommands) -> None:
   recent = commands.add_parser(
      "recent-searches",
      help="read your recent searches, one live request",
      description="Reads the recent searches the search panel lists, accounts and keywords.",
   )
   add_request_options(recent)

   search = commands.add_parser(
      "search",
      help="read the accounts a query matches, one live request",
      description=(
         "Reads the accounts QUERY matches, as the search box ranks them. Keywords, hashtags "
         "and places are left out; search-top reads them. Nothing is added to your recent "
         "searches."
      ),
   )
   search.add_argument("query", metavar="QUERY", type=search_query, help="the text to search for")
   add_route_option(search)
   add_request_options(search)

   top = commands.add_parser(
      "search-top",
      help="read what the search box offers for a query, one live request",
      description=(
         "Reads the accounts and keyword suggestions the search box offers for QUERY, in the "
         "order it shows them. Nothing is added to your recent searches."
      ),
   )
   top.add_argument("query", metavar="QUERY", type=search_query, help="the text to search for")
   add_route_option(top)
   add_request_options(top)

   hashtag = commands.add_parser(
      "hashtag",
      help="read a hashtag's header, one live request",
      description="Reads the header of the page of the hashtag TAG, named without its '#'.",
   )
   hashtag.add_argument(
      "tag", metavar="TAG", type=hashtag_name, help="the hashtag's name, without its '#'"
   )
   add_request_options(hashtag)

   keyword = commands.add_parser(
      "keyword",
      help="read the first page of a keyword search's grid, one live request",
      description=(
         "Reads the first page of the grid of posts the keyword page shows for QUERY, and says "
         "whether it goes on. A hashtag's posts are the grid for '#TAG'."
      ),
   )
   keyword.add_argument("query", metavar="QUERY", type=search_query, help="the text to search for")
   add_request_options(keyword)
