"""The two commands that spend no live request: adopt a browser session, and print one.

`session --clear-write-stop` is the one way the CLI lifts a write stop, and it is always a
person's decision. It clears the stop in the pacing ledger beside the session file and keeps
the budget's departures, so clearing a stop never also hands back an hour's writes.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO

from dumpstagram._cli.commands.common import Subcommands, emit, resolve_session_path
from dumpstagram._cli.cookie_sources import read_cookie_file, session_from
from dumpstagram._cli.exits import EXIT_OK
from dumpstagram._cli.render.session import describe_session, render_session
from dumpstagram.session import Session, clear_write_stop

__all__ = [
   "add_adopt_parser",
   "add_session_parser",
   "run_adopt",
   "run_session",
]


def run_adopt(arguments: argparse.Namespace, environment: Mapping[str, str], stdout: TextIO) -> int:
   source = (
      read_cookie_file(Path(arguments.cookies_file))
      if arguments.cookies_file
      else dict(environment)
   )
   session = session_from(source)
   path = resolve_session_path(arguments.session, environment)

   session.save(path)

   summary = describe_session(session, path)

   emit(summary, render_session(summary), as_json=arguments.json, stream=stdout)

   return EXIT_OK


def run_session(
   arguments: argparse.Namespace, environment: Mapping[str, str], stdout: TextIO
) -> int:
   path = resolve_session_path(arguments.session, environment)
   summary = describe_session(Session.load(path), path)

   if arguments.clear_write_stop:
      summary["write_stop_cleared"] = clear_write_stop(path)

   emit(summary, render_session(summary), as_json=arguments.json, stream=stdout)

   return EXIT_OK


def add_adopt_parser(commands: Subcommands) -> None:
   adopt = commands.add_parser(
      "adopt",
      help="build a session from cookie material and save it, spending no live request",
      description=(
         "Cookie material is read from the environment, or from --cookies-file, and never "
         "from the command line. Required keys: IG_SESSIONID, IG_DS_USER_ID, IG_CSRFTOKEN. "
         "Optional: IG_MID, and IG_FR, the fr value from the browser's localStorage."
      ),
   )
   adopt.add_argument(
      "--cookies-file",
      metavar="PATH",
      help="a file of KEY=value lines to read cookie material from instead of the environment",
   )


def add_session_parser(commands: Subcommands) -> None:
   session = commands.add_parser(
      "session",
      help="print what the saved session holds, redacted, spending no live request",
   )
   session.add_argument(
      "--clear-write-stop",
      action="store_true",
      help=(
         "lift the write stop kept beside the session file, after a person has checked the "
         "account. The hour's write budget is kept"
      ),
   )
