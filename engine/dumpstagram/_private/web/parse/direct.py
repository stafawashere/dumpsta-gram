"""Map a direct payload: a thread's messages, the inbox listing and its public pages, the message
requests, a folder's unread rows, and a send and unsend answer.

What the upstream sends and this module drops, from the twenty-node capture on 2026-09-21 in
`engine/logs/message-node-shape-2026-09-21-022957.json`:

- ``message_id``, equal to ``id`` on all twenty nodes, so it is a second name rather than a
  second identifier.
- ``msg_reactions``, non-empty on exactly the message ``reactions`` was non-empty on, and
  carrying ``sender_igid`` instead of the emoji. ``reactions`` is the one with the emoji.
- ``content``, whose ``text_body`` duplicates the node's own ``text_body``.
- ``bot_response_id``, ``expiration_timestamp_ms``, ``igd_wearables_attribution_text``,
  ``igd_wearables_attribution_type``, ``is_tombstone_revealable``, ``tombstone_reason`` and
  ``view_expiration_timestamp_ms``, all null on all twenty nodes, so there is nothing measured
  to model.
- ``is_reported``, ``mentions``, ``offline_threading_id``, ``replied_to_message`` and
  ``slide_edit_history``, which are real but belong to capabilities that do not exist yet.
- the per-edge ``cursor``, because pagination terminates on ``page_info`` and a caller that
  holds a mid-page cursor has a way to resume nothing else offers.

Finding: `skills/reverse-engineer/knowledge/endpoints/direct-thread-message-page.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from dumpstagram._private.web.parse.common import (
   MILLISECONDS_PER_SECOND,
   _object_at,
   _optional_string,
   _required,
   _required_flag,
   _required_string,
)
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import (
   DirectThread,
   Message,
   MessageRequests,
   MessageSender,
   Page,
   Reaction,
   SentMessage,
   ThreadParticipant,
)

__all__ = [
   "DIRECT_TEXT_SEND_ROOT",
   "DIRECT_UNSEND_ROOT",
   "INBOX_LISTING_PATH",
   "INBOX_MAILBOX_PATH",
   "INBOX_NEXT_PAGE_MAILBOX_PATH",
   "PENDING_REQUESTS_PATH",
   "SPAM_REQUESTS_PATH",
   "THREAD_DETAIL_PATH",
   "THREAD_DETAIL_THREAD_PATH",
   "THREAD_PAGE_PATH",
   "FolderUnreadRows",
   "InboxMessage",
   "InboxPage",
   "InboxThread",
   "parse_direct_text_send_answer",
   "parse_direct_unsend_answer",
   "parse_folder_unread_rows",
   "parse_inbox_continuation",
   "parse_inbox_listing",
   "parse_inbox_next_page",
   "parse_inbox_page",
   "parse_message_requests",
   "parse_inbox_recent_messages",
   "parse_thread_detail",
   "parse_thread_id",
   "parse_thread_message_page",
]

THREAD_PAGE_PATH = ("data", "fetch__SlideThread", "as_ig_direct_thread", "slide_messages")
"""The canonical path to the message connection, unchanged across both measured days."""

THREAD_DETAIL_PATH = (
   "data",
   "get_slide_thread_nullable",
   "as_ig_direct_thread",
   "slide_messages",
)
"""The same message connection in an ``IGDThreadDetailQuery`` payload, under its own root."""

INBOX_LISTING_PATH = ("data", "get_slide_mailbox_for_iris_subscription", "threads_by_folder")
"""The path to the thread connection in a ``PolarisDirectInboxQuery`` payload."""

DIRECT_TEXT_SEND_ROOT = "xig_direct_text_send_with_slide_messaging_response"
"""The root field a text send answers under, with ``message_id``, ``id`` and ``timestamp_ms``."""

DIRECT_UNSEND_ROOT = "direct_unsend_message"
"""The root field an unsend answers under, a boolean, true on both observed unsends."""

THREAD_DETAIL_THREAD_PATH = ("data", "get_slide_thread_nullable", "as_ig_direct_thread")


def _sent_at(node: dict[str, Any], path: str) -> datetime:
   """Convert ``timestamp_ms`` to timezone-aware UTC.

   The upstream sends it as a string of milliseconds since the Unix epoch, thirteen digits on
   every measured node. It is accepted as an integer too, because a JSON number is the shape
   the same value would most plausibly change into, and refusing that would be a break with no
   safety behind it. Anything else raises rather than being coerced.
   """

   raw = _required(node, "timestamp_ms", path)

   if isinstance(raw, bool) or not isinstance(raw, (str, int)):
      raise SchemaChanged(
         f"{path}.timestamp_ms is neither a string nor an integer", path=f"{path}.timestamp_ms"
      )

   try:
      milliseconds = int(raw)
   except ValueError as failure:
      raise SchemaChanged(
         f"{path}.timestamp_ms does not hold an integer", path=f"{path}.timestamp_ms"
      ) from failure

   return datetime.fromtimestamp(milliseconds / MILLISECONDS_PER_SECOND, tz=UTC)


def _sender(node: dict[str, Any], path: str) -> MessageSender:
   """Build the sender from ``sender_fbid``, enriched by the sender object when it resolves.

   ``sender_fbid`` is required because it is present on every node. The nested object is
   optional because a sender that no longer resolves is a state the upstream can be in, and
   losing the display name is not a reason to fail a whole page.
   """

   fbid = _required_string(node, "sender_fbid", path)
   details = node.get("sender")

   if not isinstance(details, dict):
      return MessageSender(fbid=fbid)

   igid = details.get("igid")
   name = details.get("name")

   return MessageSender(
      fbid=fbid,
      igid=igid if isinstance(igid, str) else None,
      name=name if isinstance(name, str) else None,
   )


def _reactions(node: dict[str, Any], path: str) -> tuple[Reaction, ...]:
   raw = _required(node, "reactions", path)

   if raw is None:
      return ()

   if not isinstance(raw, list):
      raise SchemaChanged(f"{path}.reactions is not a list", path=f"{path}.reactions")

   built: list[Reaction] = []

   for index, entry in enumerate(raw):
      entry_path = f"{path}.reactions[{index}]"

      built.append(
         Reaction(
            emoji=_required_string(entry, "reaction", entry_path),
            sender_fbid=_required_string(entry, "sender_fbid", entry_path),
         )
      )

   return tuple(built)


def parse_message(node: Any, path: str) -> Message:
   """One message node, mapped field by field."""

   if not isinstance(node, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

   return Message(
      id=_required_string(node, "id", path),
      thread_fbid=_required_string(node, "thread_fbid", path),
      sender=_sender(node, path),
      sent_at=_sent_at(node, path),
      text=_optional_string(node, "text_body", path),
      content_type=_required_string(node, "content_type", path),
      reactions=_reactions(node, path),
      replied_to_message_id=_optional_string(node, "replied_to_message_id", path),
      is_forwarded=_required_flag(node, "igd_is_forwarded", path),
      is_pinned=_required_flag(node, "is_pinned", path),
      is_ai_generated=_required_flag(node, "is_ai_generated", path),
      offline_threading_id=_offline_threading_id(node, path),
   )


def _offline_threading_id(node: dict[str, Any], path: str) -> str | None:
   """The client identifier the sending client generated, which every live node carried.

   Absent reads as ``None`` rather than raising, because the pages recorded before this field
   was mapped do not carry it. Present, it must be a string or null.
   """

   if "offline_threading_id" not in node:
      return None

   return _optional_string(node, "offline_threading_id", path)


def parse_thread_message_page(payload: Any) -> Page[Message]:
   """One page of the pagination query, mapped into typed messages.

   ``useIGDMessageListPaginationQuery`` and ``IGDMessageListOffMsysQuery`` answer with the same
   root field, so this maps both.

   Edges keep the order the upstream sent them in. Nothing is sorted here, because a
   normalisation applied at the boundary is a normalisation a recorded oracle has to know
   about, and reordering hides whether the upstream order ever changes.

   Two shapes are deliberately not special cased, because neither has been observed and a
   mapper that invents a meaning for an unmeasured shape is guessing in the one place this
   package exists to stop guessing.

   A thread field resolving to null is one of them. It stops the walk like any other
   unreachable path and raises :class:`~dumpstagram.errors.SchemaChanged` naming where it
   stopped. What was measured is that the two thread identifiers which are not the ``fbid``
   answer with nothing; the null shape of that answer was not, so it is reported as a payload
   this mapper cannot map rather than as a thread that does not exist.

   A page claiming a successor while carrying no cursor is the other. It is returned exactly
   as it arrived, with ``has_next_page`` true and ``end_cursor`` ``None``, and the caller sees
   the contradiction the upstream sent.
   """

   return _message_page(payload, THREAD_PAGE_PATH)


def parse_thread_detail(payload: Any) -> Page[Message]:
   """One ``IGDThreadDetailQuery`` payload, mapped into the thread's newest page.

   The thread object around the connection also carries its title, members, read receipts and
   pinned messages. None of that is mapped yet, because no public model holds it.

   A null ``get_slide_thread_nullable`` raises :class:`~dumpstagram.errors.SchemaChanged` for
   the reason :func:`parse_thread_message_page` gives: the name says null is possible, and no
   null answer has been observed, so nothing here claims to know what one means.
   """

   return _message_page(payload, THREAD_DETAIL_PATH)


def _message_page(payload: Any, path: tuple[str, ...]) -> Page[Message]:
   connection = _object_at(payload, path)
   connection_path = ".".join(path)

   edges = _required(connection, "edges", connection_path)

   if not isinstance(edges, list):
      raise SchemaChanged(f"{connection_path}.edges is not a list", path=f"{connection_path}.edges")

   messages = tuple(
      parse_message(
         _required(edge, "node", f"{connection_path}.edges[{index}]"),
         f"{connection_path}.edges[{index}].node",
      )
      for index, edge in enumerate(edges)
   )

   page_info_path = f"{connection_path}.page_info"
   page_info = _required(connection, "page_info", connection_path)

   if not isinstance(page_info, dict):
      raise SchemaChanged(f"{page_info_path} is not an object", path=page_info_path)

   has_next_page = _required_flag(page_info, "has_next_page", page_info_path)
   end_cursor = _optional_string(page_info, "end_cursor", page_info_path)

   return Page(items=messages, has_next_page=has_next_page, end_cursor=end_cursor)


@dataclass(frozen=True)
class InboxThread:
   """One row of the inbox listing, reduced to what tells a poll whether the thread moved.

   Private on purpose. The listener reads it and nothing public returns it, so its fields can
   follow the upstream without a snapshot line changing.

   ``thread_fbid`` is the identifier ``thread_messages`` takes, and equals the row's own ``id``
   on every measured row. ``thread_key`` is what a browser sends as the ``thread_fbid`` variable
   when it opens the thread, and differs from ``thread_fbid`` on one-to-one threads.
   """

   thread_fbid: str
   thread_key: str
   last_activity_ms: int
   last_message_id: str | None
   is_pinned: bool


def _milliseconds(node: dict[str, Any], key: str, path: str) -> int:
   raw = _required(node, key, path)
   is_a_digit_string = isinstance(raw, str) and raw.isdigit()

   if not is_a_digit_string:
      raise SchemaChanged(f"{path}.{key} is not a string of digits", path=f"{path}.{key}")

   return int(raw)


def _newest_message_id(thread: dict[str, Any], path: str) -> str | None:
   """The id of the first message edge, which is the newest.

   Every one of the fifteen rows of the capture of 2026-09-23 listed its messages newest first,
   and on every one the first message's ``timestamp_ms`` equalled the row's
   ``last_activity_timestamp_ms``. A thread with no message edges has no newest message.
   """

   messages_path = f"{path}.slide_messages"
   messages = _required(thread, "slide_messages", path)
   edges = _required(messages, "edges", messages_path)

   if not isinstance(edges, list):
      raise SchemaChanged(f"{messages_path}.edges is not a list", path=f"{messages_path}.edges")

   if not edges:
      return None

   node = _required(edges[0], "node", f"{messages_path}.edges[0]")

   return _required_string(node, "id", f"{messages_path}.edges[0].node")


def _inbox_thread(edge: Any, path: str) -> InboxThread:
   node = _required(edge, "node", path)
   thread_path = f"{path}.node.as_ig_direct_thread"
   thread = _required(node, "as_ig_direct_thread", f"{path}.node")

   if not isinstance(thread, dict):
      raise SchemaChanged(f"{thread_path} is not an object", path=thread_path)

   return InboxThread(
      thread_fbid=_required_string(thread, "thread_fbid", thread_path),
      thread_key=_required_string(thread, "thread_key", thread_path),
      last_activity_ms=_milliseconds(thread, "last_activity_timestamp_ms", thread_path),
      last_message_id=_newest_message_id(thread, thread_path),
      is_pinned=_required_flag(thread, "is_pin", thread_path),
   )


def parse_inbox_listing(payload: Any) -> Page[InboxThread]:
   """One ``PolarisDirectInboxQuery`` payload, mapped into its rows in the listing's order.

   The order is the upstream's and is kept as sent: newest activity first on every measured
   read, with pinned threads at their activity position rather than hoisted. The separate
   ``pinned_threads_v2`` list repeats rows already in the connection and is not read.

   Finding: `direct-inbox-thread-list` in the knowledge base.
   """

   connection = _object_at(payload, INBOX_LISTING_PATH)
   connection_path = ".".join(INBOX_LISTING_PATH)

   edges = _required(connection, "edges", connection_path)

   if not isinstance(edges, list):
      raise SchemaChanged(f"{connection_path}.edges is not a list", path=f"{connection_path}.edges")

   threads = tuple(
      _inbox_thread(edge, f"{connection_path}.edges[{index}]") for index, edge in enumerate(edges)
   )

   page_info_path = f"{connection_path}.page_info"
   page_info = _required(connection, "page_info", connection_path)

   if not isinstance(page_info, dict):
      raise SchemaChanged(f"{page_info_path} is not an object", path=page_info_path)

   has_next_page = _required_flag(page_info, "has_next_page", page_info_path)
   end_cursor = _optional_string(page_info, "end_cursor", page_info_path)

   return Page(items=threads, has_next_page=has_next_page, end_cursor=end_cursor)


@dataclass(frozen=True)
class InboxMessage:
   """One of the newest messages an inbox row carries, reduced to its id and its time.

   Private, like :class:`InboxThread`. A row's message nodes carry ten keys and lack the
   sender object, the reactions, ``thread_fbid`` and the three flags a
   :class:`~dumpstagram.models.Message` holds, so they are never mapped into one. The listener
   uses them to place a message id in time and reads the messages themselves from the thread.
   """

   id: str
   sent_at_ms: int


def _inbox_messages(edge: Any, path: str) -> tuple[InboxMessage, ...]:
   thread_path = f"{path}.node.as_ig_direct_thread"
   thread = _required(_required(edge, "node", path), "as_ig_direct_thread", f"{path}.node")
   messages_path = f"{thread_path}.slide_messages"
   edges = _required(_required(thread, "slide_messages", thread_path), "edges", messages_path)

   if not isinstance(edges, list):
      raise SchemaChanged(f"{messages_path}.edges is not a list", path=f"{messages_path}.edges")

   carried: list[InboxMessage] = []

   for index, message_edge in enumerate(edges):
      node_path = f"{messages_path}.edges[{index}].node"
      node = _required(message_edge, "node", f"{messages_path}.edges[{index}]")

      if not isinstance(node, dict):
         raise SchemaChanged(f"{node_path} is not an object", path=node_path)

      carried.append(
         InboxMessage(
            id=_required_string(node, "id", node_path),
            sent_at_ms=_milliseconds(node, "timestamp_ms", node_path),
         )
      )

   return tuple(carried)


def parse_inbox_recent_messages(payload: Any) -> tuple[tuple[InboxMessage, ...], ...]:
   """The messages each row of one ``PolarisDirectInboxQuery`` payload carries, row by row.

   One tuple per row, in the same order :func:`parse_inbox_listing` returns the rows, and each
   tuple in the order the row lists its messages, which was newest first on all 75 measured
   nodes. Five per row, set by the request's provider flag.

   Finding: `direct-inbox-thread-list` in the knowledge base.
   """

   connection = _object_at(payload, INBOX_LISTING_PATH)
   connection_path = ".".join(INBOX_LISTING_PATH)
   edges = _required(connection, "edges", connection_path)

   if not isinstance(edges, list):
      raise SchemaChanged(f"{connection_path}.edges is not a list", path=f"{connection_path}.edges")

   return tuple(
      _inbox_messages(edge, f"{connection_path}.edges[{index}]") for index, edge in enumerate(edges)
   )


def parse_direct_text_send_answer(payload: Any, thread_fbid: str, threading_id: str) -> SentMessage:
   """What a text send answered, under ``data.xig_direct_text_send_with_slide_messaging_response``.

   Both observed answers carried ``message_id`` and ``id`` holding the same ``mid.$`` string and
   ``timestamp_ms`` as a thirteen-digit string, 310 bytes, no ``errors`` array. An ``id`` that
   differs from ``message_id`` would mean two identifiers where one was measured, so it raises.
   """

   root_path = f"data.{DIRECT_TEXT_SEND_ROOT}"
   root = _object_at(payload, ("data", DIRECT_TEXT_SEND_ROOT))

   message_id = _required_string(root, "message_id", root_path)
   echoed_id = _required_string(root, "id", root_path)
   ids_disagree = echoed_id != message_id

   if ids_disagree:
      raise SchemaChanged(f"{root_path}.id differs from its message_id", path=f"{root_path}.id")

   return SentMessage(
      id=message_id,
      thread_fbid=thread_fbid,
      sent_at=_sent_at(root, root_path),
      offline_threading_id=threading_id,
   )


def parse_direct_unsend_answer(payload: Any) -> bool:
   """Whether an unsend applied, from ``data.direct_unsend_message``, true on both observed."""

   data = _object_at(payload, ("data",))
   answer = _required(data, DIRECT_UNSEND_ROOT, "data")

   if not isinstance(answer, bool):
      raise SchemaChanged(
         f"data.{DIRECT_UNSEND_ROOT} is not a boolean", path=f"data.{DIRECT_UNSEND_ROOT}"
      )

   return answer


def parse_thread_id(payload: Any) -> str:
   """The thread's 39-digit ``thread_id`` from an ``IGDThreadDetailQuery`` payload.

   The unsend takes this id and none other, and the message nodes do not carry it. The thread
   open does, beside ``thread_fbid`` and ``thread_key``.
   """

   thread = _object_at(payload, THREAD_DETAIL_THREAD_PATH)

   return _required_string(thread, "thread_id", ".".join(THREAD_DETAIL_THREAD_PATH))


INBOX_MAILBOX_PATH = ("data", "get_slide_mailbox_for_iris_subscription")
"""The mailbox root of the inbox's first page and of a folder's unread rows."""

INBOX_NEXT_PAGE_MAILBOX_PATH = ("data", "fetch__SlideMailbox")
"""The mailbox root of every inbox page after the first."""

PENDING_REQUESTS_PATH = ("data", "pendingMailbox")

SPAM_REQUESTS_PATH = ("data", "spamMailbox")


@dataclass(frozen=True)
class InboxPage:
   """One inbox page and the id of the mailbox it came from, which the next page is keyed on."""

   page: Page[DirectThread]
   mailbox_id: str


@dataclass(frozen=True)
class FolderUnreadRows:
   """How many of one folder's rows are unread, and whether the folder has rows past them."""

   unread: int
   has_more: bool


