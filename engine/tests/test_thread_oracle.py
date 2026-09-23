"""The recorded oracle: one whole thread, read offline, checked against a second implementation.

`fixtures/thread_oracle/pages.json.gz` is every page of one real direct thread as the upstream
sent it, pseudonymised by `scripts/build_thread_oracle.py` and served back here by a transport
that answers each request with the page recorded for the cursor it carries. A cursor nobody
recorded fails the read, so the replay only reaches the end by walking the same path the live
read walked.

`fixtures/thread_oracle/independent_export.json` is the other half, and it is why these gates
do not derive their expectations from the code they gate. It is the prior project's `ghost`
export of the same thread, made a day before the capture by a separate Node implementation,
pseudonymised with the same mapping. Every assertion against it is scoped to the window ghost
covered, because the thread kept growing after ghost read it, and an absolute count would fail
on a correct run.

One message ghost holds was not in any page the upstream sent a day later. The fixture names it
under `absent_from_capture`, and the exemption is itself gated: every exempted id must be
missing from the raw recorded pages as text, which no mapper touches. A message the mapper drops
is present in the raw pages, so it cannot hide behind the exemption.

The fixtures are local. They describe a private conversation with a third party who never agreed
to have its shape published, pseudonymised or not, so `tests/fixtures/thread_oracle/` is
gitignored. A checkout without them skips this module and says why, and a skip is reported as a
skip, never as a pass. Rebuilding them needs a capture from
`probes/capture_thread_oracle.py` and `scripts/build_thread_oracle.py`.

The hazard this file cannot remove. Green here means the mapper and the pagination loop agree
with a capture from 2026-09-22 and with an export from 2026-09-21. It says nothing about what
the upstream sends today.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import pytest

from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import Request, Response
from dumpstagram._private.web.documents import API_GRAPHQL_URL
from dumpstagram.aio import AsyncClient
from dumpstagram.models import Message
from tests.test_direct import FakeClock, a_bootstrapped_session

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "thread_oracle"

fixtures_missing = not (FIXTURES / "pages.json.gz").exists()

if fixtures_missing:
   pytest.skip(
      "the recorded oracle is local and absent here, build it with scripts/build_thread_oracle.py",
      allow_module_level=True,
   )

RECORDED_PAGES: list[dict[str, Any]] = json.loads(
   gzip.decompress((FIXTURES / "pages.json.gz").read_bytes())
)

INDEPENDENT: dict[str, Any] = json.loads(
   (FIXTURES / "independent_export.json").read_text(encoding="utf-8")
)


class RecordedThread:
   """Answers a thread page request with the page recorded for the cursor it carries."""

   def __init__(self, pages: list[dict[str, Any]]) -> None:
      self.pages_by_cursor = {page["after"]: page["payload"] for page in pages}
      self.cursors_requested: list[str | None] = []

   async def send(self, request: Request) -> Response:
      assert request.content is not None

      variables = json.loads(parse_qs(request.content.decode("utf-8"))["variables"][0])
      after = variables["after"]
      self.cursors_requested.append(after)

      if after not in self.pages_by_cursor:
         raise AssertionError(f"no page was recorded for cursor {after!r}")

      return Response(
         status_code=200,
         headers={"content-type": "application/json; charset=utf-8"},
         content=json.dumps(self.pages_by_cursor[after]).encode("utf-8"),
         final_url=API_GRAPHQL_URL,
      )


async def read_the_whole_thread() -> tuple[list[Message], RecordedThread, int]:
   thread = RecordedThread(RECORDED_PAGES)
   clock = FakeClock()
   client = AsyncClient(a_bootstrapped_session())
   client._sender = PacedSender(thread, Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0))

   messages: list[Message] = []
   pages_read = 0
   after: str | None = None

   try:
      while True:
         page = await client.thread_messages(INDEPENDENT["thread_fbid"], after=after)
         pages_read += 1
         messages.extend(page.items)

         if not page.has_next_page:
            break

         after = page.end_cursor
   finally:
      await client.aclose()

   return messages, thread, pages_read


def milliseconds(moment: datetime) -> int:
   return round(moment.astimezone(UTC).timestamp() * 1000)


def in_the_independent_window(message: Message) -> bool:
   low, high = INDEPENDENT["window_ms"]

   return low <= milliseconds(message.sent_at) <= high


def raw_pages_text() -> str:
   return json.dumps([page["payload"] for page in RECORDED_PAGES])


def test_the_fixtures_hold_a_whole_thread_and_a_whole_independent_export() -> None:
   """Positive control for every gate below: an empty fixture would make each one vacuous."""

   assert len(RECORDED_PAGES) > 1
   assert RECORDED_PAGES[0]["after"] is None
   assert len(INDEPENDENT["messages"]) > 1000


@pytest.mark.asyncio
async def test_the_read_follows_every_recorded_cursor_and_stops_on_the_terminator() -> None:
   """Catches a loop that stops on a short page, or follows a cursor the upstream never sent."""

   _, thread, pages_read = await read_the_whole_thread()

   assert pages_read == len(RECORDED_PAGES)
   assert thread.cursors_requested == [page["after"] for page in RECORDED_PAGES]


@pytest.mark.asyncio
async def test_no_message_is_read_twice() -> None:
   """Catches an overlapping page or a cursor that restarts the connection part way."""

   messages, _, _ = await read_the_whole_thread()
   identifiers = [message.id for message in messages]

   assert len(identifiers) == len(set(identifiers))


@pytest.mark.asyncio
async def test_the_window_holds_exactly_the_messages_the_independent_export_holds() -> None:
   """Catches a message the mapper drops or invents, judged by an implementation it is not."""

   messages, _, _ = await read_the_whole_thread()

   read_in_window = {message.id for message in messages if in_the_independent_window(message)}
   independent = {record["id"] for record in INDEPENDENT["messages"]}
   absent_upstream = set(INDEPENDENT["absent_from_capture"])

   assert read_in_window == independent - absent_upstream


def test_every_exempted_message_is_missing_from_the_raw_pages_too() -> None:
   """Catches the exemption list hiding a message the mapper dropped, since a dropped message
   is still in the raw pages. The present id is the control that the text search can hit."""

   raw = raw_pages_text()
   absent_upstream = INDEPENDENT["absent_from_capture"]
   present = next(
      record["id"] for record in INDEPENDENT["messages"] if record["id"] not in absent_upstream
   )

   assert f'"{present}"' in raw

   for identifier in absent_upstream:
      assert f'"{identifier}"' not in raw, identifier


@pytest.mark.asyncio
async def test_every_message_in_the_window_agrees_with_the_independent_export() -> None:
   """Catches a field mapped from the wrong key: a misread timestamp, sender or content type."""

   messages, _, _ = await read_the_whole_thread()
   read_by_id = {message.id: message for message in messages}

   disagreements = []

   absent_upstream = set(INDEPENDENT["absent_from_capture"])

   for record in INDEPENDENT["messages"]:
      if record["id"] in absent_upstream:
         continue

      message = read_by_id[record["id"]]

      read = (milliseconds(message.sent_at), message.sender.fbid, message.content_type)
      expected = (int(record["timestamp_ms"]), record["sender_fbid"], record["content_type"])

      if read != expected:
         disagreements.append((record["id"], read, expected))

   assert disagreements == []
