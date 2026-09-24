"""One listener event per line, in both output forms."""

from __future__ import annotations

from typing import Any

from dumpstagram._cli.render.direct import describe_message
from dumpstagram.models import (
   Event,
   EventsDropped,
   NewMessage,
)

__all__ = [
   "describe_event",
   "render_event",
]


def describe_event(event: Event, *, ids_only: bool) -> dict[str, Any]:
   """The JSON form of one listener event, one object per line of output.

   ``ids_only`` keeps a message's identifiers and time and drops its text, its sender's name
   and its reactions, for a run whose output lands in a log.
   """

   if isinstance(event, NewMessage):
      message = event.message

      if not ids_only:
         return {"event": "new_message", "message": describe_message(message)}

      return {
         "event": "new_message",
         "message": {
            "id": message.id,
            "thread_fbid": message.thread_fbid,
            "sender_fbid": message.sender.fbid,
            "sent_at": message.sent_at.isoformat(),
            "content_type": message.content_type,
         },
      }

   if isinstance(event, EventsDropped):
      return {"event": "events_dropped", "count": event.count, "thread_fbid": event.thread_fbid}

   return {"event": type(event).__name__}


def render_event(event: Event, *, ids_only: bool) -> str:
   """The human form of one listener event, one line."""

   if isinstance(event, NewMessage):
      message = event.message
      line = (
         f"new_message  {message.sent_at.isoformat()}  {message.thread_fbid}  "
         f"{message.sender.fbid}  {message.id}"
      )

      if ids_only:
         return line

      text = message.text if message.text is not None else f"<{message.content_type}>"

      return f"{line}  {text}"

   if isinstance(event, EventsDropped):
      count = "unknown" if event.count is None else str(event.count)
      thread = event.thread_fbid or "any"

      return f"events_dropped  count: {count}  thread: {thread}"

   return type(event).__name__