def _receipt_watermarks(thread: dict[str, Any], participant_fbid: str, path: str) -> list[int]:
   receipts_path = f"{path}.slide_read_receipts"
   receipts = _required(thread, "slide_read_receipts", path)

   if not isinstance(receipts, list):
      raise SchemaChanged(f"{receipts_path} is not a list", path=receipts_path)

   watermarks: list[int] = []

   for index, receipt in enumerate(receipts):
      receipt_path = f"{receipts_path}[{index}]"
      participant = _required_string(receipt, "participant_fbid", receipt_path)
      is_the_participant = participant == participant_fbid

      if is_the_participant:
         watermarks.append(_milliseconds(receipt, "watermark_timestamp_ms", receipt_path))

   return watermarks


def _is_unread(thread: dict[str, Any], viewer_fbid: str, path: str) -> bool:
   """Whether ``thread`` is unread to the viewer whose messaging id is ``viewer_fbid``.

   A thread is unread when it is marked unread, or when the viewer's read receipt is earlier than
   its last activity or absent. The browser's own rule has not been read, so this is the
   engine's reading of the row (INFERENCE). On 2026-09-24, 29 of the 30 rows of two inbox pages
   carried the viewer's receipt at or after the last activity, and one carried it 166 s before,
   the one row this calls unread.
   """

   is_marked_unread = _required_flag(thread, "marked_as_unread", path)
   last_activity_ms = _milliseconds(thread, "last_activity_timestamp_ms", path)
   watermarks = _receipt_watermarks(thread, viewer_fbid, path)
   has_read_to_the_end = bool(watermarks) and max(watermarks) >= last_activity_ms

   return is_marked_unread or not has_read_to_the_end


