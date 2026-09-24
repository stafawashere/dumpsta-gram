"""Gates on send_message and unsend_message, the Step 18 table in the build plan.

Seven defect classes live here.

The client identifier can be built wrong, or reused across sends, and then a thread read can no
longer find the message a send created. The browser's construction was read off
``IGDOfflineThreadingID``, and one browser send and one engine send were observed with it.

The request can drift from the fourteen variables the browser's composer sent, which is the
single-request parity gate for this step, or name the thread by one of its other two ids.

The answer can be misread: an ``id`` that is not the ``message_id``, or a ``sent_at`` taken from
the local clock instead of the upstream's ``timestamp_ms``.

The reconciling read can match the wrong message. Two sends of the same text are two messages,
and only the echoed ``offline_threading_id`` tells them apart.

The unsend can name the thread by the wrong id. It takes the 39-digit ``thread_id`` that only
the thread open carries, and neither of the ids the reads are keyed on.

A write can leave by a path other than ``send_write``, or be sent again after an error answer.

And the CLI can cross its arguments or reach a client with an id it should have refused.

Every response is canned. The ids are shaped like the ones observed on 2026-09-23 and are not
the observed values. Nothing in this file touches the network.
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import pytest

from dumpstagram._cli.main import main
from dumpstagram._core.direct import find_sent_message
from dumpstagram._core.pacer import PacingPolicy, WritePolicy
from dumpstagram._core.writes.direct import send_message, unsend_message
from dumpstagram._private.transport import Request
from dumpstagram._private.web.parse.direct import parse_message
from dumpstagram._private.web.requests.direct import offline_threading_id
from dumpstagram.errors import SchemaChanged, UpstreamRejected
from dumpstagram.models import Message, SentMessage
from dumpstagram.session import Session
from tests.test_direct import (
   ScriptedTransport,
   a_bootstrapped_session,
   json_response,
   make_paced,
   sent_variables,
)
from tests.test_parse import node

API_GRAPHQL = "https://www.instagram.com/api/graphql"

THREAD_FBID = "1000000000000001"
THREAD_KEY = "200000000000002"
THREAD_ID = "340282366841710300000000000000000000001"
THREAD_PAGE = f"https://www.instagram.com/direct/t/{THREAD_FBID}/"

SENT_ID = "mid.$cAD8FwPSNk0anAPH8c2gzAAAAAAAA"
TIMESTAMP_MS = "1790190597235"
TEXT = "a message"

SEND_DOC_ID = "26911679871773184"
UNSEND_DOC_ID = "26948700068153789"
DETAIL_DOC_ID = "28730473946590056"

OBSERVED_VARIABLE_ORDER = [
   "ig_thread_igid",
   "offline_threading_id",
   "recipient_igids",
   "replied_to_client_context",
   "replied_to_item_id",
   "reply_to_message_id",
   "sampled",
   "text",
   "mentions",
   "mentioned_user_ids",
   "commands",
   "forwarded_from_thread_id",
   "is_forwarded_from_own_message",
   "send_attribution",
]
"""The keys the browser's composer sent on 2026-09-23, in the order it sent them."""


def send_answer(*, message_id: str = SENT_ID, echoed_id: str = SENT_ID) -> dict[str, Any]:
   """The 310 byte answer both observed sends got, with synthetic ids."""

   return {
      "data": {
         "xig_direct_text_send_with_slide_messaging_response": {
            "message_id": message_id,
            "timestamp_ms": TIMESTAMP_MS,
            "id": echoed_id,
         }
      },
      "extensions": {"is_final": True},
   }


def unsend_answer(applied: Any = True) -> dict[str, Any]:
   """The 161 byte answer both observed unsends got."""

   return {"data": {"direct_unsend_message": applied}, "extensions": {"is_final": True}}


def thread_open(*, thread_id: str = THREAD_ID) -> dict[str, Any]:
   """A thread open with its three ids apart, as the new thread's open carried them."""

   thread = {
      "id": THREAD_FBID,
      "thread_fbid": THREAD_FBID,
      "thread_key": THREAD_KEY,
      "thread_id": thread_id,
      "slide_messages": {
         "edges": [{"cursor": "c", "node": node(id=SENT_ID, message_id=SENT_ID)}],
         "page_info": {"has_next_page": False, "end_cursor": None},
      },
   }

   return {
      "data": {"get_slide_thread_nullable": {"as_ig_direct_thread": thread, "id": THREAD_FBID}},
      "extensions": {"is_final": True},
   }


def body_of(request: Request) -> dict[str, list[str]]:
   return parse_qs(request.content.decode("utf-8")) if request.content else {}


