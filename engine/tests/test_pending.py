"""Gates on ``dumpstagram.pending``, the non-blocking entry point, release phase 2 item 4.

Five defects live here. ``submit`` can block until the call finishes, which is the stall it
exists to remove. Concurrent calls can cross their answers, or overlap on the wire past the
pacer. A failure can lose the seam note, gain it twice, or arrive as a bare ``CancelledError``.
A write submitted can escape the write path. And a name that does not answer once, or a private
one, can be started rather than refused.

Every response is canned. Nothing in this file touches the network.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import replace
from typing import Any
from urllib.parse import parse_qs

import pytest

from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import Request, Response
from dumpstagram.behavior import FAST
from dumpstagram.client import SyncClient
from dumpstagram.errors import OperationCancelled, RateLimited, SchemaChanged
from dumpstagram.models import Message, Page
from dumpstagram.pending import PendingCall, submit
from tests.test_direct import a_bootstrapped_session, json_response
from tests.test_parse import node
from tests.test_thread_route import detail_payload

THREADS = [f"178000000000000{index:02d}" for index in range(12)]
BROKEN_THREAD = "17800000000000099"
"""A thread whose open answers with no thread at all, which the mapper refuses."""

SEND_ANSWER = {
   "data": {
      "xig_direct_text_send_with_slide_messaging_response": {
         "message_id": "mid.$sent",
         "id": "mid.$sent",
         "timestamp_ms": "1758412345678",
      }
   }
}


class KeyedTransport:
   """Answers each request from its own variables, holds every answer until ``gate`` is set, and
   records how many requests were in flight at once."""

   def __init__(self, *, held: bool = False) -> None:
      self.gate = threading.Event()
      self.in_flight = 0
      self.max_in_flight = 0
      self.sent: list[str] = []
      self.started = threading.Event()

      if not held:
         self.gate.set()

   async def send(self, request: Request) -> Response:
      self.in_flight += 1
      self.max_in_flight = max(self.max_in_flight, self.in_flight)
      self.started.set()

      try:
         while not self.gate.is_set():
            await asyncio.sleep(0.005)

         await asyncio.sleep(0.002)
         name = request.headers.get("x-fb-friendly-name", "document")
         self.sent.append(name)
         variables = json.loads(parse_qs((request.content or b"").decode())["variables"][0])

         if name == "IGDThreadDetailQuery" and variables["thread_fbid"] == BROKEN_THREAD:
            return json_response({"data": {}})

         if name == "IGDThreadDetailQuery":
            fbid = variables["thread_fbid"]
            nodes = [node(id=f"mid.$for-{fbid}", thread_fbid=fbid)]

            return json_response(detail_payload(nodes))

         if name == "IGDirectTextSendMutation":
            return json_response(SEND_ANSWER)

         return json_response({"data": {"unexpected": None}})
      finally:
         self.in_flight -= 1

   async def aclose(self) -> None:
      return None


def a_client(transport: KeyedTransport, **behavior: Any) -> SyncClient:
   client = SyncClient(a_bootstrapped_session(), behavior=replace(FAST, **behavior))
   inner = client._impl
   inner._sender = PacedSender(transport, Pacer(), inner._sender.pacing, inner._sender.writes)

   return client


def test_submit_returns_before_the_call_finishes() -> None:
   """Catches a submit that blocks, the stall it exists to remove. The answer is released 1 s
   after the submit by a timer, so a submit that waits for it returns late, not never."""

   transport = KeyedTransport(held=True)
   release = threading.Timer(1.0, transport.gate.set)

   with a_client(transport) as client:
      release.start()
      started_at = time.monotonic()
      pending = submit(client, "direct.messages", THREADS[0])
      returned_after = time.monotonic() - started_at

      assert returned_after < 0.5
      assert pending.done() is False

      page = pending.result(timeout=5)

   assert pending.done() is True
   assert isinstance(page, Page)
   assert [message.id for message in page.items] == [f"mid.$for-{THREADS[0]}"]


def test_concurrent_calls_on_one_client_each_get_their_own_answer_one_at_a_time() -> None:
   """Catches answers crossing between calls, or two requests on the wire at once."""

   transport = KeyedTransport()

   with a_client(transport) as client:
      reads = [submit(client, "direct.messages", fbid) for fbid in THREADS]
      send = submit(client, "direct.send", THREADS[0], "hello")
      pages = [pending.result(timeout=10) for pending in reads]
      sent = send.result(timeout=10)

   newest: list[Message] = [page.items[0] for page in pages]

   assert [message.id for message in newest] == [f"mid.$for-{fbid}" for fbid in THREADS]
   assert sent.id == "mid.$sent"
   assert transport.max_in_flight == 1
   assert transport.sent.count("IGDirectTextSendMutation") == 1


def test_a_failure_arrives_as_itself_with_one_seam_note() -> None:
   """Catches the note dropped, or added again on every look at the result."""

   transport = KeyedTransport()

   with a_client(transport) as client:
      pending = submit(client, "direct.messages", BROKEN_THREAD)
      failures: list[SchemaChanged] = []

      for _ in range(2):
         with pytest.raises(SchemaChanged) as raised:
            pending.result(timeout=5)

         failures.append(raised.value)

   notes = [note for note in failures[1].__notes__ if "operation: direct.messages" in note]

   assert failures[0] is failures[1]

   assert len(notes) == 1


def test_a_cancelled_call_raises_operation_cancelled() -> None:
   transport = KeyedTransport(held=True)

   with a_client(transport) as client:
      pending = submit(client, "direct.messages", THREADS[0])
      assert transport.started.wait(5)

      assert pending.cancel() is True

      with pytest.raises(OperationCancelled, match="direct.messages"):
         pending.result(timeout=5)

      transport.gate.set()


def test_a_timeout_leaves_the_call_running() -> None:
   transport = KeyedTransport(held=True)

   with a_client(transport) as client:
      pending = submit(client, "direct.messages", THREADS[0])

      with pytest.raises(TimeoutError):
         pending.result(timeout=0.05)

      transport.gate.set()

      assert pending.result(timeout=5).items


def test_a_submitted_write_still_takes_the_write_path() -> None:
   """Catches a submit that reaches the transport around the budget."""

   transport = KeyedTransport()

   with a_client(transport, write_budget_per_hour=0) as client:
      pending = submit(client, "direct.send", THREADS[0], "hello")

      with pytest.raises(RateLimited):
         pending.result(timeout=5)

   assert transport.sent == []


@pytest.mark.parametrize("operation", ["_watch_for_checkpoint", "direct._client", "_sender"])
def test_a_private_name_is_refused_before_anything_starts(operation: str) -> None:
   """Catches a private coroutine, such as the checkpoint watch, reachable through submit."""

   transport = KeyedTransport()

   with a_client(transport) as client:
      with pytest.raises(ValueError, match="not a public method"):
         submit(client, operation, None)

   assert transport.sent == []


@pytest.mark.parametrize("operation", ["nothing", "direct.nothing"])
def test_an_unknown_name_is_refused(operation: str) -> None:
   with a_client(KeyedTransport()) as client:
      with pytest.raises(ValueError, match="not a method of the client"):
         submit(client, operation)


@pytest.mark.parametrize("operation", ["session", "direct.iter_messages"])
def test_what_does_not_answer_once_is_refused_before_anything_starts(operation: str) -> None:
   transport = KeyedTransport()

   with a_client(transport) as client:
      with pytest.raises(ValueError, match="does not answer once"):
         submit(client, operation, THREADS[0])

   assert transport.sent == []


def test_the_listener_cannot_be_submitted() -> None:
   with a_client(KeyedTransport()) as client:
      with pytest.raises(ValueError, match="does not answer once"):
         submit(client, "events")


def test_a_pending_call_is_not_built_directly() -> None:
   with pytest.raises(TypeError):
      PendingCall()
