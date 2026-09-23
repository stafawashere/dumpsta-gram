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
import asyncio
import json
import os
import sys
import time
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import aclosing
from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol, TextIO

from dumpstagram._cli.cookie_sources import read_cookie_file, session_from
from dumpstagram._cli.exits import EXIT_OK, EXIT_USAGE, exit_code_for
from dumpstagram._cli.render import (
   describe_comment,
   describe_comment_page,
   describe_event,
   describe_feed_item,
   describe_feed_pages,
   describe_message,
   describe_note,
   describe_pages,
   describe_post_detail,
   describe_profile,
   describe_sent_message,
   describe_session,
   render_comment_page,
   render_event,
   render_feed,
   render_messages,
   render_notes,
   render_post_detail,
   render_profile,
   render_session,
)
from dumpstagram._core.redaction import redact
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY, Behavior
from dumpstagram.client import SyncClient
from dumpstagram.errors import DumpstagramError
from dumpstagram.models import (
   Comment,
   Event,
   EventsDropped,
   FeedItem,
   ListenerStopped,
   Message,
   NewMessage,
   Note,
   NoteAudience,
   Page,
   PostDetail,
   Profile,
   SentMessage,
)
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

   def feed(self, *, after: str | None = None) -> Page[FeedItem]: ...

   def profile(self, username: str) -> Profile: ...

   def profile_by_id(self, user_id: str) -> Profile: ...

   def notes(self) -> tuple[Note, ...]: ...

   def set_note(self, text: str, *, audience: NoteAudience = ...) -> Note: ...

   def delete_note(self, note_id: str) -> None: ...

   def post(self, code: str) -> PostDetail: ...

   def like(self, post_pk: str) -> None: ...

   def unlike(self, post_pk: str) -> None: ...

   def follow(self, user_id: str) -> None: ...

   def unfollow(self, user_id: str) -> None: ...

   def comments(self, post_pk: str, *, after: str | None = None) -> Page[Comment]: ...

   def comment(self, post_pk: str, text: str) -> Comment: ...

   def delete_comment(self, post_pk: str, comment_id: str) -> None: ...

   def send_message(self, thread_fbid: str, text: str) -> SentMessage: ...

   def unsend_message(self, thread_fbid: str, message_id: str) -> None: ...

   def close(self) -> None: ...


class ClientFactory(Protocol):
   def __call__(self, path: Path, *, user_agent: str | None = None) -> Client: ...


class Listener(Protocol):
   """What `events` needs of a blocking listener, which `EventListener` offers as written."""

   def start(self) -> None: ...

   def stop(self) -> None: ...

   def wait_for_events(self, timeout: float | None) -> list[Event]: ...


class ListeningClient(Protocol):
   @property
   def session(self) -> Session: ...

   def events(self, *, since: str | None = None) -> Listener: ...

   def close(self) -> None: ...


class AsyncListeningClient(Protocol):
   @property
   def session(self) -> Session: ...

   def events(self, *, since: str | None = None) -> AsyncIterator[Event]: ...

   async def aclose(self) -> None: ...


class ListeningClientFactory(Protocol):
   def __call__(
      self, path: Path, *, user_agent: str | None, behavior: Behavior
   ) -> ListeningClient: ...


class AsyncListeningClientFactory(Protocol):
   def __call__(
      self, path: Path, *, user_agent: str | None, behavior: Behavior
   ) -> AsyncListeningClient: ...


class UsageError(Exception):
   """A command line that parsed but cannot be carried out."""


def open_client(path: Path, *, user_agent: str | None = None) -> Client:
   return SyncClient.from_session_file(path, user_agent=user_agent)


def open_listening_client(
   path: Path, *, user_agent: str | None, behavior: Behavior
) -> ListeningClient:
   return SyncClient.from_session_file(path, user_agent=user_agent, behavior=behavior)


def open_async_listening_client(
   path: Path, *, user_agent: str | None, behavior: Behavior
) -> AsyncListeningClient:
   return AsyncClient.from_session_file(path, user_agent=user_agent, behavior=behavior)


def positive_seconds(value: str) -> float:
   seconds = float(value)

   if seconds <= 0:
      raise argparse.ArgumentTypeError("a duration is more than 0 seconds")

   return seconds


def interval_seconds(value: str) -> float:
   seconds = float(value)

   if seconds < 0:
      raise argparse.ArgumentTypeError("a poll interval cannot be negative")

   return seconds


