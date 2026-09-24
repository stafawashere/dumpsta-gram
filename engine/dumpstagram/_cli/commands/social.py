"""The follow and unfollow commands, keyed on the numeric account id."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import TextIO

from dumpstagram._cli.commands.common import (
   ClientFactory,
   Subcommands,
   add_request_options,
   emit,
   resolve_session_path,
)
from dumpstagram._cli.exits import EXIT_OK

__all__ = [
   "account_id",
   "add_follow_parsers",
   "run_follow_write",
]


def account_id(value: str) -> str:
   is_all_digits = value.isascii() and value.isdigit()

   if not is_all_digits:
      raise argparse.ArgumentTypeError(
         "an account is named by its numeric id, digits only, not by its username. "
         "dumpsta profile USERNAME prints the id"
      )

   return value


def run_follow_write(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_write = client.session.fb_dtsg
   is_follow = arguments.command == "follow"

   try:
      if is_follow:
         client.follow(arguments.user_id)
      else:
         client.unfollow(arguments.user_id)

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_write
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   payload = {"command": arguments.command, "user_id": arguments.user_id}

   emit(
      payload,
      f"{arguments.command} sent for {arguments.user_id}. "
      f"dumpsta profile --by-id {arguments.user_id} shows the relationship",
      as_json=arguments.json,
      stream=stdout,
   )

   return EXIT_OK


def add_follow_parsers(commands: Subcommands) -> None:
   for verb, effect in (("follow", "follow"), ("unfollow", "unfollow")):
      write = commands.add_parser(
         verb,
         help=f"{effect} one account, one write, sent once and never retried",
         description=(
            f"Writes to the account: {effect} the account whose numeric id is USER_ID, which "
            "is notified of a follow. There is no prompt and no default target. A follow of a "
            "private account becomes a follow request. Read dumpsta profile --by-id USER_ID "
            "for the relationship, and before sending again if the outcome is unknown."
         ),
      )
      write.add_argument(
         "user_id", metavar="USER_ID", type=account_id, help="the account's numeric id"
      )
      add_request_options(write)
