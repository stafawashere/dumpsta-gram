"""Gates on the mapper from one GraphQL page to typed messages.

The defect class here is the one the corpus rates worst: an upstream field rename degrades
records silently, because a permissive mapper fills a default instead of raising. Every gate
below names a specific way that can happen.

The node fixture carries the key set observed on all twenty nodes of a live page on
2026-09-21, recorded in `logs/message-node-shape-2026-09-21-022957.json`, with synthetic
values. Keys that were null on all twenty are present and null, because a mapper that only
ever sees the keys it reads is a mapper whose unknown-field policy is untested.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from dumpstagram._private.web.parse import parse_thread_message_page
from dumpstagram.errors import NotFound, SchemaChanged

THREAD_FBID = "17945046917948992"
MESSAGE_ID = "mid.$cAAANx1A4CESm8y_m2mgweqeUAaea"
OTHER_MESSAGE_ID = "mid.$cAAANx1A4CESm87IV-mgwmzNQgle_"
CURSOR = "cursor-that-stands-in-for-132-characters"


def node(**overrides: Any) -> dict[str, Any]:
   built: dict[str, Any] = {
      "__typename": "SlideMessage",
      "bot_response_id": None,
      "content": {"__typename": "SlideMessageText", "text_body": "hello"},
      "content_type": "TEXT",
      "expiration_timestamp_ms": None,
      "id": MESSAGE_ID,
      "igd_is_forwarded": False,
      "igd_wearables_attribution_text": None,
      "igd_wearables_attribution_type": None,
      "is_ai_generated": False,
      "is_pinned": False,
      "is_reported": False,
      "is_tombstone_revealable": None,
      "mentions": [],
      "message_id": MESSAGE_ID,
      "msg_reactions": [],
      "offline_threading_id": "7551234567890123456",
      "reactions": [],
      "replied_to_message": None,
      "replied_to_message_id": None,
      "sender": {
         "id": "sender-node-id",
         "igid": "1111111111",
         "name": "someone",
         "user_dict": None,
      },
      "sender_fbid": "17841400000000000",
      "slide_edit_history": [],
      "text_body": "hello",
      "thread_fbid": THREAD_FBID,
      "timestamp_ms": "1758412345678",
      "tombstone_reason": None,
      "view_expiration_timestamp_ms": None,
   }

   built.update(overrides)

   return built


def payload(
   nodes: list[dict[str, Any]],
   *,
   has_next_page: bool = False,
   end_cursor: str | None = None,
   thread: Any = ...,
) -> dict[str, Any]:
   connection = {
      "edges": [{"cursor": CURSOR, "node": entry} for entry in nodes],
      "page_info": {
         "has_next_page": has_next_page,
         "has_previous_page": False,
         "start_cursor": CURSOR,
         "end_cursor": end_cursor,
      },
   }

   resolved = {"id": THREAD_FBID, "slide_messages": connection} if thread is ... else thread

   return {"data": {"fetch__SlideThread": {"as_ig_direct_thread": resolved}}, "extensions": {}}


def test_a_well_formed_page_maps_every_field_it_claims_to_carry() -> None:
   """Catches a mapper reading the wrong key, which produces a plausible wrong record."""

   page = parse_thread_message_page(
      payload(
         [
            node(
               igd_is_forwarded=True,
               is_pinned=True,
               is_ai_generated=True,
               replied_to_message_id=OTHER_MESSAGE_ID,
               reactions=[
                  {"reaction": "\N{HEAVY BLACK HEART}", "sender_fbid": "17841400000000001"}
               ],
            )
         ],
         has_next_page=True,
         end_cursor=CURSOR,
      )
   )

   assert len(page.items) == 1

   message = page.items[0]

   assert message.id == MESSAGE_ID
   assert message.thread_fbid == THREAD_FBID
   assert message.text == "hello"
   assert message.content_type == "TEXT"
   assert message.sender.fbid == "17841400000000000"
   assert message.sender.igid == "1111111111"
   assert message.sender.name == "someone"
   assert message.is_forwarded is True
   assert message.is_pinned is True
   assert message.is_ai_generated is True
   assert message.replied_to_message_id == OTHER_MESSAGE_ID
   assert message.reactions == (
      type(message.reactions[0])(emoji="\N{HEAVY BLACK HEART}", sender_fbid="17841400000000001"),
   )
   assert page.has_next_page is True
   assert page.end_cursor == CURSOR


def test_the_timestamp_becomes_aware_utc_at_the_right_instant() -> None:
   """Catches milliseconds read as seconds, which dates every message to 1970 and still parses."""

   page = parse_thread_message_page(payload([node(timestamp_ms="1758412345678")]))
   sent_at = page.items[0].sent_at

   assert sent_at.tzinfo is not None
   assert sent_at.utcoffset() == timedelta(0)
   assert sent_at == datetime(2025, 9, 20, 23, 52, 25, 678000, tzinfo=UTC)


def test_an_integer_timestamp_is_accepted_too() -> None:
   """The one coercion the mapper allows, because a JSON number is the plausible next shape."""

   page = parse_thread_message_page(payload([node(timestamp_ms=1758412345678)]))

   assert page.items[0].sent_at == datetime(2025, 9, 20, 23, 52, 25, 678000, tzinfo=UTC)


@pytest.mark.parametrize(
   "missing",
   ["id", "thread_fbid", "sender_fbid", "timestamp_ms", "content_type", "text_body", "reactions"],
)
def test_a_missing_required_key_raises_rather_than_defaulting(missing: str) -> None:
   """Catches the silent-degradation failure mode: a renamed field becoming an empty value."""

   broken = node()
   del broken[missing]

   with pytest.raises(SchemaChanged) as raised:
      parse_thread_message_page(payload([broken]))

   assert raised.value.path is not None
   assert raised.value.path.endswith(f".{missing}")


def test_an_unknown_upstream_key_is_ignored() -> None:
   """Six fields appeared on this node between two captures. Failing on them is not an option."""

   page = parse_thread_message_page(
      payload([node(a_field_nobody_has_seen_before={"nested": ["anything"]})])
   )

   assert page.items[0].id == MESSAGE_ID


def test_a_null_text_body_stays_none_rather_than_becoming_empty() -> None:
   """Absent, null and empty are three states, and collapsing them loses one."""

   page = parse_thread_message_page(payload([node(text_body=None)]))

   assert page.items[0].text is None


def test_an_empty_text_body_stays_empty_rather_than_becoming_none() -> None:
   """The positive control for the gate above."""

   page = parse_thread_message_page(payload([node(text_body="")]))

   assert page.items[0].text == ""


def test_reactions_come_from_reactions_and_not_from_msg_reactions() -> None:
   """Both were non-empty on the same measured message. Only one carries the emoji."""

   page = parse_thread_message_page(
      payload(
         [
            node(
               reactions=[{"reaction": "\N{FIRE}", "sender_fbid": "17841400000000002"}],
               msg_reactions=[{"sender_fbid": "17841400000000003", "sender_igid": "2222222222"}],
            )
         ]
      )
   )

   reactions = page.items[0].reactions

   assert len(reactions) == 1
   assert reactions[0].emoji == "\N{FIRE}"
   assert reactions[0].sender_fbid == "17841400000000002"


def test_the_identifier_comes_from_id_and_not_from_message_id() -> None:
   """They were equal on all twenty measured nodes. This asserts which one is read anyway."""

   page = parse_thread_message_page(payload([node(id=MESSAGE_ID, message_id=OTHER_MESSAGE_ID)]))

   assert page.items[0].id == MESSAGE_ID


def test_edges_keep_the_order_the_upstream_sent_them_in() -> None:
   """Catches a mapper sorting the page, which hides whether upstream order ever changes."""

   page = parse_thread_message_page(
      payload(
         [
            node(id=MESSAGE_ID, timestamp_ms="1758412345678"),
            node(id=OTHER_MESSAGE_ID, timestamp_ms="1658412345678"),
         ]
      )
   )

   assert [message.id for message in page.items] == [MESSAGE_ID, OTHER_MESSAGE_ID]


def test_another_page_with_no_cursor_to_reach_it_raises() -> None:
   """A caller that trusts has_next_page and gets no cursor stops paginating silently."""

   with pytest.raises(SchemaChanged):
      parse_thread_message_page(payload([node()], has_next_page=True, end_cursor=None))


def test_the_last_page_is_allowed_to_carry_a_cursor() -> None:
   """The positive control for the gate above, since the upstream sends one on the last page."""

   page = parse_thread_message_page(payload([node()], has_next_page=False, end_cursor=CURSOR))

   assert page.has_next_page is False
   assert page.end_cursor == CURSOR


def test_an_unresolved_thread_raises_not_found() -> None:
   """The two non-fbid thread identifiers answer with nothing, which must not read as empty."""

   with pytest.raises(NotFound):
      parse_thread_message_page(payload([], thread=None))


def test_an_empty_thread_is_an_empty_page_and_not_an_error() -> None:
   """The positive control for the gate above. Zero messages is a legal answer."""

   page = parse_thread_message_page(payload([]))

   assert page.items == ()
   assert page.has_next_page is False


def test_a_missing_connection_names_the_path_that_stopped_resolving() -> None:
   """The doc_id rotating produces a payload shaped like nothing. The error must say where."""

   with pytest.raises(SchemaChanged) as raised:
      parse_thread_message_page({"data": {"fetch__SlideThread": {}}})

   assert raised.value.path == "data.fetch__SlideThread.as_ig_direct_thread"