def _participant(user: Any, path: str) -> ThreadParticipant:
   return ThreadParticipant(
      user_id=_required_string(user, "id", path),
      username=_required_string(user, "username", path),
      full_name=_required_string(user, "full_name", path),
      is_verified=_required_flag(user, "is_verified", path),
   )


def _participants(thread: dict[str, Any], path: str) -> tuple[ThreadParticipant, ...]:
   users_path = f"{path}.users"
   users = _required(thread, "users", path)

   if not isinstance(users, list):
      raise SchemaChanged(f"{users_path} is not a list", path=users_path)

   return tuple(_participant(user, f"{users_path}[{index}]") for index, user in enumerate(users))


def _newest_message(thread: dict[str, Any], path: str) -> dict[str, Any] | None:
   messages_path = f"{path}.slide_messages"
   messages = _required(thread, "slide_messages", path)
   edges = _required(messages, "edges", messages_path)

   if not isinstance(edges, list):
      raise SchemaChanged(f"{messages_path}.edges is not a list", path=f"{messages_path}.edges")

   if not edges:
      return None

   newest_edge = edges[0]
   node_path = f"{messages_path}.edges[0].node"
   node = _required(newest_edge, "node", f"{messages_path}.edges[0]")

   if not isinstance(node, dict):
      raise SchemaChanged(f"{node_path} is not an object", path=node_path)

   return node


