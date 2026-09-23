"""What a listener delivers, one class per kind of event.

Every kind subclasses :class:`Event`, so a consumer that matches on the kinds it knows and
ignores the rest keeps working when a kind is added. That is also why ``Event`` is a class
rather than a union of the kinds: a union would be one snapshot line that changes every time a
kind arrives, where a new subclass is a new line.

The first version has one kind that comes from the upstream, :class:`NewMessage`. The other
two are the listener's own: :class:`EventsDropped` marks a gap, from a full buffer or from a
poll that could not see everything, and :class:`ListenerStopped` is the last event a blocking
listener delivers when a failure ended it.
Nothing here parses or touches the network.
"""

from __future__ import annotations

from dataclasses import dataclass

from dumpstagram.models.messages import Message

__all__ = ["Event", "EventsDropped", "ListenerStopped", "NewMessage"]


@dataclass(frozen=True)
class Event:
   """The base of every event a listener delivers. It is never delivered itself."""


@dataclass(frozen=True)
class NewMessage(Event):
   """A message the listener had not delivered before, in any thread the account can read.

   Messages the viewer sent count too, including ones sent from another device, so a consumer
   that wants only incoming messages compares :attr:`Message.sender
   <dumpstagram.models.Message.sender>` with the viewer. Within one thread these arrive in
   ascending ``sent_at``.
   """

   message: Message


@dataclass(frozen=True)
class EventsDropped(Event):
   """Messages were not delivered here, and the listener says so rather than going quiet.

   Two things leave this marker. A full buffer drops its oldest waiting events, and then
   ``count`` says how many and ``thread_fbid`` is None, because the dropped events may span
   threads. The marker stands where they stood, before every event that was kept.

   The polling transport leaves it when it cannot see everything that arrived: a thread gained
   more messages between two polls than the listener reads back, or ``since`` named a message
   the listener could not find, or more threads changed than the inbox's first page shows.
   Then ``count`` is None, because the listener cannot know how many it missed, and
   ``thread_fbid`` names the thread when the gap is in one. It comes before the messages the
   same poll delivers.

   Either way, what fell into the gap can be read back with
   :meth:`~dumpstagram.SyncClient.thread_messages`.
   """

   count: int | None
   thread_fbid: str | None = None


@dataclass(frozen=True)
class ListenerStopped(Event):
   """The listener stopped because of ``error``, and this is the last event it delivers.

   Only the blocking listener delivers this. ``error`` is the object the failed poll raised,
   never a wrapper, carrying a note that names the thread seam. A
   :class:`~dumpstagram.errors.CheckpointRequired` or an
   :class:`~dumpstagram.errors.AuthenticationFailed` ends a listener this way, and so does any
   failure the listener does not poll through. The async iterator raises the same object
   instead of delivering this.
   """

   error: Exception
