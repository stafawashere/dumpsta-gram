"""Gates on the write path, the Step 13 table in ``engine/docs/build-plan.md``.

No write capability exists yet, so every gate sends a write request built here through
``send_write`` over a paced sender and a fake wire. Each names the retry, the lost outcome or
the unpaced write it catches, and each is seen red by ``scripts/verify_write_safety_gates.py``.

Numbers the defaults promise are written out rather than read off a policy, so that turning a
default down cannot also turn its gate down.
"""

from __future__ import annotations

import ast
import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from dumpstagram._core.pacer import WRITES_STOPPED, Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.writing import send_write
from dumpstagram._private.transport import Request, Response, WriteRequest
from dumpstagram.aio import pacing_for, write_policy_for
from dumpstagram.behavior import FAST, PARITY, Behavior, Spacing
from dumpstagram.errors import OutcomeUnknown, RateLimited, TransportFailure, UpstreamRejected
from dumpstagram.session import Session

CORE = Path(__file__).resolve().parents[1] / "dumpstagram" / "_core"

RETRY_HELPERS = {"run_with_retries", "with_token_recovery"}

WRITE_URL = "https://example.invalid/write"
READ_URL = "https://example.invalid/read"

SHELL_BODY = b"<!DOCTYPE html><html><head></head><body></body></html>"
UNRECOGNISED_REJECTION_BODY = b'{"error": "a_code_no_finding_explains"}'


class FakeClock:
   """A monotonic clock that only advances when something sleeps on it."""

   def __init__(self) -> None:
      self.now = 0.0

   def __call__(self) -> float:
      return self.now

   async def sleep(self, seconds: float) -> None:
      self.now += seconds

      await asyncio.sleep(0)


class Wire:
   """Answers reads with an empty payload and writes as told, recording every departure."""

   def __init__(self, clock: FakeClock, write_answers: list[str] | None = None) -> None:
      self.clock = clock
      self.write_answers = list(write_answers or [])
      self.writes: list[float] = []
      self.reads: list[float] = []

   async def send(self, request: Request) -> Response:
      if request.url == READ_URL:
         self.reads.append(self.clock.now)

         return json_response(b"{}")

      self.writes.append(self.clock.now)
      answer = self.write_answers.pop(0) if self.write_answers else "applied"

      if answer == "timeout":
         raise TransportFailure("the read timed out")

      if answer == "throttle":
         raise RateLimited("slow down", retry_after=60.0)

      if answer == "shell":
         return Response(
            status_code=200,
            headers={"content-type": "text/html"},
            content=SHELL_BODY,
            final_url=request.url,
         )

      if answer == "unrecognised":
         return json_response(UNRECOGNISED_REJECTION_BODY)

      return json_response(b'{"data": {"applied": true}}')


def json_response(content: bytes) -> Response:
   return Response(
      status_code=200,
      headers={"content-type": "application/json"},
      content=content,
      final_url=WRITE_URL,
   )


def a_session() -> Session:
   session = Session(sessionid="sessionid-value", ds_user_id="1234567890", csrftoken="csrf-value")
   session.fb_dtsg = "fb-dtsg-value"

   return session


def a_write() -> WriteRequest:
   return WriteRequest(Request(method="POST", url=WRITE_URL, content=b"x"), operation="a_write")


def a_read() -> Request:
   return Request(method="POST", url=READ_URL)


def paced(wire: Wire, behavior: Behavior = PARITY) -> PacedSender:
   pacer = Pacer(clock=wire.clock, sleep=wire.clock.sleep, jitter=lambda: 0.0)

   return PacedSender(wire, pacer, pacing_for(behavior), write_policy_for(behavior))


def names_referenced(path: Path) -> set[str]:
   """Every identifier a module names in code, and every string equal to one, never prose."""

   found: set[str] = set()

   for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
      if isinstance(node, ast.Name):
         found.add(node.id)
      elif isinstance(node, ast.Attribute):
         found.add(node.attr)
      elif isinstance(node, ast.alias):
         found.add(node.name.rsplit(".", 1)[-1])
         if node.asname:
            found.add(node.asname)
      elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
         found.add(node.name)
      elif isinstance(node, ast.Constant) and isinstance(node.value, str):
         found.add(node.value)

   return found