def test_the_identifier_is_built_as_the_browser_builds_it() -> None:
   """Catches a construction other than IGDOfflineThreadingID's. The browser's send carried
   7508603579515594871, and its mark read named the same message's clock as 1790190596465. The
   low 22 bits of the id are 59511."""

   assert offline_threading_id(1790190596465, 59511) == "7508603579515594871"


def test_the_identifier_keeps_only_22_random_bits() -> None:
   """Catches the random number written in whole, which would overwrite the clock bits."""

   assert offline_threading_id(1790191252480, 0xFFFFFFFF) == "7508606331046068223"


def test_the_identifier_is_cut_to_63_bits() -> None:
   """Catches the cut dropped, which a clock past 2**41 ms, in 2039, turns into a 64-bit id."""

   assert offline_threading_id(2**41 + 5, 1) == "20971521"


@pytest.mark.asyncio
async def test_each_send_carries_a_fresh_identifier_and_returns_it() -> None:
   """Catches one identifier reused across sends, and a returned one that is not the one sent.
   The clock and the random source are real here, as they are in a live send."""

   transport = ScriptedTransport([json_response(send_answer()), json_response(send_answer())])
   sender = make_paced(transport)
   session = a_bootstrapped_session()

   first = await send_message(sender, session, THREAD_FBID, TEXT)
   second = await send_message(sender, session, THREAD_FBID, TEXT)

   sent_ids = [sent_variables(request)["offline_threading_id"] for request in transport.sent]

   assert sent_ids[0] != sent_ids[1]
   assert [first.offline_threading_id, second.offline_threading_id] == sent_ids


@pytest.mark.asyncio
async def test_a_send_is_the_one_request_the_browser_sent() -> None:
   """The parity gate for the send. Catches a variable the composer did not send or sent in
   another order, the thread named by its thread_key or its thread_id, a text not wrapped as the
   composer wraps it, another document, another referer, and a request beside the write."""

   transport = ScriptedTransport([json_response(send_answer())])

   await send_message(
      make_paced(transport),
      a_bootstrapped_session(),
      THREAD_FBID,
      TEXT,
      clock_ms=lambda: 1790190596465,
      random_bits=lambda: 59511,
   )

   assert len(transport.sent) == 1

   request = transport.sent[0]
   body = body_of(request)
   variables = sent_variables(request)

   assert request.url == API_GRAPHQL
   assert body["doc_id"] == [SEND_DOC_ID]
   assert body["fb_api_req_friendly_name"] == ["IGDirectTextSendMutation"]
   assert request.headers["x-fb-friendly-name"] == "IGDirectTextSendMutation"
   assert request.headers["referer"] == THREAD_PAGE
   assert list(variables) == OBSERVED_VARIABLE_ORDER
   assert variables == {
      "ig_thread_igid": THREAD_FBID,
      "offline_threading_id": "7508603579515594871",
      "recipient_igids": None,
      "replied_to_client_context": None,
      "replied_to_item_id": None,
      "reply_to_message_id": None,
      "sampled": None,
      "text": {"sensitive_string_value": TEXT},
      "mentions": [],
      "mentioned_user_ids": [],
      "commands": None,
      "forwarded_from_thread_id": None,
      "is_forwarded_from_own_message": None,
      "send_attribution": "igd_web_chat_tab:in_thread",
   }


@pytest.mark.asyncio
async def test_the_answer_maps_into_a_sent_message() -> None:
   """Catches ``sent_at`` taken from the local clock rather than the upstream's timestamp, and
   the id or the thread read from anywhere but the answer and the call."""

   transport = ScriptedTransport([json_response(send_answer())])

   sent = await send_message(
      make_paced(transport),
      a_bootstrapped_session(),
      THREAD_FBID,
      TEXT,
      clock_ms=lambda: 1_000_000_000_000,
      random_bits=lambda: 1,
   )

   assert sent == SentMessage(
      id=SENT_ID,
      thread_fbid=THREAD_FBID,
      sent_at=datetime(2026, 9, 23, 19, 9, 57, 235000, tzinfo=UTC),
      offline_threading_id=str((1_000_000_000_000 << 22) | 1),
   )


@pytest.mark.asyncio
async def test_an_answer_whose_id_is_not_its_message_id_is_a_schema_change() -> None:
   """Catches two different identifiers in one answer, where one was measured, taken silently."""

   answer = send_answer(echoed_id="mid.$cSOMETHINGELSE0000000000000000")
   transport = ScriptedTransport([json_response(answer)])

   with pytest.raises(SchemaChanged):
      await send_message(make_paced(transport), a_bootstrapped_session(), THREAD_FBID, TEXT)


