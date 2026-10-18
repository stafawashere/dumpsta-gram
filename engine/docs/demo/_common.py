"""What every demo script shares: the session, the output helpers, the log and the error exits.

Nothing here reaches past the public `dumpstagram` names, so the scripts beside it stay worked
usage of the surface a consumer gets.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dumpstagram import (
   PARITY,
   AsyncClient,
   AuthenticationFailed,
   Behavior,
   CheckpointRequired,
   DumpstagramError,
   FeedFirstPage,
   Message,
   NotFound,
   OperationCancelled,
   OutcomeUnknown,
   Page,
   Profile,
   ProfileRoute,
   RateLimited,
   SchemaChanged,
   Session,
   SyncClient,
   ThreadFirstPage,
   TransportFailure,
   UpstreamRejected,
)

ENGINE_ROOT = Path(__file__).resolve().parents[2]
SESSION_PATH = ENGINE_ROOT / "state" / "session.json"
ENV_PATH = ENGINE_ROOT.parent / ".env"
LOG_DIR = ENGINE_ROOT / "logs"

PREVIEW_LENGTH = 44
SHOWN_ITEMS = 5
INDENT = "   "

DEFAULT_WRITE_TEXT = "dumpsta demo"

QUICK = dataclasses.replace(
   PARITY,
   feed_first_page=FeedFirstPage.QUERY,
   profile_route=ProfileRoute.QUERIES,
   thread_first_page=ThreadFirstPage.QUERY,
   page_load_companions=False,
)
"""Parity timing without the page loads, which is how a derived preset is built."""

EXIT_CODES: dict[type[DumpstagramError], int] = {
   DumpstagramError: 1,
   AuthenticationFailed: 3,
   CheckpointRequired: 4,
   RateLimited: 5,
   UpstreamRejected: 6,
   NotFound: 7,
   SchemaChanged: 8,
   TransportFailure: 9,
   OperationCancelled: 10,
   OutcomeUnknown: 11,
}
"""The same numbers the `dumpsta` command exits with."""


class Tour:
   def __init__(self) -> None:
      self.section_number = 0

   def section(self, title: str, *calls: str) -> None:
      self.section_number += 1

      print()
      print(f"{self.section_number}. {title}")

      for call in calls:
         show_call(call)


@dataclass
class Demo:
   tour: Tour
   env: dict[str, str]
   session: Session
   session_call: str
   user_agent: str | None
   behavior: Behavior
   report: dict[str, object] = field(default_factory=dict)

   def client(self, behavior: Behavior | None = None) -> SyncClient:
      return SyncClient(
         self.session,
         user_agent=self.user_agent,
         behavior=behavior or self.behavior,
      )

   def async_client(self, behavior: Behavior | None = None) -> AsyncClient:
      return AsyncClient(
         self.session,
         user_agent=self.user_agent,
         behavior=behavior or self.behavior,
      )

   def write_text(self, env_key: str) -> str:
      return self.env.get(env_key) or DEFAULT_WRITE_TEXT


def show_call(call: str) -> None:
   is_continuation = call.startswith("...")
   prompt = "" if is_continuation else ">>> "

   print(f"{INDENT}{prompt}{call}")


def line(text: str = "", depth: int = 1) -> None:
   print(f"{INDENT * depth}{text}".rstrip())


def preview(text: str | None) -> str:
   if not text:
      return ""

   single_line = " ".join(text.split())
   is_too_long = len(single_line) > PREVIEW_LENGTH

   if is_too_long:
      single_line = single_line[: PREVIEW_LENGTH - 3] + "..."

   return f'"{single_line}"'


def yes_no(flag: bool | None) -> str:
   if flag is None:
      return "unknown"

   return "yes" if flag else "no"


def show_profile(profile: Profile) -> None:
   visibility = "private" if profile.is_private else "public"
   verified = ", verified" if profile.is_verified else ""

   line(f"@{profile.username}  {profile.full_name}  ({visibility}{verified})")
   line(
      f"{profile.media_count:,} posts  "
      f"{profile.follower_count:,} followers  "
      f"{profile.following_count:,} following  "
      f"{profile.total_clips_count:,} reels"
   )

   if profile.bio_links:
      first_link = profile.bio_links[0]
      label = preview(first_link.title) or f"untitled, a {first_link.link_type} link"

      line(f"{len(profile.bio_links)} bio links, first {label}")

   relationship = profile.friendship_status

   if relationship is None:
      line("friendship_status is None, which is the viewer's own profile")
      return

   line(
      f"following {yes_no(relationship.following)}, "
      f"followed by {yes_no(relationship.followed_by)}, "
      f"request pending {yes_no(relationship.outgoing_request)}"
   )


def describe_message(message: Message) -> str:
   sender = message.sender.name or message.sender.fbid
   stamp = message.sent_at.strftime("%m-%d %H:%M")
   body = preview(message.text) or f"<{message.content_type}>"
   reactions = "".join(reaction.emoji for reaction in message.reactions)
   suffix = f"  {reactions}" if reactions else ""

   return f"{stamp}  {sender}: {body}{suffix}"


def show_thread_page(page: Page[Message]) -> None:
   line(f"Page[Message], {len(page.items)} messages, has_next_page={page.has_next_page}")

   for message in page.items[:SHOWN_ITEMS]:
      line(describe_message(message), depth=2)

   hidden_count = len(page.items) - SHOWN_ITEMS

   if hidden_count > 0:
      line(f"... {hidden_count} more", depth=2)


def read_env_file(path: Path) -> dict[str, str]:
   values: dict[str, str] = {}

   for raw_line in path.read_text(encoding="utf-8").splitlines():
      stripped = raw_line.strip()

      is_comment = stripped.startswith("#")
      has_assignment = "=" in stripped

      if stripped and not is_comment and has_assignment:
         key, _, value = stripped.partition("=")
         values[key.strip()] = value.strip().strip('"').strip("'")

   return values


def load_session(env: dict[str, str]) -> tuple[Session, str]:
   if SESSION_PATH.exists():
      return Session.load(SESSION_PATH), 'session = Session.load("state/session.json")'

   extra_cookies = {"mid": env["IG_MID"]} if env.get("IG_MID") else {}

   session = Session(
      sessionid=env["IG_SESSIONID"],
      ds_user_id=env["IG_DS_USER_ID"],
      csrftoken=env["IG_CSRFTOKEN"],
      extra_cookies=extra_cookies,
   )

   return session, "session = Session(sessionid=..., ds_user_id=..., csrftoken=...)"


def build_parser(description: str) -> argparse.ArgumentParser:
   parser = argparse.ArgumentParser(description=description)

   parser.add_argument(
      "--quick",
      action="store_true",
      help="skip the page loads a browser would make, fewer requests and no longer parity",
   )

   return parser


def exit_code_for(failure: DumpstagramError) -> int:
   for ancestor in type(failure).__mro__:
      if ancestor in EXIT_CODES:
         return EXIT_CODES[ancestor]

   return 1


def explain_failure(failure: DumpstagramError) -> None:
   print()

   if isinstance(failure, CheckpointRequired):
      line(f"CheckpointRequired, clear it in a browser first ({failure.required_action})")
   elif isinstance(failure, RateLimited):
      line(f"RateLimited, the pacer holds the account for {failure.retry_after} s")
   elif isinstance(failure, OutcomeUnknown):
      line(f"OutcomeUnknown on {failure.operation}, read the state back before sending it again")
   elif isinstance(failure, UpstreamRejected):
      line(f"UpstreamRejected with code {failure.code}")
   else:
      line(f"{type(failure).__name__}: {failure}")


def write_log(name: str, report: dict[str, object]) -> Path:
   LOG_DIR.mkdir(parents=True, exist_ok=True)
   stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
   path = LOG_DIR / f"demo-{name}-{stamp}.json"

   path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")

   return path


def run(
   name: str,
   parser: argparse.ArgumentParser,
   body: Callable[[Demo, argparse.Namespace], None],
   *,
   saves_session: bool = True,
) -> int:
   """Run one demo script: parse, load the session, call ``body``, save and log either way.

   The log holds the counts ``body`` put in ``demo.report`` and nothing a person wrote.
   """

   arguments = parser.parse_args()
   env = read_env_file(ENV_PATH) if ENV_PATH.exists() else {}
   behavior = QUICK if arguments.quick else PARITY
   mode = "quick" if arguments.quick else "parity"

   print(f"Dumpsta-Engine demo: {name} ({mode})")

   session, session_call = load_session(env)

   demo = Demo(
      tour=Tour(),
      env=env,
      session=session,
      session_call=session_call,
      user_agent=env.get("IG_USER_AGENT") or None,
      behavior=behavior,
      report={"demo": name, "mode": mode},
   )

   started = time.monotonic()
   exit_code = 0

   try:
      body(demo, arguments)
   except DumpstagramError as failure:
      explain_failure(failure)
      demo.report["failure"] = type(failure).__name__
      exit_code = exit_code_for(failure)
   finally:
      if saves_session:
         session.save(SESSION_PATH)

   elapsed_seconds = time.monotonic() - started
   demo.report["elapsed_ms"] = round(elapsed_seconds * 1000)
   log_path = write_log(name, demo.report)

   print()
   print(f"Done in {elapsed_seconds:.1f} s. Log: {log_path.relative_to(ENGINE_ROOT)}")

   return exit_code
