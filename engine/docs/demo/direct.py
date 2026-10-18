"""Direct: the notes tray, and with --thread one thread by page and by message.

Live requests: 1 for the notes tray. With --thread, 1 per page for the first two pages, the
newest read the way a browser opens a thread, plus 1 when the iterator reads a third.

   uv run python docs/demo/direct.py
   uv run python docs/demo/direct.py --thread FBID --limit 20
"""

from __future__ import annotations

import argparse
import sys

from _common import (
   SHOWN_ITEMS,
   Demo,
   build_parser,
   describe_message,
   line,
   preview,
   run,
   show_call,
   show_thread_page,
)

from dumpstagram import SyncClient


def show_notes(demo: Demo, client: SyncClient) -> None:
   demo.tour.section("Notes tray", "client.direct.notes()")

   notes = client.direct.notes()
   line(f"tuple[Note, ...], {len(notes)} notes")

   for note in notes[:SHOWN_ITEMS]:
      author = note.author_username or note.author_id
      line(f"@{author:<18} {preview(note.text)}  ({note.audience.name})", depth=2)

   demo.report["notes"] = len(notes)


def show_thread(demo: Demo, client: SyncClient, thread_fbid: str, limit: int) -> None:
   demo.tour.section("Direct thread", f'page = client.direct.messages("{thread_fbid}")')

   newest_page = client.direct.messages(thread_fbid)
   show_thread_page(newest_page)
   demo.report["thread_page_one_messages"] = len(newest_page.items)

   if not newest_page.has_next_page:
      return

   print()
   show_call(f'page = client.thread_messages("{thread_fbid}", after=page.end_cursor)')

   older_page = client.thread_messages(thread_fbid, after=newest_page.end_cursor)
   show_thread_page(older_page)
   demo.report["thread_page_two_messages"] = len(older_page.items)

   if not older_page.has_next_page:
      return

   demo.tour.section(
      "Message iterator",
      f'client.direct.iter_messages("{thread_fbid}", limit={limit}, after=page.end_cursor)',
   )

   walk = client.direct.iter_messages(thread_fbid, limit=limit, after=older_page.end_cursor)
   walked = 0

   for message in walk:
      walked += 1

      if walked <= SHOWN_ITEMS:
         line(describe_message(message), depth=2)

   line(f"{walked} messages walked")
   demo.report["thread_iterated_messages"] = walked


def tour(demo: Demo, arguments: argparse.Namespace) -> None:
   with demo.client() as client:
      show_notes(demo, client)

      if arguments.thread:
         show_thread(demo, client, arguments.thread, arguments.limit)


if __name__ == "__main__":
   parser = build_parser("Read the notes tray and a direct thread.")
   parser.add_argument("--thread", metavar="FBID", help="also read this thread")
   parser.add_argument("--limit", type=int, default=5, help="messages the iterator walks")

   sys.exit(run("direct", parser, tour))