def _direct_thread(edge: Any, path: str) -> DirectThread:
   """One listing row mapped into a :class:`~dumpstagram.models.DirectThread`.

   ``users`` holds the people other than the viewer: on every measured row it was as long as
   ``usersWithoutViewer``, one on each one-to-one row and seventeen on the one group. The viewer
   is named by the row's own ``viewer.interop_messaging_user_fbid``, the id the read receipts use.
   """

   row_path = f"{path}.node.as_ig_direct_thread"
   row = _required(_required(edge, "node", path), "as_ig_direct_thread", f"{path}.node")

   if not isinstance(row, dict):
      raise SchemaChanged(f"{row_path} is not an object", path=row_path)

   viewer_path = f"{row_path}.viewer"
   viewer_fbid = _required_string(
      _required(row, "viewer", row_path), "interop_messaging_user_fbid", viewer_path
   )
   newest = _newest_message(row, row_path)
   newest_path = f"{row_path}.slide_messages.edges[0].node"
   last_activity_ms = _milliseconds(row, "last_activity_timestamp_ms", row_path)

   return DirectThread(
      thread_fbid=_required_string(row, "thread_fbid", row_path),
      title=_required_string(row, "thread_title", row_path),
      is_group=_required_flag(row, "is_group", row_path),
      participants=_participants(row, row_path),
      last_activity_at=datetime.fromtimestamp(last_activity_ms / MILLISECONDS_PER_SECOND, tz=UTC),
      last_message_id=None if newest is None else _required_string(newest, "id", newest_path),
      snippet=None if newest is None else _optional_string(newest, "igd_snippet", newest_path),
      is_unread=_is_unread(row, viewer_fbid, row_path),
      is_marked_unread=_required_flag(row, "marked_as_unread", row_path),
      is_muted=_required_flag(row, "is_muted", row_path),
      is_pinned=_required_flag(row, "is_pin", row_path),
   )