def page_count(value: str) -> int:
   count = int(value)

   if count < 1:
      raise argparse.ArgumentTypeError("a page count is at least 1")

   return count


def media_pk(value: str) -> str:
   is_all_digits = value.isascii() and value.isdigit()

   if not is_all_digits:
      raise argparse.ArgumentTypeError(
         "a post is named by its pk, digits only, not by the <pk>_<author id> form"
      )

   return value


def account_id(value: str) -> str:
   is_all_digits = value.isascii() and value.isdigit()

   if not is_all_digits:
      raise argparse.ArgumentTypeError(
         "an account is named by its numeric id, digits only, not by its username. "
         "dumpsta profile USERNAME prints the id"
      )

   return value


def comment_id(value: str) -> str:
   is_all_digits = value.isascii() and value.isdigit()

   if not is_all_digits:
      raise argparse.ArgumentTypeError("a comment is named by its id, digits only")

   return value


def note_id(value: str) -> str:
   is_all_digits = value.isascii() and value.isdigit()

   if not is_all_digits:
      raise argparse.ArgumentTypeError("a note is named by its tray item id, digits only")

   return value


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


NOTE_AUDIENCES = {
   "close-friends": NoteAudience.CLOSE_FRIENDS,
   "mutual-follows": NoteAudience.MUTUAL_FOLLOWS,
}
"""The audiences the web composer offers, by the name the command line takes."""


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
         "Optional: IG_MID, and IG_FR, the fr value from the browser's localStorage."
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

   feed = commands.add_parser(
      "feed",
      help="read pages of the home timeline, one live request per page",
      description=(
         "Most of a timeline is not posts. Every item is reported with its kind, and only "
         "the ones whose kind is media carry a post."
      ),
   )
   feed.add_argument(
      "--pages",
      type=page_count,
      default=1,
      metavar="N",
      help="how many pages to read at most, default 1",
   )
   feed.add_argument("--after", metavar="CURSOR", help="an end_cursor from an earlier page")
   feed.add_argument(
      "--posts-only",
      action="store_true",
      help="print only the items that carry a post, and report how many were dropped",
   )
   feed.add_argument(
      "--user-agent",
      metavar="STRING",
      help="override the user agent every request claims to be",
   )
   feed.add_argument(
      "--no-session-writeback",
      action="store_true",
      help="do not save tokens harvested during this run back to the session file",
   )

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

   note = commands.add_parser(
      "note",
      help="read the notes tray, set the viewer's note, or delete it",
      description=(
         "list reads the whole tray, one live request, and marks the viewer's own note. set and "
         "delete write to the account, one write each, sent once and never retried."
      ),
   )
   note_actions = note.add_subparsers(dest="note_action", required=True)
   note_list = note_actions.add_parser("list", help="read the whole notes tray, one live request")
   note_list.add_argument(
      "--user-agent",
      metavar="STRING",
      help="override the user agent every request claims to be",
   )
   note_list.add_argument(
      "--no-session-writeback",
      action="store_true",
      help="do not save tokens harvested during this run back to the session file",
   )

   note_set = note_actions.add_parser(
      "set",
      help="set the viewer's note, one write, sent once and never retried",
      description=(
         "Writes to the account: sets the viewer's note to TEXT for the named audience, "
         "replacing any note already up, a song note included. Prints the new note's id, which "
         "delete takes. If the outcome is unknown, read dumpsta note list before sending again."
      ),
   )
   note_set.add_argument("text", metavar="TEXT", help="the note, as it should appear")
   note_set.add_argument(
      "--audience",
      required=True,
      choices=sorted(NOTE_AUDIENCES),
      help="who sees the note: close-friends, or mutual-follows for followers followed back",
   )
   add_request_options(note_set)

   note_delete = note_actions.add_parser(
      "delete",
      help="delete the viewer's note, one write, sent once and never retried",
      description=(
         "Writes to the account: deletes the note whose tray item id is NOTE_ID. If the outcome "
         "is unknown, read dumpsta note list: a note no longer listed is gone."
      ),
   )
   note_delete.add_argument(
      "note_id", metavar="NOTE_ID", type=note_id, help="the note's tray item id, digits only"
   )
   add_request_options(note_delete)

   post = commands.add_parser(
      "post",
      help="read one post by its shortcode, one live request",
      description=(
         "Reads the post whose web address carries CODE and prints its pk, which like and "
         "unlike take, and whether the viewer likes it."
      ),
   )
   post.add_argument("code", metavar="CODE", help="the shortcode from the post's web address")
   add_request_options(post)

   for verb, effect in (("like", "like"), ("unlike", "remove the viewer's like from")):
      write = commands.add_parser(
         verb,
         help=f"{effect} one post, one write, sent once and never retried",
         description=(
            f"Writes to the account: {effect} the post whose pk is PK. There is no prompt and "
            "no default target. If the outcome is unknown, read the post with dumpsta post "
            "before sending again."
         ),
      )
      write.add_argument("pk", metavar="PK", type=media_pk, help="the post's pk, digits only")
      add_request_options(write)

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

   comments = commands.add_parser(
      "comments",
      help="read one page of a post's comments, one live request",
      description=(
         "Reads one page of the comments on the post whose pk is PK and prints each comment's "
         "id, which delete-comment takes, and whether more pages exist."
      ),
   )
   comments.add_argument("pk", metavar="PK", type=media_pk, help="the post's pk, digits only")
   comments.add_argument("--after", metavar="CURSOR", help="an end_cursor from an earlier page")
   add_request_options(comments)

   comment = commands.add_parser(
      "comment",
      help="comment on one post, one write, sent once and never retried",
      description=(
         "Writes to the account: posts TEXT as a comment on the post whose pk is PK, where "
         "everyone who can see the post sees it. There is no prompt and no default target. If "
         "the outcome is unknown, read dumpsta comments PK before sending again, because a "
         "second send is a second comment."
      ),
   )
   comment.add_argument("pk", metavar="PK", type=media_pk, help="the post's pk, digits only")
   comment.add_argument("text", metavar="TEXT", help="the comment, as it should appear")
   add_request_options(comment)

   delete_comment = commands.add_parser(
      "delete-comment",
      help="delete one comment on a post, one write, sent once and never retried",
      description=(
         "Writes to the account: deletes the comment COMMENT_ID on the post whose pk is PK. "
         "There is no prompt and no default target. If the outcome is unknown, read dumpsta "
         "comments PK: a comment no longer listed is gone."
      ),
   )
   delete_comment.add_argument("pk", metavar="PK", type=media_pk, help="the post's pk, digits only")
   delete_comment.add_argument(
      "comment_id", metavar="COMMENT_ID", type=comment_id, help="the comment's id, digits only"
   )
   add_request_options(delete_comment)

   events = commands.add_parser(
      "events",
      help="print new direct messages as they arrive, for a fixed time",
      description=(
         "Polls the inbox for --duration seconds and prints one line per event as it arrives, "
         "one JSON object per line with --json. Each poll is one live request, plus one per "
         "page of a thread that gained messages. The first poll prints nothing unless --since "
         "names the last message already handled. Nothing is marked seen."
      ),
   )
   events.add_argument(
      "--duration",
      type=positive_seconds,
      required=True,
      metavar="SECONDS",
      help="how long to listen before stopping",
   )
   events.add_argument(
      "--since",
      metavar="MESSAGE_ID",
      help="the id of the last message already handled, to catch up from",
   )
   events.add_argument(
      "--interval",
      type=interval_seconds,
      metavar="SECONDS",
      help=f"seconds between polls, default {PARITY.poll_interval_seconds:g}",
   )
   events.add_argument(
      "--surface",
      choices=("sync", "async"),
      default="sync",
      help="listen through a drained SyncClient listener or the AsyncClient iterator",
   )
   events.add_argument(
      "--ids-only",
      action="store_true",
      help="print identifiers and times only, never a message's text or sender name",
   )
   add_request_options(events)

   return parser