@pytest.mark.asyncio
async def test_a_transport_failure_during_a_write_is_an_unknown_outcome() -> None:
   """Catches a network error reaching the caller, who might answer it by sending again."""

   wire = Wire(FakeClock(), ["timeout"])

   with pytest.raises(OutcomeUnknown) as raised:
      await send_write(paced(wire), a_session(), a_write())

   assert raised.value.operation == "a_write"


@pytest.mark.asyncio
async def test_the_unknown_outcome_chains_the_transport_failure() -> None:
   """Catches the network detail being dropped instead of kept on ``__cause__``."""

   wire = Wire(FakeClock(), ["timeout"])

   with pytest.raises(OutcomeUnknown) as raised:
      await send_write(paced(wire), a_session(), a_write())

   assert isinstance(raised.value.__cause__, TransportFailure)


@pytest.mark.asyncio
async def test_a_timed_out_write_departs_once() -> None:
   """Catches a write sent through the retry loop, which would send it again after a timeout."""

   wire = Wire(FakeClock(), ["timeout", "applied"])

   with pytest.raises(OutcomeUnknown):
      await send_write(paced(wire), a_session(), a_write())

   assert len(wire.writes) == 1


@pytest.mark.asyncio
async def test_a_shell_answer_to_a_write_departs_once() -> None:
   """Catches a write sent through the token recovery, which re-bootstraps and resends."""

   wire = Wire(FakeClock(), ["shell", "applied"])

   with pytest.raises(UpstreamRejected) as raised:
      await send_write(paced(wire), a_session(), a_write())

   assert raised.value.code == "html_app_shell"
   assert len(wire.writes) == 1


@pytest.mark.asyncio
async def test_a_shell_answer_clears_the_token() -> None:
   """Catches a refused token kept, which would make the caller's next call fail the same way."""

   session = a_session()
   wire = Wire(FakeClock(), ["shell"])

   with pytest.raises(UpstreamRejected):
      await send_write(paced(wire), session, a_write())

   assert session.fb_dtsg is None


@pytest.mark.asyncio
async def test_a_shell_answer_does_not_stop_later_writes() -> None:
   """Catches the shell counted as an unrecognised rejection, which would end all writing over
   a stale token the next call repairs."""

   wire = Wire(FakeClock(), ["shell", "applied"])
   sender = paced(wire)

   with pytest.raises(UpstreamRejected):
      await send_write(sender, a_session(), a_write())

   await send_write(sender, a_session(), a_write())

   assert len(wire.writes) == 2


@pytest.mark.asyncio
async def test_a_write_request_cannot_depart_twice() -> None:
   """Catches a write object sent a second time by whatever holds it."""

   wire = Wire(FakeClock())
   sender = paced(wire)
   write = a_write()

   await send_write(sender, a_session(), write)

   with pytest.raises(RuntimeError):
      await send_write(sender, a_session(), write)

   assert len(wire.writes) == 1


def test_write_modules_do_not_import_the_retry_helpers() -> None:
   """Catches a write capability reaching for a retry helper, with the scan's positive control
   on the module that does use both."""

   control = names_referenced(CORE / "tokens.py")
   assert control >= RETRY_HELPERS

   scanned = [*sorted((CORE / "writes").rglob("*.py")), CORE / "writing.py"]
   assert CORE / "writes" / "__init__.py" in scanned

   offenders = {
      str(path.relative_to(CORE)): sorted(names_referenced(path) & RETRY_HELPERS)
      for path in scanned
      if names_referenced(path) & RETRY_HELPERS
   }

   assert offenders == {}


@pytest.mark.asyncio
async def test_a_throttled_write_holds_the_account_and_does_not_resend() -> None:
   """Catches a throttled write slept through and sent again, and a hold kept to one request."""

   wire = Wire(FakeClock(), ["throttle", "throttle"])
   sender = paced(wire)

   with pytest.raises(RateLimited):
      await send_write(sender, a_session(), a_write())

   await sender.send(a_read())

   assert len(wire.writes) == 1
   assert wire.reads[0] - wire.writes[0] >= 60.0