def _connection_of(
   mailbox: dict[str, Any], mailbox_path: str
) -> tuple[list[Any], bool, str | None]:
   connection_path = f"{mailbox_path}.threads_by_folder"
   connection = _required(mailbox, "threads_by_folder", mailbox_path)

   if not isinstance(connection, dict):
      raise SchemaChanged(f"{connection_path} is not an object", path=connection_path)

   edges = _required(connection, "edges", connection_path)

   if not isinstance(edges, list):
      raise SchemaChanged(f"{connection_path}.edges is not a list", path=f"{connection_path}.edges")

   page_info_path = f"{connection_path}.page_info"
   page_info = _required(connection, "page_info", connection_path)

   if not isinstance(page_info, dict):
      raise SchemaChanged(f"{page_info_path} is not an object", path=page_info_path)

   has_next_page = _required_flag(page_info, "has_next_page", page_info_path)
   end_cursor = _optional_string(page_info, "end_cursor", page_info_path)

   return edges, has_next_page, end_cursor


def _thread_page(payload: Any, mailbox_path: tuple[str, ...]) -> InboxPage:
   mailbox = _object_at(payload, mailbox_path)
   joined = ".".join(mailbox_path)
   edges, has_next_page, end_cursor = _connection_of(mailbox, joined)
   connection_path = f"{joined}.threads_by_folder"
   threads = tuple(
      _direct_thread(edge, f"{connection_path}.edges[{index}]") for index, edge in enumerate(edges)
   )

   return InboxPage(
      page=Page(items=threads, has_next_page=has_next_page, end_cursor=end_cursor),
      mailbox_id=_required_string(mailbox, "id", joined),
   )


