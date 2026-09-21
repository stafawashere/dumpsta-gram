"""The `dumpsta` command, which is the engine's first consumer and its acceptance harness.

ADR-0005 makes this a real consumer rather than a demo. Every capability it reaches, it
reaches through `SyncClient`, so anything awkward to do from this file is a gap in the public
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
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, TextIO

from dumpstagram._cli.cookie_sources import read_cookie_file, session_from
from dumpstagram._cli.exits import EXIT_OK, EXIT_USAGE, exit_code_for
from dumpstagram._cli.render import (
   describe_message,
   describe_pages,
   describe_session,
   render_messages,
   render_session,
)
from dumpstagram._core.redaction import redact
from dumpstagram.client import SyncClient
from dumpstagram.errors import DumpstagramError
from dumpstagram.models import Message, Page
from dumpstagram.session import Session

__all__ = ["build_parser", "main"]

SESSION_PATH_ENV = "DUMPSTAGRAM_SESSION"
"""The environment variable that answers when `--session` is not passed.

There is no default path. A session file is a credential, and guessing a location for one is
how a tool writes an account token somewhere its owner did not choose.
"""


class Client(Protocol):
   """What the CLI needs of a client, which is what `SyncClient` already offers.

   Stated as a protocol so the tests can drive every command with a fake and spend no live
   request. It is not a second surface: `SyncClient` satisfies it as written.
   """

   @property
   def session(self) -> Session: ...

   def thread_messages(
      self,
      thread_fbid: str,
      *,
      after: str | None = None,
      newer_than_message_id: str | None = None,
   ) -> Page[Message]: ...

   def close(self) -> None: ...


class ClientFactory(Protocol):
   def __call__(self, path: Path, *, user_agent: str | None = None) -> Client: ...


class UsageError(Exception):
   """A command line that parsed but cannot be carried out."""


def open_client(path: Path, *, user_agent: str | None = None) -> Client:
   return SyncClient.from_session_file(path, user_agent=user_agent)


def page_count(value: str) -> int:
   count = int(value)

   if count < 1:
      raise argparse.ArgumentTypeError("a page count is at least 1")

   return count


def build_parser() -> argparse.ArgumentParser:
   """The whole command line in one place, so a gate can read it.

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

   adopt = commands.add_parser(
      "adopt",
      help="build a session from cookie material and save it, spending no live request",
      description=(
         "Cookie material is read from the environment, or from --cookies-file, and never "
         "from the command line. Required keys: IG_SESSIONID, IG_DS_USER_ID, IG_CSRFTOKEN. "
         "Optional: IG_MID."
      ),
   )
   adopt.add_argument(
      "--cookies-file",
      metavar="PATH",
      help="a file of KEY=value lines to read cookie material from instead of the environment",
   )

   commands.add_parser(
      "session",
      help="print what the saved session holds, redacted, spending no live request",
   )

   thread = commands.add_parser(
      "thread", help="read pages of one direct thread, one live request per page"
   )
   thread.add_argument("thread_fbid", metavar="FBID", help="the thread's fbid")
   thread.add_argument(
      "--pages",
      type=page_count,
      default=1,
      metavar="N",
      help="how many pages to read at most, default 1",
   )
   thread.add_argument("--after", metavar="CURSOR", help="an end_cursor from an earlier page")
   thread.add_argument(
      "--since",
      metavar="MESSAGE_ID",
      help="read only what arrived after this message, applied to the first page",
   )
   thread.add_argument(
      "--user-agent",
      metavar="STRING",
      help="override the user agent every request claims to be",
   )
   thread.add_argument(
      "--no-session-writeback",
      action="store_true",
      help="do not save tokens harvested during this run back to the session file",
   )

   return parser


def resolve_session_path(chosen: str | None, environment: Mapping[str, str]) -> Path:
   path = chosen or environment.get(SESSION_PATH_ENV)

   if not path:
      raise UsageError(f"no session file given. Pass --session PATH or set ${SESSION_PATH_ENV}")

   return Path(path)


def emit(payload: dict[str, Any], text: str, *, as_json: bool, stream: TextIO) -> None:
   rendered = json.dumps(payload, indent=2) if as_json else text

   print(rendered, file=stream)


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

   emit(summary, render_session(summary), as_json=arguments.json, stream=stdout)

   return EXIT_OK


def read_pages(client: Client, arguments: argparse.Namespace) -> list[Page[Message]]:
   """Read up to ``--pages`` pages, stopping on the page's own terminator.

   ``--since`` is applied to the first request only. Combining it with a cursor has never been
   measured, and a client that sends both is asking the upstream a question nobody has seen
   the answer to.
   """

   pages: list[Page[Message]] = []
   cursor = arguments.after
   newer_than = arguments.since

   for _ in range(arguments.pages):
      page = client.thread_messages(
         arguments.thread_fbid, after=cursor, newer_than_message_id=newer_than
      )

      pages.append(page)

      if not page.has_next_page:
         break

      cursor = page.end_cursor
      newer_than = None

   return pages


def run_thread(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_read = client.session.fb_dtsg

   try:
      pages = read_pages(client, arguments)

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_read
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   payload = {
      "command": "thread",
      "thread_fbid": arguments.thread_fbid,
      **describe_pages(pages),
      "messages": [describe_message(message) for page in pages for message in page.items],
   }

   emit(payload, render_messages(pages), as_json=arguments.json, stream=stdout)

   return EXIT_OK


def main(
   argv: list[str] | None = None,
   *,
   environment: Mapping[str, str] | None = None,
   client_factory: ClientFactory = open_client,
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

      return run_thread(arguments, chosen_environment, out, client_factory)
   except DumpstagramError as failure:
      print(redact(f"{type(failure).__name__}: {failure}"), file=errors)

      return exit_code_for(failure)
   except (UsageError, OSError) as failure:
      print(redact(str(failure)), file=errors)

      return EXIT_USAGE


if __name__ == "__main__":
   sys.exit(main())
