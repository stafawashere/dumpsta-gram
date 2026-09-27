"""Gates on the direct read side of E2 batch 1: the inbox pages, the message requests and the
unread counts.

Six defect classes live here.

A row can be mapped from the wrong key. ``thread_key`` and ``thread_fbid`` are both 17 digit
strings that differ on every one-to-one row, and a participant carries both a numeric account id
and a messaging id, so a swap degrades every row without failing.

The unread rule can read the wrong receipt. Every row carries the other person's receipt beside
the viewer's, and the viewer is named differently in the listing and in the count query, so a
rule that takes any receipt, or the wrong viewer, counts the wrong threads.

The inbox cursor can lose the mailbox. The next page is keyed on the mailbox id beside the
upstream's cursor, and only the first page carries it, so a cursor handed out without it cannot
reach page two.

The folders can be swapped: pending read as spam, or the pending count sent as the inbox's.

Each request can drift from the one the engine replayed live on 2026-09-24.

And a command can stop on the wrong terminator or print a count without saying it is partial.

The payloads are the recorded answers of 2026-09-23 and 2026-09-24, pseudonymised by
``scripts/build_direct_read_fixtures.py``. Nothing in this file touches the network.
"""

from __future__ import annotations

import copy
import io
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import pytest

from dumpstagram._cli.main import main
from dumpstagram._core.inbox import read_inbox_page, read_unread_counts
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.web.parse.direct import (
   parse_folder_unread_rows,
   parse_inbox_next_page,
   parse_inbox_page,
   parse_message_requests,
)
from dumpstagram._private.web.requests.direct import (
   build_folder_unread_rows_request,
   build_inbox_next_page_request,
   build_message_requests_request,
)
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY
from dumpstagram.client import SyncClient
from dumpstagram.models import DirectThread, MessageRequests, Page, UnreadCounts
from dumpstagram.session import Session
from tests.test_direct import (
   FakeClock,
   ScriptedTransport,
   a_bootstrapped_session,
   json_response,
   make_paced,
   sent_variables,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "direct_read"

API_GRAPHQL = "https://www.instagram.com/api/graphql"
INBOX_REFERER = "https://www.instagram.com/direct/inbox/"
NEXT_PAGE_DOC_ID = "28000787896268887"
REQUESTS_DOC_ID = "27525641663781745"
UNREAD_ROWS_DOC_ID = "27437959689223570"
THIRTY_DAYS_MS = 2_592_000_000
DEVICE_ID = "0b6f2c1e-8d7a-4c55-9e3f-2a1b0c9d8e7f"
NOW_MS = 1_790_000_000_000

SCRIPTED_BEHAVIOR = replace(PARITY, cookie_sync=False)


def recorded(name: str) -> Any:
   return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def first_page_rows() -> list[dict[str, Any]]:
   payload = recorded("inbox_first_page.json")
   edges = payload["data"]["get_slide_mailbox_for_iris_subscription"]["threads_by_folder"]["edges"]

   return [edge["node"]["as_ig_direct_thread"] for edge in edges]


def viewer_watermark(row: dict[str, Any]) -> int | None:
   viewer = row["viewer"]["interop_messaging_user_fbid"]
   marks = [
      int(receipt["watermark_timestamp_ms"])
      for receipt in row["slide_read_receipts"]
      if receipt["participant_fbid"] == viewer
   ]

   return max(marks) if marks else None


def is_read_to_the_end(row: dict[str, Any]) -> bool:
   watermark = viewer_watermark(row)
   has_a_receipt = watermark is not None
   last_activity = int(row["last_activity_timestamp_ms"])

   return has_a_receipt and (watermark or 0) >= last_activity


def reads_as_unread(row: dict[str, Any]) -> bool:
   is_marked = bool(row["marked_as_unread"])

   return is_marked or not is_read_to_the_end(row)


def first_page_mailbox_id() -> str:
   mailbox_id: str = recorded("inbox_first_page.json")["data"][
      "get_slide_mailbox_for_iris_subscription"
   ]["id"]

   return mailbox_id


def upstream_first_cursor() -> str:
   cursor: str = recorded("inbox_first_page.json")["data"][
      "get_slide_mailbox_for_iris_subscription"
   ]["threads_by_folder"]["page_info"]["end_cursor"]

   return cursor


def test_the_first_page_maps_every_row_in_the_upstream_order_by_its_thread_fbid() -> None:
   """Catches ``thread_key`` taken for ``thread_fbid``, which differ on every one-to-one row, and
   rows reordered or dropped."""

   rows = first_page_rows()
   inbox_page = parse_inbox_page(recorded("inbox_first_page.json"))
   expected = [row["thread_fbid"] for row in rows]
   keys = [row["thread_key"] for row in rows]

   assert len(rows) == 15
   assert expected != keys
   assert [thread.thread_fbid for thread in inbox_page.page.items] == expected
   assert inbox_page.page.has_next_page is True
   assert inbox_page.page.end_cursor == upstream_first_cursor()
   assert inbox_page.mailbox_id == first_page_mailbox_id()


def test_a_row_is_unread_exactly_when_the_viewers_receipt_is_older_than_its_last_activity() -> None:
   """Catches a rule that reads the other person's receipt, or counts a receipt equal to the last
   activity as unread. The recorded page holds one unread row, 29 read ones across two pages,
   and rows whose receipt equals the activity to the millisecond."""

   rows = first_page_rows()
   expected = [reads_as_unread(row) for row in rows]
   equal_to_the_millisecond = [
      viewer_watermark(row) == int(row["last_activity_timestamp_ms"]) for row in rows
   ]
   first = parse_inbox_page(recorded("inbox_first_page.json")).page
   second = parse_inbox_next_page(recorded("inbox_next_page.json")).page

   assert sum(expected) == 1
   assert any(equal_to_the_millisecond)
   assert [thread.is_unread for thread in first.items] == expected
   assert not any(thread.is_unread for thread in second.items)
   assert len(second.items) == 15


def with_row(change: Any) -> dict[str, Any]:
   payload = copy.deepcopy(recorded("inbox_first_page.json"))
   edges = payload["data"]["get_slide_mailbox_for_iris_subscription"]["threads_by_folder"]["edges"]
   rows = [edge["node"]["as_ig_direct_thread"] for edge in edges]
   read_rows = [row for row in rows if not reads_as_unread(row)]
   change(read_rows[0])
   payload["data"]["get_slide_mailbox_for_iris_subscription"]["threads_by_folder"]["edges"] = [
      edge for edge in edges if edge["node"]["as_ig_direct_thread"] is read_rows[0]
   ]

   return payload


def test_a_read_row_marked_unread_or_without_the_viewers_receipt_is_unread() -> None:
   """Catches the marked unread flag ignored, and a missing viewer receipt taken as read. The
   control is the same row untouched, which reads as read."""

   def untouched(row: dict[str, Any]) -> None:
      return None

   def marked(row: dict[str, Any]) -> None:
      row["marked_as_unread"] = True

   def without_the_viewers_receipt(row: dict[str, Any]) -> None:
      viewer = row["viewer"]["interop_messaging_user_fbid"]
      row["slide_read_receipts"] = [
         receipt for receipt in row["slide_read_receipts"] if receipt["participant_fbid"] != viewer
      ]

   control = parse_inbox_page(with_row(untouched)).page.items[0]
   marked_row = parse_inbox_page(with_row(marked)).page.items[0]
   unreceipted = parse_inbox_page(with_row(without_the_viewers_receipt)).page.items[0]

   assert control.is_unread is False
   assert (marked_row.is_unread, marked_row.is_marked_unread) == (True, True)
   assert (unreceipted.is_unread, unreceipted.is_marked_unread) == (True, False)


def test_participants_are_the_other_users_by_their_account_id() -> None:
   """Catches a participant keyed on the messaging id rather than the account id, and the group
   row's members dropped."""

   rows = first_page_rows()
   threads = parse_inbox_page(recorded("inbox_first_page.json")).page.items
   group_sizes = [len(thread.participants) for thread in threads if thread.is_group]

   for row, thread in zip(rows, threads, strict=True):
      account_ids = [user["id"] for user in row["users"]]
      messaging_ids = [user["interop_messaging_user_fbid"] for user in row["users"]]

      assert [participant.user_id for participant in thread.participants] == account_ids
      assert account_ids != messaging_ids
      assert [participant.username for participant in thread.participants] == [
         user["username"] for user in row["users"]
      ]
      assert row["viewer_id"] not in account_ids

   assert group_sizes == [17]


def test_the_newest_carried_message_names_the_last_message_and_the_snippet() -> None:
   """Catches the oldest carried message read as the newest, and the snippet taken from the
   message text rather than the upstream's preview."""

   rows = first_page_rows()
   threads = parse_inbox_page(recorded("inbox_first_page.json")).page.items

   for row, thread in zip(rows, threads, strict=True):
      newest = row["slide_messages"]["edges"][0]["node"]

      assert thread.last_message_id == newest["id"]
      assert thread.snippet == newest["igd_snippet"]
      assert thread.title == row["thread_title"]


def test_the_flags_and_the_last_activity_come_from_their_own_keys() -> None:
   """Catches ``is_muted`` read for ``is_pin`` and the last activity read as seconds. The page
   holds pinned rows and a muted one, and no row is both."""

   rows = first_page_rows()
   threads = parse_inbox_page(recorded("inbox_first_page.json")).page.items
   pinned = [row["is_pin"] for row in rows]
   muted = [row["is_muted"] for row in rows]

   assert any(pinned)
   assert any(muted)
   assert pinned != muted
   assert [thread.is_pinned for thread in threads] == pinned
   assert [thread.is_muted for thread in threads] == muted
   assert [thread.last_activity_at for thread in threads] == [
      datetime.fromtimestamp(int(row["last_activity_timestamp_ms"]) / 1000, tz=UTC) for row in rows
   ]


def test_the_next_page_maps_under_its_own_root_and_names_the_same_mailbox() -> None:
   """Catches the next page read from the first page's root, which it does not answer under."""

   second = parse_inbox_next_page(recorded("inbox_next_page.json"))
   first_ids = {row["thread_fbid"] for row in first_page_rows()}

   assert second.mailbox_id == first_page_mailbox_id()
   assert len(second.page.items) == 15
   assert first_ids.isdisjoint(thread.thread_fbid for thread in second.page.items)
   assert second.page.has_next_page is True


def test_both_request_folders_map_from_their_own_root() -> None:
   """Catches the pending folder read from the spam root. Both recorded folders are empty, so a
   recorded inbox row is planted in the pending one and must come out there alone."""

   empty = parse_message_requests(recorded("message_requests.json"))
   planted = copy.deepcopy(recorded("message_requests.json"))
   row_edge = recorded("inbox_first_page.json")["data"]["get_slide_mailbox_for_iris_subscription"][
      "threads_by_folder"
   ]["edges"][0]
   planted["data"]["pendingMailbox"]["threads_by_folder"]["edges"] = [row_edge]
   planted["data"]["pendingMailbox"]["threads_by_folder"]["page_info"]["has_next_page"] = True
   requests = parse_message_requests(planted)

   assert empty == MessageRequests(pending=(), spam=(), pending_has_more=False, spam_has_more=False)
   assert [thread.thread_fbid for thread in requests.pending] == [
      row_edge["node"]["as_ig_direct_thread"]["thread_fbid"]
   ]
   assert requests.spam == ()
   assert (requests.pending_has_more, requests.spam_has_more) == (True, False)


def unread_rows_with(change: Any) -> dict[str, Any]:
   payload = copy.deepcopy(recorded("inbox_unread_rows.json"))
   edges = payload["data"]["get_slide_mailbox_for_iris_subscription"]["threads_by_folder"]["edges"]
   change(edges[0]["node"]["as_ig_direct_thread"])

   return payload


def test_the_unread_rows_are_counted_for_the_mailbox_as_the_viewer() -> None:
   """Catches the viewer taken from a receipt rather than the mailbox id. The first row's other
   participant is moved to before the last activity, which only a wrong viewer counts, and then
   the viewer's own is, which only the right one does."""

   mailbox_id = recorded("inbox_unread_rows.json")["data"][
      "get_slide_mailbox_for_iris_subscription"
   ]["id"]

   def move_receipt(owner_is_the_viewer: bool) -> Any:
      def change(row: dict[str, Any]) -> None:
         earlier = str(int(row["last_activity_timestamp_ms"]) - 60_000)

         for receipt in row["slide_read_receipts"]:
            is_the_viewers = receipt["participant_fbid"] == mailbox_id

            if is_the_viewers == owner_is_the_viewer:
               receipt["watermark_timestamp_ms"] = earlier

      return change

   recorded_rows = parse_folder_unread_rows(recorded("inbox_unread_rows.json"))
   other_moved = parse_folder_unread_rows(unread_rows_with(move_receipt(False)))
   viewer_moved = parse_folder_unread_rows(unread_rows_with(move_receipt(True)))
   pending = parse_folder_unread_rows(recorded("pending_unread_rows.json"))

   assert (recorded_rows.unread, recorded_rows.has_more) == (0, True)
   assert other_moved.unread == 0
   assert viewer_moved.unread == 1
   assert (pending.unread, pending.has_more) == (0, False)


def test_the_next_page_request_is_the_one_replayed_live() -> None:
   """The parity gate for the next page. Catches another page size, folder, root id or path, or
   a referer other than the inbox."""

   request = build_inbox_next_page_request(
      a_bootstrapped_session(), mailbox_id="90000000000000001", cursor="C000001ccc"
   )
   body = parse_qs(request.content.decode("utf-8")) if request.content else {}

   assert request.url == API_GRAPHQL
   assert body["doc_id"] == [NEXT_PAGE_DOC_ID]
   assert body["fb_api_req_friendly_name"] == ["IGDThreadListOffMsysPaginationQuery"]
   assert request.headers["referer"] == INBOX_REFERER
   assert sent_variables(request) == {
      "count": 15,
      "cursor": "C000001ccc",
      "folder": "INBOX",
      "newer_than_timestamp_ms": None,
      "id": "90000000000000001",
      "__relay_internal__pv__IGDPinnedThreadsRenderEnabledGKrelayprovider": True,
      "__relay_internal__pv__IGDMaxUnreadMessagesCountrelayprovider": 5,
      "__relay_internal__pv__IGDThreadListActionsEnabledGKrelayprovider": True,
   }


def test_the_requests_query_sends_the_thirty_day_bound_as_an_integer() -> None:
   """The parity gate for the requests. Catches the bound sent as a string, which the replays
   never sent, or counted from another window."""

   request = build_message_requests_request(
      a_bootstrapped_session(), iris_device_id=DEVICE_ID, now_ms=NOW_MS
   )
   body = parse_qs(request.content.decode("utf-8")) if request.content else {}

   assert request.url == API_GRAPHQL
   assert body["doc_id"] == [REQUESTS_DOC_ID]
   assert request.headers["referer"] == INBOX_REFERER
   assert sent_variables(request) == {
      "device_id_for_iris_subscription": DEVICE_ID,
      "__relay_internal__pv__IGD30DayAgoTimestampMsrelayprovider": NOW_MS - THIRTY_DAYS_MS,
      "__relay_internal__pv__IGDPinnedThreadsRenderEnabledGKrelayprovider": True,
      "__relay_internal__pv__IGDMaxUnreadMessagesCountrelayprovider": 5,
      "__relay_internal__pv__IGDThreadListActionsEnabledGKrelayprovider": True,
   }


def test_only_the_pending_folder_carries_the_thirty_day_bound_as_a_string() -> None:
   """The parity gate for the two unread row reads an inbox load sends. Catches the bound sent
   with the inbox folder, or as a number."""

   inbox = build_folder_unread_rows_request(
      a_bootstrapped_session(), iris_device_id=DEVICE_ID, folder="INBOX", now_ms=NOW_MS
   )
   pending = build_folder_unread_rows_request(
      a_bootstrapped_session(), iris_device_id=DEVICE_ID, folder="PENDING", now_ms=NOW_MS
   )
   body = parse_qs(inbox.content.decode("utf-8")) if inbox.content else {}

   assert body["doc_id"] == [UNREAD_ROWS_DOC_ID]
   assert inbox.headers["referer"] == INBOX_REFERER
   assert sent_variables(inbox) == {"device_id_for_iris_subscription": DEVICE_ID, "folder": "INBOX"}
   assert sent_variables(pending) == {
      "device_id_for_iris_subscription": DEVICE_ID,
      "folder": "PENDING",
      "newer_than_timestamp_ms": str(NOW_MS - THIRTY_DAYS_MS),
   }


@pytest.mark.asyncio
async def test_the_first_page_hands_out_a_cursor_that_carries_its_mailbox() -> None:
   """Catches a page handing out the upstream's cursor alone, which the next page cannot be
   read with, and the next page read from a cursor split the wrong way round."""

   transport = ScriptedTransport(
      [
         json_response(recorded("inbox_first_page.json")),
         json_response(recorded("inbox_next_page.json")),
      ]
   )
   sender = make_paced(transport)
   session = a_bootstrapped_session()

   first = await read_inbox_page(sender, session)
   second = await read_inbox_page(sender, session, after=first.end_cursor)
   next_page_variables = sent_variables(transport.sent[1])

   assert first.end_cursor == f"{first_page_mailbox_id()}:{upstream_first_cursor()}"
   assert sent_variables(transport.sent[0])["device_id_for_iris_subscription"]
   assert next_page_variables["id"] == first_page_mailbox_id()
   assert next_page_variables["cursor"] == upstream_first_cursor()
   assert len(second.items) == 15
   assert second.end_cursor is not None
   assert second.end_cursor.startswith(f"{first_page_mailbox_id()}:")


@pytest.mark.asyncio
@pytest.mark.parametrize(
   "cursor",
   [
      "C000001ccc",
      ":C000001ccc",
      "90000000000000001:",
      "not-a-mailbox:C000001ccc",
   ],
)
async def test_a_cursor_no_inbox_page_handed_out_is_refused_before_anything_is_sent(
   cursor: str,
) -> None:
   """Catches a foreign cursor sent upstream with half its key, which answers as nothing rather
   than as an error."""

   transport = ScriptedTransport([])

   with pytest.raises(ValueError, match="inbox cursor"):
      await read_inbox_page(make_paced(transport), a_bootstrapped_session(), after=cursor)

   assert transport.sent == []


@pytest.mark.asyncio
async def test_the_unread_counts_read_the_inbox_then_the_pending_folder_as_one_load() -> None:
   """Catches the folders swapped, sent in the other order, or with two device ids where one
   inbox load holds one."""

   planted = unread_rows_with(lambda row: row.update({"marked_as_unread": True}))
   transport = ScriptedTransport(
      [json_response(planted), json_response(recorded("pending_unread_rows.json"))]
   )

   counts = await read_unread_counts(make_paced(transport), a_bootstrapped_session())
   sent = [sent_variables(request) for request in transport.sent]

   assert [variables["folder"] for variables in sent] == ["INBOX", "PENDING"]
   assert sent[0]["device_id_for_iris_subscription"] == sent[1]["device_id_for_iris_subscription"]
   assert counts == UnreadCounts(inbox=1, pending=0, inbox_has_more=True, pending_has_more=False)


def paced(transport: ScriptedTransport, client: AsyncClient) -> PacedSender:
   clock = FakeClock()
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)

   return PacedSender(transport, pacer, client._sender.pacing, client._sender.writes)


