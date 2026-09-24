"""The direct commands: read a thread's pages, and send or unsend a text message."""

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
from dumpstagram._cli.exits import EXIT_OK
from dumpstagram._cli.render.direct import (
   describe_message,
   describe_pages,
   describe_sent_message,
   render_messages,
)
from dumpstagram.models import (
   Message,
   Page,
)

__all__ = [
   "add_message_write_parsers",
   "add_thread_parser",
   "message_id",
   "read_pages",
   "run_direct_write",
   "run_thread",
   "thread_fbid",
]


def thread_fbid(value: str) -> str:
   is_all_digits = value.isascii() and value.isdigit()

   if not is_all_digits:
      raise argparse.ArgumentTypeError(
         "a thread is named by its thread_fbid, digits only, the FBID dumpsta thread takes"
      )

   return value


def message_id(value: str) -> str:
   is_a_mid = value.startswith("mid.")

   if not is_a_mid:
      raise argparse.ArgumentTypeError("a message is named by its id, a mid. string")

   return value


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


def run_direct_write(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_write = client.session.fb_dtsg

   try:
      if arguments.command == "send-message":
         sent = client.send_message(arguments.thread_fbid, arguments.text)
         payload: dict[str, Any] = {
            "command": "send-message",
            "thread_fbid": arguments.thread_fbid,
            "message": describe_sent_message(sent),
         }
         text = f"sent {sent.id} into {arguments.thread_fbid}"
      else:
         client.unsend_message(arguments.thread_fbid, arguments.message_id)
         payload = {
            "command": "unsend-message",
            "thread_fbid": arguments.thread_fbid,
            "message_id": arguments.message_id,
            "unsent": True,
         }
         text = f"unsent {arguments.message_id} from {arguments.thread_fbid}"

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_write
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   emit(payload, text, as_json=arguments.json, stream=stdout)

   return EXIT_OK


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


def add_thread_parser(commands: Subcommands) -> None:
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


def add_message_write_parsers(commands: Subcommands) -> None:
   send = commands.add_parser(
      "send-message",
      help="send one text message into a direct thread, one write, sent once and never retried",
      description=(
         "Writes to the account: sends TEXT into the thread whose thread_fbid is FBID. The "
         "other people in the thread are notified and may read it at once. There is no prompt "
         "and no default thread. The output carries the message id, which unsend-message "
         "takes, and its offline_threading_id, which dumpsta thread FBID prints on the same "
         "message. If the outcome is unknown, read dumpsta thread FBID before sending again, "
         "because a second send is a second message."
      ),
   )
   send.add_argument("thread_fbid", metavar="FBID", type=thread_fbid, help="the thread's fbid")
   send.add_argument("text", metavar="TEXT", help="the message, as it should appear")
   add_request_options(send)

   unsend = commands.add_parser(
      "unsend-message",
      help="unsend one of the viewer's messages, one write, sent once and never retried",
      description=(
         "Writes to the account: unsends the viewer's message MESSAGE_ID from the thread whose "
         "thread_fbid is FBID. The thread is opened first to learn the identifier the unsend "
         "takes, two requests in all. The recipient may already have read the message. Read "
         "dumpsta thread FBID afterwards: an unsent message is no longer listed."
      ),
   )
   unsend.add_argument("thread_fbid", metavar="FBID", type=thread_fbid, help="the thread's fbid")
   unsend.add_argument(
      "message_id", metavar="MESSAGE_ID", type=message_id, help="the message's id, a mid. string"
   )
   add_request_options(unsend)