@pytest.mark.asyncio
@pytest.mark.parametrize(
   ("thread", "text"),
   [(THREAD_ID, TEXT), ("thread-with-letters", TEXT), (THREAD_FBID, "")],
)
async def test_a_send_that_cannot_be_right_is_refused_before_anything_is_sent(
   thread: str, text: str
) -> None:
   """Catches the 39-digit thread_id passed as the thread, which the send was never observed
   taking, and an empty message reaching the upstream."""

   transport = ScriptedTransport([])

   with pytest.raises(ValueError):
      await send_message(make_paced(transport), a_bootstrapped_session(), thread, text)

   assert transport.sent == []


@pytest.mark.asyncio
async def test_the_send_departs_only_through_the_write_slot() -> None:
   """Catches a send made with ``sender.send`` rather than ``send_write``. On an account whose
   writes are stopped the write slot refuses before the transport sees anything."""

   transport = ScriptedTransport([json_response(send_answer())])
   sender = make_paced(transport)
   sender.pacer.stop_writes()

   with pytest.raises(UpstreamRejected):
      await send_message(sender, a_bootstrapped_session(), THREAD_FBID, TEXT)

   assert transport.sent == []


@pytest.mark.asyncio
async def test_an_error_envelope_on_a_send_raises_and_departs_once() -> None:
   """Catches a message sent again after the upstream answered it with an error, which would
   deliver it twice. The write stop is off, so it cannot hide a capability that retries."""

   envelope = {"error": "a_code_no_finding_explains"}
   transport = ScriptedTransport([json_response(envelope), json_response(envelope)])
   sender = make_paced(transport).with_pacing(
      PacingPolicy(), WritePolicy(stop_after_unrecognised_rejection=False)
   )

   with pytest.raises(UpstreamRejected):
      await send_message(sender, a_bootstrapped_session(), THREAD_FBID, TEXT)

   assert len(transport.sent) == 1


def test_the_read_carries_the_identifier_a_send_generated() -> None:
   """Catches ``offline_threading_id`` left unmapped, which leaves the reconciling read nothing
   to match on."""

   message = parse_message(node(offline_threading_id="7508606331043829411"), "node")

   assert message.offline_threading_id == "7508606331043829411"


def test_a_node_without_the_identifier_reads_as_none() -> None:
   """Catches a page recorded before the field was mapped refused whole."""

   bare = node()
   del bare["offline_threading_id"]

   assert parse_message(bare, "node").offline_threading_id is None


def test_the_reconciling_read_matches_the_identifier_and_not_the_text() -> None:
   """Catches a match on text or on position. Two messages with the same text from the same
   sender, and only the second is the one the send created."""

   earlier = parse_message(
      node(id="mid.$cEARLIER", message_id="mid.$cEARLIER", offline_threading_id="1"), "node"
   )
   created = parse_message(
      node(id="mid.$cCREATED", message_id="mid.$cCREATED", offline_threading_id="2"), "node"
   )
   messages: list[Message] = [earlier, created]

   assert earlier.text == created.text
   assert find_sent_message(messages, "2") is created
   assert find_sent_message(messages, "3") is None


@pytest.mark.asyncio
async def test_an_unsend_opens_the_thread_and_names_it_by_its_thread_id() -> None:
   """The parity gate for the unsend. Catches the unsend naming the thread by its fbid or its
   key, which is what the reads take, instead of the thread_id only the open carries, and
   a request beyond the open and the write."""

   transport = ScriptedTransport([json_response(thread_open()), json_response(unsend_answer())])

   await unsend_message(make_paced(transport), a_bootstrapped_session(), THREAD_FBID, SENT_ID)

   assert len(transport.sent) == 2

   opened, unsent = transport.sent

   assert body_of(opened)["doc_id"] == [DETAIL_DOC_ID]
   assert sent_variables(opened)["thread_fbid"] == THREAD_FBID
   assert unsent.url == API_GRAPHQL
   assert body_of(unsent)["doc_id"] == [UNSEND_DOC_ID]
   assert unsent.headers["x-fb-friendly-name"] == "IGDMessageUnsendDialogOffMsysMutation"
   assert unsent.headers["referer"] == THREAD_PAGE
   assert sent_variables(unsent) == {"message_id": SENT_ID, "send_data": {"thread_id": THREAD_ID}}


@pytest.mark.asyncio
async def test_an_unsend_answered_false_did_not_apply() -> None:
   """Catches an unsend reported done when the upstream's own answer says it was not."""

   transport = ScriptedTransport(
      [json_response(thread_open()), json_response(unsend_answer(False))]
   )

   with pytest.raises(UpstreamRejected) as raised:
      await unsend_message(make_paced(transport), a_bootstrapped_session(), THREAD_FBID, SENT_ID)

   assert raised.value.code == "message_not_unsent"


@pytest.mark.asyncio
async def test_an_unsend_answer_that_is_not_a_boolean_is_a_schema_change() -> None:
   """Catches a changed answer read as truthy, which would report an unsend nobody confirmed."""

   transport = ScriptedTransport(
      [json_response(thread_open()), json_response(unsend_answer("yes"))]
   )

   with pytest.raises(SchemaChanged):
      await unsend_message(make_paced(transport), a_bootstrapped_session(), THREAD_FBID, SENT_ID)