def two_inbox_pages() -> ScriptedTransport:
   return ScriptedTransport(
      [
         json_response(recorded("inbox_first_page.json")),
         json_response(recorded("inbox_next_page.json")),
      ]
   )


@pytest.mark.asyncio
async def test_the_async_inbox_walk_crosses_to_the_next_page_query() -> None:
   """Catches a walk that asks the first page query again for page two, or stops at its end."""

   transport = two_inbox_pages()
   client = AsyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR)
   await client._sender.aclose()
   client._sender = paced(transport, client)

   try:
      threads = [thread async for thread in client.direct.iter_inbox(limit=20)]
   finally:
      await client.aclose()

   names = [
      parse_qs(request.content.decode("utf-8"))["fb_api_req_friendly_name"][0]
      for request in transport.sent
      if request.content
   ]

   assert len(threads) == 20
   assert names == ["PolarisDirectInboxQuery", "IGDThreadListOffMsysPaginationQuery"]


def test_the_blocking_inbox_walk_crosses_to_the_next_page_query() -> None:
   """The same walk on the blocking surface, each page read on the loop thread."""

   transport = two_inbox_pages()

   with SyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR) as client:
      client._loop.run(client._impl._sender.aclose(), operation="the scripted sender swap")
      client._impl._sender = paced(transport, client._impl)
      threads = list(client.direct.iter_inbox(limit=16))

   assert len(threads) == 16
   assert sent_variables(transport.sent[1])["id"] == first_page_mailbox_id()


