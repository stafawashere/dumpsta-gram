"""The events command, which listens on either facade for a fixed time."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import aclosing
from dataclasses import replace
from pathlib import Path
from typing import Protocol, TextIO

from dumpstagram._cli.commands.common import Subcommands, add_request_options, resolve_session_path
from dumpstagram._cli.exits import EXIT_OK
from dumpstagram._cli.render.events import describe_event, render_event
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY, Behavior
from dumpstagram.client import SyncClient
from dumpstagram.models import (
   Event,
   EventsDropped,
   ListenerStopped,
   NewMessage,
)
from dumpstagram.session import Session

__all__ = [
   "AsyncListeningClient",
   "AsyncListeningClientFactory",
   "Listener",
   "ListeningClient",
   "ListeningClientFactory",
   "add_events_parser",
   "interval_seconds",
   "listen_async",
   "listen_async_to_the_end",
   "listen_blocking",
   "listen_blocking_to_the_end",
   "listening_behavior",
   "open_async_listening_client",
   "open_listening_client",
   "positive_seconds",
   "run_events",
]


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


def add_events_parser(commands: Subcommands) -> None:
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
