"""A thread's pages and a sent message, in both output forms."""

from __future__ import annotations

from typing import Any

from dumpstagram.models import (
   Message,
   Page,
   SentMessage,
)

__all__ = [
   "describe_message",
   "describe_pages",
   "describe_sent_message",
   "render_messages",
]


def describe_message(message: Message) -> dict[str, Any]:
   return {
      "id": message.id,
      "thread_fbid": message.thread_fbid,
      "sender_fbid": message.sender.fbid,
      "sender_igid": message.sender.igid,
      "sender_name": message.sender.name,
      "sent_at": message.sent_at.isoformat(),
      "text": message.text,
      "content_type": message.content_type,
      "reactions": [
         {"emoji": reaction.emoji, "sender_fbid": reaction.sender_fbid}
         for reaction in message.reactions
      ],
      "replied_to_message_id": message.replied_to_message_id,
      "is_forwarded": message.is_forwarded,
      "is_pinned": message.is_pinned,
      "is_ai_generated": message.is_ai_generated,
      "offline_threading_id": message.offline_threading_id,
   }


def describe_sent_message(sent: SentMessage) -> dict[str, Any]:
   """The JSON form of what a send answered. ``offline_threading_id`` is the one the send
   carried, and ``dumpsta thread`` prints the same value on the message it created."""

   return {
      "id": sent.id,
      "thread_fbid": sent.thread_fbid,
      "sent_at": sent.sent_at.isoformat(),
      "offline_threading_id": sent.offline_threading_id,
   }


def describe_pages(pages: list[Page[Message]]) -> dict[str, Any]:
   """What was read, including the terminator, which is the only thing that says there is more.

   ``more_available`` comes from the last page's own `has_next_page`, never from the number of
   messages that arrived. A short page is not the end of a thread.
   """

   last = pages[-1] if pages else None

   return {
      "pages_read": len(pages),
      "message_count": sum(len(page.items) for page in pages),
      "more_available": last.has_next_page if last is not None else False,
      "end_cursor": last.end_cursor if last is not None else None,
   }


def render_messages(pages: list[Page[Message]]) -> str:
   """The human form: one line per message, oldest first as the upstream ordered them.

   The order is the upstream's. Nothing here sorts, because a client that reorders a thread
   invents a chronology the server did not state.
   """

   lines = []

   for page in pages:
      for message in page.items:
         text = message.text if message.text is not None else f"<{message.content_type}>"
         lines.append(f"{message.sent_at.isoformat()}  {message.sender.fbid}  {text}")

   trailer = describe_pages(pages)
   lines.append(
      f"pages_read: {trailer['pages_read']}  messages: {trailer['message_count']}  "
      f"more_available: {trailer['more_available']}"
   )

   if trailer["end_cursor"]:
      lines.append(f"next_cursor: {trailer['end_cursor']}")

   return "\n".join(lines)
