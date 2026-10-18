"""Send a direct message, find it in the thread, and unsend it. Writes.

Live requests: 4, the send, one thread page to find the message by its `offline_threading_id`,
and the unsend, which opens the thread first. The text comes from `IG_DM_TEXT` in `.env`.

   uv run python docs/demo/message_cycle.py FBID
"""

from __future__ import annotations

import argparse
import sys

from _common import Demo, build_parser, line, preview, run


def tour(demo: Demo, arguments: argparse.Namespace) -> None:
   thread_fbid = arguments.thread
   text = demo.write_text("IG_DM_TEXT")

   demo.tour.section(
      "Direct message cycle",
      f'sent = client.direct.send("{thread_fbid}", {preview(text)})',
      f'client.direct.messages("{thread_fbid}")',
      f'client.direct.unsend("{thread_fbid}", sent.id)',
   )

   with demo.client() as client:
      sent = client.direct.send(thread_fbid, text)
      line(f"SentMessage {sent.id} at {sent.sent_at:%H:%M:%S}")

      newest_page = client.direct.messages(thread_fbid)
      found = any(
         message.offline_threading_id == sent.offline_threading_id for message in newest_page
      )
      line(f"found in the thread by offline_threading_id: {found}")

      client.direct.unsend(thread_fbid, sent.id)
      line("unsent")
      demo.report["message_cycle"] = True
      demo.report["found_by_offline_threading_id"] = found


if __name__ == "__main__":
   parser = build_parser("Send a direct message, then unsend it.")
   parser.add_argument("thread", metavar="FBID", help="the thread to send into")

   sys.exit(run("message-cycle", parser, tour))
