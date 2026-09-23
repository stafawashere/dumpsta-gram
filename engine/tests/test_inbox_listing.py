"""Gates on the inbox listing's private request and mapper, which the Phase 4 listener polls.

Three defect classes live here.

The mapper can take a row's values from the wrong key. ``thread_key`` and ``thread_fbid`` are
both 17 digit strings and differ on every one-to-one thread, and only ``thread_fbid`` is what
``thread_messages`` takes, so a swap sends every top-up read to an empty answer. The newest
message is the first edge, and reading any other hides a new message from the listener.

The listing can be reported in another order than the upstream's, and a position the listener
compares would then move with nothing having happened.

And the request can drift from the one an inbox load sends, including the provider flag that
makes each row carry its newest messages at all.

Every payload is canned. Nothing in this file touches the network.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

import pytest

from dumpstagram._private.web.parse import (
   InboxMessage,
   InboxThread,
   parse_inbox_listing,
   parse_inbox_recent_messages,
)
from dumpstagram._private.web.requests import build_inbox_listing_request
from dumpstagram.errors import SchemaChanged
from tests.test_direct import a_bootstrapped_session, sent_variables

LISTING_DOC_ID = "28794932076791671"
INBOX_REFERER = "https://www.instagram.com/direct/inbox/"
API_GRAPHQL = "https://www.instagram.com/api/graphql"
DEVICE_ID = "0b6f2c1e-8d7a-4c55-9e3f-2a1b0c9d8e7f"

NEWEST_THREAD_FBID = "17800000000000001"
NEWEST_THREAD_KEY = "17800000000000901"
OLDER_THREAD_FBID = "17800000000000002"
OLDER_THREAD_KEY = "17800000000000902"


def message_edge(message_id: str, timestamp_ms: str) -> dict[str, Any]:
   return {
      "cursor": "a" * 132,
      "node": {
         "__typename": "SlideMessage",
         "id": message_id,
         "timestamp_ms": timestamp_ms,
         "sender_fbid": "17841400000000055",
         "content_type": "TEXT",
         "text_body": "a message",
         "igd_snippet": "a message",
         "content": None,
         "expiration_timestamp_ms": None,
         "view_expiration_timestamp_ms": None,
      },
   }


def listing_row(
   *,
   thread_fbid: str,
   thread_key: str,
   activity_ms: str,
   message_edges: list[dict[str, Any]],
   is_pin: bool = False,
   is_muted: bool = True,
) -> dict[str, Any]:
   """One edge with the 26 row keys measured on 2026-09-23, synthetic values.

   ``thread_key`` and ``is_muted`` differ from ``thread_fbid`` and ``is_pin`` so a value read
   from the neighbouring key cannot come out right by accident.
   """

   thread = {
      "event_chat_info": None,
      "folder": "PRIMARY",
      "id": thread_fbid,
      "input_mode": 0,
      "is_group": False,
      "is_muted": is_muted,
      "is_pin": is_pin,
      "last_activity_timestamp_ms": activity_ms,
      "marked_as_unread": False,
      "messaging_folder_tag": "INBOX",
      "nicknames": [],
      "slide_messages": {
         "edges": message_edges,
         "page_info": {"end_cursor": "b" * 132, "has_next_page": True},
      },
      "slide_read_receipts": [],
      "system_folder": "INBOX",
      "takedown_data": None,
      "thread_fbid": thread_fbid,
      "thread_id": "3" * 39,
      "thread_image_url": None,
      "thread_key": thread_key,
      "thread_label": 0,
      "thread_subtype": "IG_ONLY_ONE_TO_ONE",
      "thread_title": "a title",
      "users": [],
      "usersWithoutViewer": [],
      "viewer": {"id": "1234567890"},
      "viewer_id": "1234567890",
   }

   return {
      "cursor": "c" * 132,
      "node": {"__typename": "SlideThread", "id": thread_fbid, "as_ig_direct_thread": thread},
   }


def listing_payload(
   edges: list[dict[str, Any]],
   *,
   has_next_page: bool = True,
   end_cursor: str | None = "d" * 132,
) -> dict[str, Any]:
   return {
      "data": {
         "get_slide_mailbox_for_iris_subscription": {
            "__token": None,
            "__typename": "SlideMailbox",
            "id": "1234567890",
            "iris_inactive_subscription_uq_seq_id": "1834149",
            "pinned_threads_v2": [],
            "threads_by_folder": {
               "edges": edges,
               "page_info": {"end_cursor": end_cursor, "has_next_page": has_next_page},
            },
         }
      },
      "extensions": {"is_final": True},
   }


def two_row_listing() -> dict[str, Any]:
   return listing_payload(
      [
         listing_row(
            thread_fbid=NEWEST_THREAD_FBID,
            thread_key=NEWEST_THREAD_KEY,
            activity_ms="1790153242519",
            message_edges=[
               message_edge("mid.$newest", "1790153242519"),
               message_edge("mid.$middle", "1790153102470"),
               message_edge("mid.$oldest", "1790136891853"),
            ],
            is_pin=True,
         ),
         listing_row(
            thread_fbid=OLDER_THREAD_FBID,
            thread_key=OLDER_THREAD_KEY,
            activity_ms="1790135581037",
            message_edges=[message_edge("mid.$other", "1790135581037")],
         ),
      ]
   )


def test_a_row_maps_field_by_field() -> None:
   """Catches thread_key taken for thread_fbid, the oldest listed message taken for the newest,
   and is_muted taken for is_pin."""

   page = parse_inbox_listing(two_row_listing())

   assert page.items[0] == InboxThread(
      thread_fbid=NEWEST_THREAD_FBID,
      thread_key=NEWEST_THREAD_KEY,
      last_activity_ms=1790153242519,
      last_message_id="mid.$newest",
      is_pinned=True,
   )
   assert page.items[1] == InboxThread(
      thread_fbid=OLDER_THREAD_FBID,
      thread_key=OLDER_THREAD_KEY,
      last_activity_ms=1790135581037,
      last_message_id="mid.$other",
      is_pinned=False,
   )


def test_rows_keep_the_listings_order() -> None:
   """Catches the rows reordered on the way out. The fixture's thread ids sort the other way
   round from the listing, so any sort by id shows."""

   payload = listing_payload(
      [
         listing_row(
            thread_fbid="17800000000000009",
            thread_key="17800000000000909",
            activity_ms="1790153242519",
            message_edges=[message_edge("mid.$a", "1790153242519")],
         ),
         listing_row(
            thread_fbid="17800000000000003",
            thread_key="17800000000000903",
            activity_ms="1790135581037",
            message_edges=[message_edge("mid.$b", "1790135581037")],
         ),
      ]
   )

   page = parse_inbox_listing(payload)

   assert [thread.thread_fbid for thread in page.items] == [
      "17800000000000009",
      "17800000000000003",
   ]


def test_a_thread_without_messages_has_no_newest_message_id() -> None:
   """Catches an empty thread taken as a malformed payload, which would stop a listener on an
   inbox that merely holds a thread with nothing in it."""

   payload = listing_payload(
      [
         listing_row(
            thread_fbid=NEWEST_THREAD_FBID,
            thread_key=NEWEST_THREAD_KEY,
            activity_ms="1790153242519",
            message_edges=[],
         )
      ]
   )

   page = parse_inbox_listing(payload)

   assert page.items[0].last_message_id is None


def test_a_row_without_an_activity_marker_is_a_schema_change() -> None:
   """Catches a missing marker defaulted to a value, which would read as no activity and hide
   every change on that row."""

   payload = two_row_listing()
   row = payload["data"]["get_slide_mailbox_for_iris_subscription"]["threads_by_folder"]["edges"][0]
   del row["node"]["as_ig_direct_thread"]["last_activity_timestamp_ms"]

   with pytest.raises(SchemaChanged) as raised:
      parse_inbox_listing(payload)

   assert raised.value.path is not None
   assert raised.value.path.endswith("last_activity_timestamp_ms")


def test_the_listing_ends_only_on_the_servers_flag() -> None:
   """Catches has_next_page inferred from the cursor. The fixture carries a cursor beside a
   false flag, and only the flag says whether more rows exist."""

   page = parse_inbox_listing(
      listing_payload(
         two_row_listing()["data"]["get_slide_mailbox_for_iris_subscription"]["threads_by_folder"][
            "edges"
         ],
         has_next_page=False,
      )
   )

   assert page.has_next_page is False
   assert page.end_cursor == "d" * 132


def test_the_listing_request_is_the_one_an_inbox_load_sends() -> None:
   """The parity gate for the request. Catches another referer, the device id not sent, and a
   provider flag changed, the row message count among them."""

   request = build_inbox_listing_request(a_bootstrapped_session(), device_id=DEVICE_ID)
   body = parse_qs(request.content.decode("utf-8")) if request.content else {}

   assert request.url == API_GRAPHQL
   assert body["doc_id"] == [LISTING_DOC_ID]
   assert body["fb_api_req_friendly_name"] == ["PolarisDirectInboxQuery"]
   assert sent_variables(request) == {
      "device_id_for_iris_subscription": DEVICE_ID,
      "__relay_internal__pv__IGDIsProfessionalAccountGKrelayprovider": False,
      "__relay_internal__pv__IGDPinnedThreadsRenderEnabledGKrelayprovider": True,
      "__relay_internal__pv__IGDMaxUnreadMessagesCountrelayprovider": 5,
      "__relay_internal__pv__IGDThreadListActionsEnabledGKrelayprovider": True,
   }
   assert request.headers["referer"] == INBOX_REFERER
   assert "x-root-field-name" not in request.headers


def test_each_rows_carried_messages_map_in_order_with_their_times() -> None:
   """Catches the carried messages reordered or given the wrong row's times. The listener
   places a ``since`` in time from these, so a wrong time moves where its catch up starts."""

   carried = parse_inbox_recent_messages(two_row_listing())

   assert carried == (
      (
         InboxMessage(id="mid.$newest", sent_at_ms=1790153242519),
         InboxMessage(id="mid.$middle", sent_at_ms=1790153102470),
         InboxMessage(id="mid.$oldest", sent_at_ms=1790136891853),
      ),
      (InboxMessage(id="mid.$other", sent_at_ms=1790135581037),),
   )