@pytest.mark.asyncio
async def test_the_unsend_departs_only_through_the_write_slot() -> None:
   """Catches an unsend made with ``sender.send``. With writes stopped the open, a read, still
   departs and the unsend does not."""

   transport = ScriptedTransport([json_response(thread_open()), json_response(unsend_answer())])
   sender = make_paced(transport)
   sender.pacer.stop_writes()

   with pytest.raises(UpstreamRejected):
      await unsend_message(sender, a_bootstrapped_session(), THREAD_FBID, SENT_ID)

   assert len(transport.sent) == 1


@pytest.mark.asyncio
async def test_a_thread_open_without_a_thread_id_sends_no_unsend() -> None:
   """Catches an unsend sent with a missing or empty thread id."""

   opened = thread_open()
   del opened["data"]["get_slide_thread_nullable"]["as_ig_direct_thread"]["thread_id"]
   transport = ScriptedTransport([json_response(opened), json_response(unsend_answer())])

   with pytest.raises(SchemaChanged):
      await unsend_message(make_paced(transport), a_bootstrapped_session(), THREAD_FBID, SENT_ID)

   assert len(transport.sent) == 1


@pytest.mark.asyncio
async def test_an_unsend_of_something_that_is_not_a_message_id_sends_nothing() -> None:
   """Catches an offline_threading_id or a thread id passed as the message."""

   transport = ScriptedTransport([])

   with pytest.raises(ValueError):
      await unsend_message(
         make_paced(transport), a_bootstrapped_session(), THREAD_FBID, "7508603579515594871"
      )

   assert transport.sent == []


class RecordingClient:
   def __init__(self) -> None:
      self.session = Session(sessionid="s", ds_user_id="1234567890", csrftoken="c")
      self.calls: list[tuple[str, ...]] = []

   def send_message(self, thread_fbid: str, text: str) -> SentMessage:
      self.calls.append(("send_message", thread_fbid, text))

      return SentMessage(
         id=SENT_ID,
         thread_fbid=thread_fbid,
         sent_at=datetime(2026, 9, 23, 19, 9, 57, tzinfo=UTC),
         offline_threading_id="7508603579515594871",
      )

   def unsend_message(self, thread_fbid: str, message_id: str) -> None:
      self.calls.append(("unsend_message", thread_fbid, message_id))

   def close(self) -> None:
      pass


def run_cli(argv: list[str], client: RecordingClient) -> tuple[int, str]:
   out = io.StringIO()

   def factory(path: Path, *, user_agent: str | None = None) -> Any:
      return client

   code = main(argv, environment={}, client_factory=factory, stdout=out, stderr=io.StringIO())

   return code, out.getvalue()


def test_the_cli_sends_the_text_into_the_named_thread() -> None:
   """Catches the CLI crossing the thread and the text, and dropping the identifier from its
   output, which is what ``dumpsta thread`` matches the message by."""

   client = RecordingClient()

   code, out = run_cli(["--json", "--session", "s.json", "send-message", THREAD_FBID, TEXT], client)

   assert code == 0
   assert client.calls == [("send_message", THREAD_FBID, TEXT)]
   assert json.loads(out) == {
      "command": "send-message",
      "thread_fbid": THREAD_FBID,
      "message": {
         "id": SENT_ID,
         "thread_fbid": THREAD_FBID,
         "sent_at": "2026-09-23T19:09:57+00:00",
         "offline_threading_id": "7508603579515594871",
      },
   }


def test_the_cli_unsends_the_named_message() -> None:
   """Catches the CLI crossing the thread and the message id."""

   client = RecordingClient()

   code, out = run_cli(
      ["--json", "--session", "s.json", "unsend-message", THREAD_FBID, SENT_ID], client
   )

   assert code == 0
   assert client.calls == [("unsend_message", THREAD_FBID, SENT_ID)]
   assert json.loads(out) == {
      "command": "unsend-message",
      "thread_fbid": THREAD_FBID,
      "message_id": SENT_ID,
      "unsent": True,
   }


@pytest.mark.parametrize(
   "argv",
   [
      ["send-message", "not-a-thread", TEXT],
      ["unsend-message", THREAD_FBID, "7508603579515594871"],
   ],
)
def test_the_cli_refuses_a_wrong_id_before_opening_a_client(argv: list[str]) -> None:
   """Catches a malformed thread or message id reaching a client, where it becomes a request."""

   client = RecordingClient()

   with pytest.raises(SystemExit) as raised:
      run_cli(["--session", "s.json", *argv], client)

   assert raised.value.code == 2
   assert client.calls == []
