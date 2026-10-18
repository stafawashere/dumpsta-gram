"""New direct messages as they arrive, on the blocking listener or the async iterator.

Live requests: 1 inbox read per poll, plus 1 per page read back from each thread that changed.
Polls are `Behavior.poll_interval_seconds` apart, 60 s by default, and the first poll only
takes a baseline, so --seconds must pass 60 to see an event.

   uv run python docs/demo/events.py --seconds 130
   uv run python docs/demo/events.py --seconds 130 --async
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
import time

from _common import Demo, build_parser, describe_message, line, run

from dumpstagram import Event, EventsDropped, ListenerStopped, NewMessage


def describe_event(event: Event) -> str:
   if isinstance(event, NewMessage):
      return f"NewMessage in {event.message.thread_fbid}: {describe_message(event.message)}"

   if isinstance(event, EventsDropped):
      how_many = "an unknown number" if event.count is None else str(event.count)
      return f"EventsDropped, {how_many} missed, thread {event.thread_fbid or 'any'}"

   if isinstance(event, ListenerStopped):
      return f"ListenerStopped on {type(event.error).__name__}"

   return type(event).__name__


def listen_blocking(demo: Demo, seconds: float) -> int:
   demo.tour.section(
      "Blocking listener",
      "with client.events() as listener:",
      "...     listener.wait_for_events(timeout=...)",
   )

   deadline = time.monotonic() + seconds
   delivered = 0
   stopped = False

   with demo.client() as client, client.events() as listener:
      while not stopped:
         remaining = deadline - time.monotonic()

         if remaining <= 0:
            break

         for event in listener.wait_for_events(timeout=remaining):
            line(describe_event(event), depth=2)
            delivered += 1
            stopped = isinstance(event, ListenerStopped)

   return delivered


async def listen_async(demo: Demo, seconds: float) -> int:
   delivered = 0

   async with demo.async_client() as client:
      with contextlib.suppress(TimeoutError):
         async with asyncio.timeout(seconds), contextlib.aclosing(client.events()) as events:
            async for event in events:
               line(describe_event(event), depth=2)
               delivered += 1

   return delivered


def tour(demo: Demo, arguments: argparse.Namespace) -> None:
   interval = demo.behavior.poll_interval_seconds
   line(f"polling every {interval:.0f} s for {arguments.seconds:.0f} s")

   if arguments.use_async:
      demo.tour.section(
         "Async iterator",
         "async with asyncio.timeout(seconds), aclosing(client.events()) as events:",
         "...     async for event in events: ...",
      )

      delivered = asyncio.run(listen_async(demo, arguments.seconds))
   else:
      delivered = listen_blocking(demo, arguments.seconds)

   line(f"{delivered} events delivered")
   demo.report["surface"] = "async" if arguments.use_async else "blocking"
   demo.report["events_delivered"] = delivered


if __name__ == "__main__":
   parser = build_parser("Listen for new direct messages.")
   parser.add_argument("--seconds", type=float, default=130.0, help="how long to listen")
   parser.add_argument(
      "--async",
      dest="use_async",
      action="store_true",
      help="use AsyncClient.events rather than the blocking listener",
   )

   sys.exit(run("events", parser, tour))
