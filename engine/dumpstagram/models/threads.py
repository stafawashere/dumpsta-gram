"""Typed representations of the direct inbox: its threads, the message requests and the unread
counts.

Every field below was observed on live rows of ``PolarisDirectInboxQuery`` and
``IGDThreadListOffMsysPaginationQuery``, 15 rows each on 2026-09-24, and on the inbox cold loads
of 2026-09-23. The findings are ``direct-inbox-thread-list``,
``direct-inbox-thread-list-next-page``, ``direct-message-requests`` and
``direct-inbox-unread-thread-count`` in the local knowledge base.

Nothing here parses. Construction is done by the mapper in ``_private/web/parse/direct.py``,
which reads named keys and raises rather than filling a default, so an upstream rename is loud.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

__all__ = ["DirectThread", "MessageRequests", "ThreadParticipant", "UnreadCounts"]


@dataclass(frozen=True)
class ThreadParticipant:
   """One person in a thread other than the viewer.

   ``user_id`` is the numeric Instagram account id, the one
   :attr:`Profile.id <dumpstagram.models.Profile.id>` carries and
   :meth:`~dumpstagram.namespaces.profiles.AsyncProfiles.by_id` takes. It is not the messaging
   id a :class:`~dumpstagram.models.MessageSender` carries as ``fbid``, which is a different
   number for the same person.
   """

   user_id: str
   username: str
   full_name: str
   is_verified: bool


@dataclass(frozen=True)
class DirectThread:
   """One row of the direct inbox, or of a message requests folder.

   ``thread_fbid`` is the identifier
   :meth:`~dumpstagram.namespaces.direct.AsyncDirect.messages` takes. Listing a thread marks
   nothing, and no read in this library sends the mark read a browser sends when it opens one.

   ``participants`` are the people in the thread other than the viewer, one on a one-to-one
   thread. ``title`` is the upstream's own, the other person's name on a one-to-one thread and
   the group's name on a group.

   ``last_message_id`` and ``snippet`` come from the newest of the messages the row carries, and
   are ``None`` on a row that carries none, which has not been observed. ``snippet`` is the
   upstream's one-line preview, the text a browser shows under the title.

   ``is_unread`` is true when the thread is marked unread, or when the viewer's read receipt is
   earlier than the thread's last activity or absent. That is the engine's reading of the row, an
   INFERENCE: the browser's own rule has not been read, and an unread row has been observed only
   by that reading. ``is_marked_unread`` is the upstream's flag alone.
   """

   thread_fbid: str
   title: str
   is_group: bool
   participants: tuple[ThreadParticipant, ...]
   last_activity_at: datetime
   last_message_id: str | None
   snippet: str | None
   is_unread: bool
   is_marked_unread: bool
   is_muted: bool
   is_pinned: bool


@dataclass(frozen=True)
class MessageRequests:
   """The two message request folders, as the browser's requests view reads them in one query.

   Each folder is its first page only. ``pending_has_more`` and ``spam_has_more`` are the
   upstream's own ``has_next_page`` for each, and no query that reads further has been observed,
   so a true one says the tuple is not the whole folder.

   Listing the requests marks nothing. Opening a request thread would mark it seen to its sender,
   and nothing in this library opens one on its own.
   """

   pending: tuple[DirectThread, ...]
   spam: tuple[DirectThread, ...]
   pending_has_more: bool
   spam_has_more: bool


@dataclass(frozen=True)
class UnreadCounts:
   """How many threads are unread in the inbox and in the pending requests.

   The upstream sends rows rather than numbers, the first page of each folder that a browser's
   inbox load asks for, and the count is taken over those rows by the rule
   :attr:`DirectThread.is_unread` states. ``inbox_has_more`` and ``pending_has_more`` say the
   folder has rows past that page, which the count does not cover. Muted threads are counted.
   """

   inbox: int
   pending: int
   inbox_has_more: bool
   pending_has_more: bool
