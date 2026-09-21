"""Map one GraphQL payload into typed models.

This is the only module that knows both the upstream field names and the public models, and
that is deliberate: ADR-0007 requires GraphQL shapes to stop before ``_core``, so the mapping
happens on the surface adapter rather than one layer up.

Mapping is explicit and total. Every field is read by name, a missing required key raises
:class:`~dumpstagram.errors.SchemaChanged` carrying the path that was missing, and unknown
keys are ignored. Nothing is splatted into a constructor, because a permissive mapper turns
an upstream rename into silently degraded records rather than an error.

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

from datetime import UTC, datetime
from typing import Any

from dumpstagram.errors import SchemaChanged
from dumpstagram.models import Message, MessageSender, Page, Reaction

__all__ = ["THREAD_PAGE_PATH", "parse_thread_message_page"]

THREAD_PAGE_PATH = ("data", "fetch__SlideThread", "as_ig_direct_thread", "slide_messages")
"""The canonical path to the message connection, unchanged across both measured days."""

MILLISECONDS_PER_SECOND = 1000


def _object_at(payload: Any, path: tuple[str, ...]) -> dict[str, Any]:
   """Walk ``path``, raising with the exact prefix that stopped resolving."""

   current = payload

   for depth, key in enumerate(path):
      reached = ".".join(path[: depth + 1])

      if not isinstance(current, dict):
         raise SchemaChanged(
            f"{reached} is not reachable, its parent is not an object", path=reached
         )

      if key not in current:
         raise SchemaChanged(f"{reached} is missing from the payload", path=reached)

      current = current[key]

   if not isinstance(current, dict):
      raise SchemaChanged(f"{'.'.join(path)} is not an object", path=".".join(path))

   return current


def _required(node: Any, key: str, path: str) -> Any:
   if not isinstance(node, dict) or key not in node:
      raise SchemaChanged(f"{path}.{key} is missing from the payload", path=f"{path}.{key}")

   return node[key]


def _required_string(node: Any, key: str, path: str) -> str:
   value = _required(node, key, path)

   if not isinstance(value, str):
      raise SchemaChanged(f"{path}.{key} is not a string", path=f"{path}.{key}")

   return value


def _required_flag(node: Any, key: str, path: str) -> bool:
   value = _required(node, key, path)

   if not isinstance(value, bool):
      raise SchemaChanged(f"{path}.{key} is not a boolean", path=f"{path}.{key}")

   return value


def _optional_string(node: dict[str, Any], key: str, path: str) -> str | None:
   value = _required(node, key, path)

   if value is None:
      return None

   if not isinstance(value, str):
      raise SchemaChanged(f"{path}.{key} is not a string or null", path=f"{path}.{key}")

   return value


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
   )


def parse_thread_message_page(payload: Any) -> Page[Message]:
   """One ``useIGDMessageListPaginationQuery`` payload, mapped into typed messages.

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

   connection = _object_at(payload, THREAD_PAGE_PATH)
   connection_path = ".".join(THREAD_PAGE_PATH)

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