def add_request_options(command: argparse.ArgumentParser) -> None:
   command.add_argument(
      "--user-agent",
      metavar="STRING",
      help="override the user agent every request claims to be",
   )
   command.add_argument(
      "--no-session-writeback",
      action="store_true",
      help="do not save tokens harvested during this run back to the session file",
   )


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


def read_feed_pages(client: Client, arguments: argparse.Namespace) -> list[Page[FeedItem]]:
   """Read up to ``--pages`` pages, stopping on the page's own terminator.

   The loop never stops because a page looked short. Measured pages carried 14, 12 and 5
   items for the same request, so a length is not a signal here any more than it is anywhere
   else on this surface.
   """

   pages: list[Page[FeedItem]] = []
   cursor = arguments.after

   for _ in range(arguments.pages):
      page = client.feed(after=cursor)

      pages.append(page)

      if not page.has_next_page:
         break

      cursor = page.end_cursor

   return pages


def run_feed(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_read = client.session.fb_dtsg

   try:
      pages = read_feed_pages(client, arguments)

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_read
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   items = [item for page in pages for item in page.items]
   shown = [item for item in items if item.post is not None] if arguments.posts_only else items

   payload = {
      "command": "feed",
      **describe_feed_pages(pages),
      "posts_only": arguments.posts_only,
      "items": [describe_feed_item(item) for item in shown],
   }

   emit(
      payload,
      render_feed(pages, posts_only=arguments.posts_only),
      as_json=arguments.json,
      stream=stdout,
   )

   return EXIT_OK


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


def run_note_list(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_read = client.session.fb_dtsg
   viewer_id = client.session.ds_user_id

   try:
      notes = client.notes()

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_read
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   own_notes = [note for note in notes if note.author_id == viewer_id]

   payload = {
      "command": "note list",
      "note_count": len(notes),
      "own_note_id": own_notes[0].id if own_notes else None,
      "notes": [describe_note(note, viewer_id=viewer_id) for note in notes],
   }

   emit(payload, render_notes(notes, viewer_id=viewer_id), as_json=arguments.json, stream=stdout)

   return EXIT_OK


def run_note_write(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_write = client.session.fb_dtsg
   actor_id_before_the_write = client.session.actor_id
   viewer_id = client.session.ds_user_id

   try:
      if arguments.note_action == "set":
         created = client.set_note(arguments.text, audience=NOTE_AUDIENCES[arguments.audience])
         payload: dict[str, object] = {
            "command": "note set",
            "note": describe_note(created, viewer_id=viewer_id),
         }
         text = f"set note {created.id}  [{created.audience.name.lower()}]"
      else:
         client.delete_note(arguments.note_id)
         payload = {"command": "note delete", "note_id": arguments.note_id, "deleted": True}
         text = f"deleted note {arguments.note_id}"

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_write
      harvested_the_actor_id = client.session.actor_id != actor_id_before_the_write
      harvested_anything = harvested_a_new_token or harvested_the_actor_id
      may_write_back = not arguments.no_session_writeback

      if harvested_anything and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   emit(payload, text, as_json=arguments.json, stream=stdout)

   return EXIT_OK


def run_post(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_read = client.session.fb_dtsg

   try:
      post = client.post(arguments.code)

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_read
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   payload = {"command": "post", "post": describe_post_detail(post)}

   emit(payload, render_post_detail(post), as_json=arguments.json, stream=stdout)

   return EXIT_OK


def run_like_write(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_write = client.session.fb_dtsg
   is_like = arguments.command == "like"

   try:
      if is_like:
         client.like(arguments.pk)
      else:
         client.unlike(arguments.pk)

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_write
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   payload = {"command": arguments.command, "pk": arguments.pk, "has_liked": is_like}

   emit(
      payload,
      f"{arguments.command}d {arguments.pk}  has_liked: {is_like}",
      as_json=arguments.json,
      stream=stdout,
   )

   return EXIT_OK


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


def run_comment_command(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_call = client.session.fb_dtsg

   try:
      if arguments.command == "comments":
         page = client.comments(arguments.pk, after=arguments.after)
         payload = {"command": "comments", "pk": arguments.pk, **describe_comment_page(page)}
         text = render_comment_page(page)
      elif arguments.command == "comment":
         created = client.comment(arguments.pk, arguments.text)
         payload = {"command": "comment", "pk": arguments.pk, "comment": describe_comment(created)}
         text = f"commented {created.id} on {arguments.pk}"
      else:
         client.delete_comment(arguments.pk, arguments.comment_id)
         payload = {
            "command": "delete-comment",
            "pk": arguments.pk,
            "comment_id": arguments.comment_id,
            "deleted": True,
         }
         text = f"deleted {arguments.comment_id} on {arguments.pk}"

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_call
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   emit(payload, text, as_json=arguments.json, stream=stdout)

   return EXIT_OK


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


def listening_behavior(arguments: argparse.Namespace) -> Behavior:
   if arguments.interval is None:
      return PARITY

   return replace(PARITY, poll_interval_seconds=arguments.interval)


def listen_blocking(
   client: ListeningClient,
   arguments: argparse.Namespace,
   report: Callable[[Event], None],
) -> None:
   """Drain a blocking listener until the duration runs out, as a Swift consumer would."""

   listener = client.events(since=arguments.since)
   deadline = time.monotonic() + arguments.duration

   listener.start()

   try:
      while True:
         remaining = deadline - time.monotonic()

         if remaining <= 0:
            return

         for event in listener.wait_for_events(remaining):
            report(event)
   finally:
      listener.stop()


async def listen_async(
   client: AsyncListeningClient,
   arguments: argparse.Namespace,
   report: Callable[[Event], None],
) -> None:
   timer = asyncio.timeout(arguments.duration)

   try:
      async with timer:
         async with aclosing(client.events(since=arguments.since)) as stream:  # type: ignore[type-var]
            async for event in stream:
               report(event)
   except TimeoutError:
      if not timer.expired():
         raise


def run_events(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   listening_client_factory: ListeningClientFactory,
   async_listening_client_factory: AsyncListeningClientFactory,
) -> int:
   """Listen for ``--duration`` seconds and print every event as it arrives.

   A final ``ListenerStopped`` from the blocking listener re-raises its error, so a checkpoint
   ends the command with the checkpoint's exit code on either surface.
   """

   path = resolve_session_path(arguments.session, environment)
   behavior = listening_behavior(arguments)
   counts = {"new_messages": 0, "events_dropped": 0}

   def report(event: Event) -> None:
      if isinstance(event, ListenerStopped):
         raise event.error

      if isinstance(event, NewMessage):
         counts["new_messages"] += 1

      if isinstance(event, EventsDropped):
         counts["events_dropped"] += 1

      if arguments.json:
         line = json.dumps(describe_event(event, ids_only=arguments.ids_only))
      else:
         line = render_event(event, ids_only=arguments.ids_only)

      print(line, file=stdout, flush=True)

   if arguments.surface == "async":
      async_client = async_listening_client_factory(
         path, user_agent=arguments.user_agent, behavior=behavior
      )
      session = async_client.session
      token_before_the_run = session.fb_dtsg

      listen_async_to_the_end(async_client, arguments, report)
   else:
      client = listening_client_factory(path, user_agent=arguments.user_agent, behavior=behavior)
      session = client.session
      token_before_the_run = session.fb_dtsg

      listen_blocking_to_the_end(client, arguments, report)

   harvested_a_new_token = session.fb_dtsg != token_before_the_run
   may_write_back = not arguments.no_session_writeback

   if harvested_a_new_token and may_write_back:
      session.save(path)

   summary = {
      "command": "events",
      "surface": arguments.surface,
      "duration_seconds": arguments.duration,
      "poll_interval_seconds": behavior.poll_interval_seconds,
      **counts,
   }

   if arguments.json:
      print(json.dumps(summary), file=stdout)
   else:
      print("  ".join(f"{key}: {value}" for key, value in summary.items()), file=stdout)

   return EXIT_OK


def listen_blocking_to_the_end(
   client: ListeningClient,
   arguments: argparse.Namespace,
   report: Callable[[Event], None],
) -> None:
   try:
      listen_blocking(client, arguments, report)
   finally:
      client.close()


def listen_async_to_the_end(
   client: AsyncListeningClient,
   arguments: argparse.Namespace,
   report: Callable[[Event], None],
) -> None:
   """Run the async iterator on a loop of the command's own, once, for the whole run.

   The command is a process entry point, not a facade, so one loop for its one run is what the
   loop-per-call rule in ``tests/test_loop_thread.py`` leaves allowed.
   """

   async def listen_and_close() -> None:
      try:
         await listen_async(client, arguments, report)
      finally:
         await client.aclose()

   with asyncio.Runner() as runner:
      runner.run(listen_and_close())


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
   listening_client_factory: ListeningClientFactory = open_listening_client,
   async_listening_client_factory: AsyncListeningClientFactory = open_async_listening_client,
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

      if arguments.command in ("send-message", "unsend-message"):
         return run_direct_write(arguments, chosen_environment, out, client_factory)

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

      return exit_code_for(failure)
   except (UsageError, OSError) as failure:
      print(redact(str(failure)), file=errors)

      return EXIT_USAGE


if __name__ == "__main__":
   sys.exit(main())
