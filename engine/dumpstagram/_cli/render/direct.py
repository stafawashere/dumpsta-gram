"""A thread's pages, a sent message, the inbox, the message requests and the unread counts, in
both output forms."""

from __future__ import annotations

from typing import Any

from dumpstagram.models import (
   DirectThread,
   Message,
   MessageRequests,
   Page,
   SentMessage,
   UnreadCounts,
)

__all__ = [
   "describe_inbox_pages",
   "describe_message",
   "describe_message_requests",
   "describe_pages",
   "describe_sent_message",
   "describe_thread",
   "describe_unread_counts",
   "render_inbox",
   "render_message_requests",
   "render_messages",
   "render_unread_counts",
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


def describe_thread(thread: DirectThread) -> dict[str, Any]:
   return {
      "thread_fbid": thread.thread_fbid,
      "title": thread.title,
      "is_group": thread.is_group,
      "participants": [
         {
            "user_id": participant.user_id,
            "username": participant.username,
            "full_name": participant.full_name,
            "is_verified": participant.is_verified,
         }
         for participant in thread.participants
      ],
      "last_activity_at": thread.last_activity_at.isoformat(),
      "last_message_id": thread.last_message_id,
      "snippet": thread.snippet,
      "is_unread": thread.is_unread,
      "is_marked_unread": thread.is_marked_unread,
      "is_muted": thread.is_muted,
      "is_pinned": thread.is_pinned,
   }


def describe_inbox_pages(pages: list[Page[DirectThread]]) -> dict[str, Any]:
   """What was read, with the last page's own terminator and cursor, never a count of rows."""

   last = pages[-1] if pages else None

   return {
      "pages_read": len(pages),
      "thread_count": sum(len(page.items) for page in pages),
      "more_available": last.has_next_page if last is not None else False,
      "end_cursor": last.end_cursor if last is not None else None,
   }


def _thread_line(thread: DirectThread) -> str:
   markers = [
      marker
      for marker, applies in (
         ("unread", thread.is_unread),
         ("pinned", thread.is_pinned),
         ("muted", thread.is_muted),
         ("group", thread.is_group),
      )
      if applies
   ]
   flags = f"  [{', '.join(markers)}]" if markers else ""
   snippet = thread.snippet if thread.snippet is not None else ""

   return (
      f"{thread.last_activity_at.isoformat()}  {thread.thread_fbid}  {thread.title}{flags}"
      f"\n   {snippet}"
   )


def render_inbox(pages: list[Page[DirectThread]]) -> str:
   """One entry per thread in the upstream's order, newest activity first, and the trailer."""

   lines = [_thread_line(thread) for page in pages for thread in page.items]
   trailer = describe_inbox_pages(pages)
   lines.append(
      f"pages_read: {trailer['pages_read']}  threads: {trailer['thread_count']}  "
      f"more_available: {trailer['more_available']}"
   )

   if trailer["end_cursor"]:
      lines.append(f"next_cursor: {trailer['end_cursor']}")

   return "\n".join(lines)


def describe_message_requests(requests: MessageRequests) -> dict[str, Any]:
   return {
      "pending": [describe_thread(thread) for thread in requests.pending],
      "spam": [describe_thread(thread) for thread in requests.spam],
      "pending_has_more": requests.pending_has_more,
      "spam_has_more": requests.spam_has_more,
   }


def render_message_requests(requests: MessageRequests) -> str:
   lines = []

   for folder, threads, has_more in (
      ("pending", requests.pending, requests.pending_has_more),
      ("spam", requests.spam, requests.spam_has_more),
   ):
      more = "  more_available: True" if has_more else ""
      lines.append(f"{folder}: {len(threads)}{more}")
      lines.extend(_thread_line(thread) for thread in threads)

   return "\n".join(lines)


def describe_unread_counts(counts: UnreadCounts) -> dict[str, Any]:
   return {
      "inbox": counts.inbox,
      "pending": counts.pending,
      "inbox_has_more": counts.inbox_has_more,
      "pending_has_more": counts.pending_has_more,
   }


def render_unread_counts(counts: UnreadCounts) -> str:
   """The two counts, each marked when the folder has rows past the page it was taken over."""

   inbox_bound = "+" if counts.inbox_has_more else ""
   pending_bound = "+" if counts.pending_has_more else ""

   return (
      f"unread inbox: {counts.inbox}{inbox_bound}  "
      f"pending requests: {counts.pending}{pending_bound}"
   )