def parse_inbox_page(payload: Any) -> InboxPage:
   """The inbox's first page, one ``PolarisDirectInboxQuery`` payload, as public threads.

   The rows keep the upstream's order, newest activity first with pinned threads in place, as
   :func:`parse_inbox_listing` keeps them. The page's ``end_cursor`` is the upstream's own, and
   the mailbox id beside it is what the next page is keyed on.

   Finding: ``direct-inbox-thread-list`` in the knowledge base.
   """

   return _thread_page(payload, INBOX_MAILBOX_PATH)


def parse_inbox_continuation(payload: Any) -> tuple[str, str | None]:
   """The mailbox id and the upstream's ``end_cursor`` of the inbox's first page, the two values
   the next page is keyed on, with ``None`` for the cursor when the page says it is the last.
   Nothing else in the payload is read.
   """

   mailbox = _object_at(payload, INBOX_MAILBOX_PATH)
   mailbox_path = ".".join(INBOX_MAILBOX_PATH)
   _, has_next_page, end_cursor = _connection_of(mailbox, mailbox_path)

   return _required_string(mailbox, "id", mailbox_path), end_cursor if has_next_page else None


def parse_inbox_next_page(payload: Any) -> InboxPage:
   """One inbox page after the first, one ``IGDThreadListOffMsysPaginationQuery`` payload.

   Its rows carry the same keys as the first page's and map the same way.

   Finding: ``direct-inbox-thread-list-next-page`` in the knowledge base.
   """

   return _thread_page(payload, INBOX_NEXT_PAGE_MAILBOX_PATH)


