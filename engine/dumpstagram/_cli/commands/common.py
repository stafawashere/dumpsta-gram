"""What every command shares: the client it drives, the session path, and how a result is
emitted.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, TextIO

from dumpstagram.client import SyncClient
from dumpstagram.models import (
   Comment,
   FeedItem,
   Message,
   Note,
   NoteAudience,
   Page,
   PostDetail,
   Profile,
   SentMessage,
)
from dumpstagram.namespaces.media import SyncMedia
from dumpstagram.session import Session

__all__ = [
   "Client",
   "ClientFactory",
   "SESSION_PATH_ENV",
   "Subcommands",
   "UsageError",
   "add_request_options",
   "emit",
   "open_client",
   "page_count",
   "resolve_session_path",
]

type Subcommands = argparse._SubParsersAction[argparse.ArgumentParser]

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

   @property
   def media(self) -> SyncMedia: ...

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


class UsageError(Exception):
   """A command line that parsed but cannot be carried out."""


def open_client(path: Path, *, user_agent: str | None = None) -> Client:
   return SyncClient.from_session_file(path, user_agent=user_agent)


def page_count(value: str) -> int:
   count = int(value)

   if count < 1:
      raise argparse.ArgumentTypeError("a page count is at least 1")

   return count


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
