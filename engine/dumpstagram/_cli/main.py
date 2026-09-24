"""The `dumpsta` command, which is the engine's first consumer and its acceptance harness.

ADR-0005 makes this a real consumer rather than a demo. Every capability it reaches, it
reaches through `SyncClient`, so anything awkward to do from this package is a gap in the public
surface rather than something to reach past it for. The one internal import is the library's
own redaction helper, which stderr passes through, and a gate holds that line: no module
under `_private`, and nothing from `_core` but redaction.

Three properties are load-bearing and each is gated. Cookie material never arrives through
`argv`. Every deliberate failure has its own exit code. And pagination stops on the page's own
`has_next_page`, never on how many messages came back.

`_cli` is private on purpose. The command is a product and the entry point is stable, but the
module layout behind it is not, and nothing here appears in `tests/public_surface.txt`.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from typing import TextIO

from dumpstagram._cli.commands.common import (
   SESSION_PATH_ENV,
   ClientFactory,
   UsageError,
   open_client,
)
from dumpstagram._cli.commands.direct import (
   add_message_write_parsers,
   add_thread_parser,
   run_direct_write,
   run_thread,
)
from dumpstagram._cli.commands.doctor import (
   DoctorFactory,
   PlanFactory,
   add_doctor_parser,
   open_doctor,
   plan_only,
   run_doctor,
)
from dumpstagram._cli.commands.events import (
   AsyncListeningClientFactory,
   ListeningClientFactory,
   add_events_parser,
   open_async_listening_client,
   open_listening_client,
   run_events,
)
from dumpstagram._cli.commands.feed import add_feed_parser, run_feed
from dumpstagram._cli.commands.media import (
   add_comment_parsers,
   add_like_parsers,
   add_post_parser,
   run_comment_command,
   run_like_write,
   run_post,
)
from dumpstagram._cli.commands.notes import add_note_parser, run_note_list, run_note_write
from dumpstagram._cli.commands.posting import (
   POSTING_COMMANDS,
   add_posting_parsers,
   run_posting_command,
)
from dumpstagram._cli.commands.profiles import add_profile_parser, run_profile
from dumpstagram._cli.commands.session import (
   add_adopt_parser,
   add_session_parser,
   run_adopt,
   run_session,
)
from dumpstagram._cli.commands.social import add_follow_parsers, run_follow_write
from dumpstagram._cli.exits import EXIT_USAGE, exit_code_for
from dumpstagram._core.redaction import redact
from dumpstagram.errors import DumpstagramError

__all__ = ["build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
   """The whole command line, assembled in one place from each domain's commands, so a gate
   can read it.

   No option here takes a cookie, a token, or a password. That is a rule with a test behind
   it rather than a habit.
   """

   parser = argparse.ArgumentParser(
      prog="dumpsta",
      description="Read an Instagram account through Dumpsta-Engine.",
   )
   parser.add_argument(
      "--session",
      metavar="PATH",
      help=f"the session file to use, defaulting to ${SESSION_PATH_ENV}",
   )
   parser.add_argument(
      "--json", action="store_true", help="emit machine-readable JSON instead of text"
   )

   commands = parser.add_subparsers(dest="command", required=True)

   add_adopt_parser(commands)
   add_session_parser(commands)
   add_thread_parser(commands)
   add_feed_parser(commands)
   add_profile_parser(commands)
   add_note_parser(commands)
   add_post_parser(commands)
   add_like_parsers(commands)
   add_follow_parsers(commands)
   add_message_write_parsers(commands)
   add_comment_parsers(commands)
   add_events_parser(commands)
   add_doctor_parser(commands)
   add_posting_parsers(commands)

   return parser


def main(
   argv: list[str] | None = None,
   *,
   environment: Mapping[str, str] | None = None,
   client_factory: ClientFactory = open_client,
   listening_client_factory: ListeningClientFactory = open_listening_client,
   async_listening_client_factory: AsyncListeningClientFactory = open_async_listening_client,
   doctor_factory: DoctorFactory = open_doctor,
   plan_factory: PlanFactory = plan_only,
   stdout: TextIO | None = None,
   stderr: TextIO | None = None,
) -> int:
   """Parse ``argv``, run one command, and return its exit code.

   Every argument after the first exists so the tests can drive this without a network, a
   real session file, or a captured process. The installed entry point passes none of them.
   """

   arguments = build_parser().parse_args(argv)
   chosen_environment = os.environ if environment is None else environment
   out = sys.stdout if stdout is None else stdout
   errors = sys.stderr if stderr is None else stderr

   try:
      if arguments.command == "adopt":
         return run_adopt(arguments, chosen_environment, out)

      if arguments.command == "session":
         return run_session(arguments, chosen_environment, out)

      if arguments.command == "feed":
         return run_feed(arguments, chosen_environment, out, client_factory)

      if arguments.command == "profile":
         return run_profile(arguments, chosen_environment, out, client_factory)

      is_a_note_write = arguments.command == "note" and arguments.note_action != "list"

      if is_a_note_write:
         return run_note_write(arguments, chosen_environment, out, client_factory)

      if arguments.command == "note":
         return run_note_list(arguments, chosen_environment, out, client_factory)

      if arguments.command == "post":
         return run_post(arguments, chosen_environment, out, client_factory)

      if arguments.command in ("like", "unlike"):
         return run_like_write(arguments, chosen_environment, out, client_factory)

      if arguments.command in ("follow", "unfollow"):
         return run_follow_write(arguments, chosen_environment, out, client_factory)

      if arguments.command in ("comments", "comment", "delete-comment"):
         return run_comment_command(arguments, chosen_environment, out, client_factory)

      if arguments.command in POSTING_COMMANDS:
         return run_posting_command(arguments, chosen_environment, out, client_factory)

      if arguments.command in ("send-message", "unsend-message"):
         return run_direct_write(arguments, chosen_environment, out, client_factory)

      if arguments.command == "doctor":
         return run_doctor(arguments, chosen_environment, out, errors, doctor_factory, plan_factory)

      if arguments.command == "events":
         return run_events(
            arguments,
            chosen_environment,
            out,
            listening_client_factory,
            async_listening_client_factory,
         )

      return run_thread(arguments, chosen_environment, out, client_factory)
   except DumpstagramError as failure:
      print(redact(f"{type(failure).__name__}: {failure}"), file=errors)

      for note in getattr(failure, "__notes__", ()):
         print(redact(note), file=errors)

      return exit_code_for(failure)
   except (UsageError, OSError) as failure:
      print(redact(str(failure)), file=errors)

      return EXIT_USAGE


if __name__ == "__main__":
   sys.exit(main())