def parse_message_requests(payload: Any) -> MessageRequests:
   """One ``IGDMessageRequestLeftRailStandaloneQuery`` payload, both folders.

   A request row is mapped as an inbox row is. Both folders were empty on every read so far, so
   whether a request row carries the same keys has not been observed, and a row that does not
   raises :class:`~dumpstagram.errors.SchemaChanged` naming the key it lacked.

   Finding: ``direct-message-requests`` in the knowledge base.
   """

   pending = _thread_page(payload, PENDING_REQUESTS_PATH).page
   spam = _thread_page(payload, SPAM_REQUESTS_PATH).page

   return MessageRequests(
      pending=pending.items,
      spam=spam.items,
      pending_has_more=pending.has_next_page,
      spam_has_more=spam.has_next_page,
   )


def parse_folder_unread_rows(payload: Any) -> FolderUnreadRows:
   """How many rows of one ``useIGDSystemFolderUnreadThreadCountQuery`` payload are unread.

   The rows carry no viewer, so the viewer is the mailbox's own ``id``, which equalled the
   ``viewer.interop_messaging_user_fbid`` of every listing row read beside it on 2026-09-24 and
   the one participant on every row's receipts on 2026-09-23.

   Finding: ``direct-inbox-unread-thread-count`` in the knowledge base.
   """

   mailbox = _object_at(payload, INBOX_MAILBOX_PATH)
   mailbox_path = ".".join(INBOX_MAILBOX_PATH)
   viewer_fbid = _required_string(mailbox, "id", mailbox_path)
   edges, has_next_page, _ = _connection_of(mailbox, mailbox_path)
   connection_path = f"{mailbox_path}.threads_by_folder"
   unread = 0

   for index, edge in enumerate(edges):
      edge_path = f"{connection_path}.edges[{index}]"
      thread_path = f"{edge_path}.node.as_ig_direct_thread"
      thread = _required(
         _required(edge, "node", edge_path), "as_ig_direct_thread", f"{edge_path}.node"
      )

      if not isinstance(thread, dict):
         raise SchemaChanged(f"{thread_path} is not an object", path=thread_path)

      if _is_unread(thread, viewer_fbid, thread_path):
         unread += 1

   return FolderUnreadRows(unread=unread, has_more=has_next_page)