class FakeDirect:
   def __init__(self, pages: list[Page[DirectThread]]) -> None:
      self.pages = pages
      self.cursors: list[str | None] = []

   def inbox(self, *, after: str | None = None) -> Page[DirectThread]:
      self.cursors.append(after)

      return self.pages[len(self.cursors) - 1]

   def message_requests(self) -> MessageRequests:
      return parse_message_requests(recorded("message_requests.json"))

   def unread_counts(self) -> UnreadCounts:
      return UnreadCounts(inbox=3, pending=0, inbox_has_more=True, pending_has_more=False)


class FakeInboxClient:
   def __init__(self, pages: list[Page[DirectThread]]) -> None:
      self.session = Session(sessionid="s", ds_user_id="1234567890", csrftoken="c")
      self.direct = FakeDirect(pages)
      self.closed = False

   def close(self) -> None:
      self.closed = True


def run_command(argv: list[str], client: FakeInboxClient) -> tuple[int, str]:
   out = io.StringIO()

   def factory(path: Path, *, user_agent: str | None = None) -> Any:
      return client

   code = main(
      ["--session", "unused.json", *argv],
      environment={},
      client_factory=factory,
      stdout=out,
      stderr=io.StringIO(),
   )

   return code, out.getvalue()


def recorded_pages() -> list[Page[DirectThread]]:
   first = parse_inbox_page(recorded("inbox_first_page.json")).page
   second = parse_inbox_next_page(recorded("inbox_next_page.json")).page
   last = Page(items=second.items, has_next_page=False, end_cursor=None)

   return [replace(first, end_cursor="1:k1"), last]