@pytest.mark.asyncio
async def test_writes_are_spaced_by_the_write_floor_and_reads_are_not() -> None:
   """Catches an unspaced default for writes, and a write floor that also delays reads."""

   wire = Wire(FakeClock())
   sender = paced(wire)

   await send_write(sender, a_session(), a_write())
   await sender.send(a_read())
   await send_write(sender, a_session(), a_write())

   assert wire.writes[1] - wire.writes[0] >= 30.0
   assert wire.reads[0] - wire.writes[0] == pytest.approx(1.3)


@pytest.mark.asyncio
async def test_zero_write_spacing_leaves_the_budget_and_the_stop() -> None:
   """Catches a departure in spacing switching off the rest of the write policy with it."""

   unspaced = replace(PARITY, write_spacing=Spacing(floor_seconds=0.0, mean_jitter_seconds=0.0))

   budget_wire = Wire(FakeClock())
   budget_sender = paced(budget_wire, unspaced)

   for _ in range(30):
      await send_write(budget_sender, a_session(), a_write())

   with pytest.raises(RateLimited):
      await send_write(budget_sender, a_session(), a_write())

   stop_wire = Wire(FakeClock(), ["unrecognised"])
   stop_sender = paced(stop_wire, unspaced)

   with pytest.raises(UpstreamRejected):
      await send_write(stop_sender, a_session(), a_write())

   with pytest.raises(UpstreamRejected) as stopped:
      await send_write(stop_sender, a_session(), a_write())

   assert len(budget_wire.writes) == 30
   assert stopped.value.code == WRITES_STOPPED
   assert len(stop_wire.writes) == 1


def test_the_fast_preset_keeps_the_budget_and_the_stop() -> None:
   """Catches the fast preset departing in more than the spacing it names."""

   assert FAST.write_budget_per_hour == 30
   assert FAST.stop_writes_after_unrecognised_rejection is True


@pytest.mark.asyncio
async def test_the_write_budget_refuses_without_sending() -> None:
   """Catches a thirty-first write in an hour reaching the wire."""

   wire = Wire(FakeClock())
   sender = paced(wire)

   for _ in range(30):
      await send_write(sender, a_session(), a_write())

   with pytest.raises(RateLimited) as refused:
      await send_write(sender, a_session(), a_write())

   assert len(wire.writes) == 30
   assert wire.clock.now < 3600.0
   assert refused.value.retry_after is not None
   assert refused.value.retry_after > 0


@pytest.mark.asyncio
async def test_a_refused_write_leaves_the_account_unheld() -> None:
   """Catches the budget's own refusal treated as an upstream throttle, stopping reads for it."""

   behavior = replace(PARITY, write_budget_per_hour=0)
   wire = Wire(FakeClock())
   sender = paced(wire, behavior)

   with pytest.raises(RateLimited):
      await send_write(sender, a_session(), a_write())

   await sender.send(a_read())

   assert wire.writes == []
   assert wire.reads == [0.0]


@pytest.mark.asyncio
async def test_an_unrecognised_write_rejection_stops_later_writes_and_not_reads() -> None:
   """Catches a write sent again into what is most likely an action block."""

   wire = Wire(FakeClock(), ["unrecognised"])
   sender = paced(wire)

   with pytest.raises(UpstreamRejected):
      await send_write(sender, a_session(), a_write())

   with pytest.raises(UpstreamRejected) as stopped:
      await send_write(sender, a_session(), a_write())

   await sender.send(a_read())

   assert stopped.value.code == WRITES_STOPPED
   assert len(wire.writes) == 1
   assert len(wire.reads) == 1


@pytest.mark.asyncio
async def test_the_write_stop_can_be_turned_off() -> None:
   """Catches the stop ignoring a caller who set it to False."""

   behavior = replace(PARITY, stop_writes_after_unrecognised_rejection=False)
   wire = Wire(FakeClock(), ["unrecognised"])
   sender = paced(wire, behavior)

   with pytest.raises(UpstreamRejected):
      await send_write(sender, a_session(), a_write())

   await send_write(sender, a_session(), a_write())

   assert len(wire.writes) == 2