def test_dumpsta_inbox_walks_on_the_pages_own_cursor_and_stops_on_its_terminator() -> None:
   """Catches the command passing its first cursor again, or reading past a last page when
   ``--pages`` allows more."""

   client = FakeInboxClient(recorded_pages())

   code, out = run_command(["--json", "inbox", "--pages", "5"], client)
   payload = json.loads(out)

   assert code == 0
   assert client.direct.cursors == [None, "1:k1"]
   assert payload["pages_read"] == 2
   assert payload["thread_count"] == 30
   assert payload["more_available"] is False
   assert sum(thread["is_unread"] for thread in payload["threads"]) == 1
   assert client.closed


def test_dumpsta_unread_marks_a_count_taken_over_part_of_a_folder() -> None:
   """Catches a partial count printed as if it were the whole folder's."""

   code, out = run_command(["unread"], FakeInboxClient([]))

   assert code == 0
   assert out.strip() == "unread inbox: 3+  pending requests: 0"


def test_dumpsta_message_requests_prints_both_folders() -> None:
   """Catches a folder left out of the JSON form."""

   code, out = run_command(["--json", "message-requests"], FakeInboxClient([]))
   payload = json.loads(out)

   assert code == 0
   assert payload == {
      "command": "message-requests",
      "pending": [],
      "spam": [],
      "pending_has_more": False,
      "spam_has_more": False,
   }
