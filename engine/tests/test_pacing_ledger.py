"""Gates on the durable pacing ledger, E1 item 8 of ``engine/docs/web-parity-plan.md``.

The write budget and the write stop of a client built from a session file live in a ledger file
beside it, so separate processes on one account share them. The cross-process gates start real
interpreters on the same ledger path. Every wire is fake and every clock is injected: a pacer's
monotonic clock only advances when something sleeps on it, and a ledger's wall clock is a fixed
instant plus that. Each gate is seen red by ``scripts/verify_ledger_gates.py``.
"""

from __future__ import annotations

import asyncio
import io
import json
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from dumpstagram._cli.exits import EXIT_BY_ERROR
from dumpstagram._cli.main import main
from dumpstagram._core.ledger import FileLedger, MemoryLedger, WriteRecord, ledger_path_for
from dumpstagram._core.pacer import WRITES_STOPPED, Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.writing import send_write
from dumpstagram._private.transport import Request, Response, WriteRequest
from dumpstagram.aio import AsyncClient, pacing_for, write_policy_for
from dumpstagram.behavior import PARITY, Behavior, Spacing
from dumpstagram.client import SyncClient
from dumpstagram.errors import RateLimited, SchemaChanged, UpstreamRejected
from dumpstagram.session import Session

ENGINE = Path(__file__).resolve().parents[1]

WALL_START = 1_790_000_000.0
HOUR = 3600.0

WRITE_URL = "https://example.invalid/write"

UNRECOGNISED_REJECTION_BODY = b'{"error": "a_code_no_finding_explains"}'

TWO_AN_HOUR = replace(
   PARITY,
   write_spacing=Spacing(floor_seconds=0.0, mean_jitter_seconds=0.0),
   write_budget_per_hour=2,
)

WRITING_PROCESS = """
import asyncio
import json
import sys
from dataclasses import replace

from dumpstagram._core.ledger import FileLedger
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.writing import send_write
from dumpstagram._private.transport import Request, Response, WriteRequest
from dumpstagram.aio import pacing_for, write_policy_for
from dumpstagram.behavior import PARITY, Spacing
from dumpstagram.errors import RateLimited, UpstreamRejected
from dumpstagram.session import Session

ledger_path, wall_start, write_count, answer = sys.argv[1:5]


class Clock:
   def __init__(self):
      self.now = 0.0

   def __call__(self):
      return self.now

   async def sleep(self, seconds):
      self.now += seconds
      await asyncio.sleep(0)


class Wire:
   def __init__(self):
      self.departures = 0

   async def send(self, request):
      self.departures += 1
      body = b'{"data": {"applied": true}}'

      if answer == "unrecognised":
         body = b'{"error": "a_code_no_finding_explains"}'

      return Response(
         status_code=200,
         headers={"content-type": "application/json"},
         content=body,
         final_url=request.url,
      )


async def main():
   clock = Clock()
   wire = Wire()
   ledger = FileLedger(ledger_path, clock=lambda: float(wall_start) + clock.now)
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0, ledger=ledger)
   behavior = replace(
      PARITY,
      write_spacing=Spacing(floor_seconds=0.0, mean_jitter_seconds=0.0),
      write_budget_per_hour=2,
   )
   sender = PacedSender(wire, pacer, pacing_for(behavior), write_policy_for(behavior))
   session = Session(sessionid="sessionid-value", ds_user_id="1234567890", csrftoken="csrf")
   session.fb_dtsg = "fb-dtsg-value"
   outcomes = []

   for _ in range(int(write_count)):
      write = WriteRequest(
         Request(method="POST", url="https://example.invalid/write", content=b"x"),
         operation="a_write",
      )

      try:
         await send_write(sender, session, write)
         outcomes.append("applied")
      except RateLimited:
         outcomes.append("rate_limited")
      except UpstreamRejected as rejection:
         outcomes.append(f"rejected:{rejection.code}")

   print(json.dumps({"outcomes": outcomes, "departures": wire.departures}))


asyncio.run(main())
"""

INCREMENTING_PROCESS = """
import sys
import time

from dumpstagram._core.ledger import FileLedger

ledger_path, start_at, increments = sys.argv[1:4]
ledger = FileLedger(ledger_path)


def add_one(record, now):
   record.departures.append(now)


while time.time() < float(start_at):
   time.sleep(0.001)

for _ in range(int(increments)):
   ledger.update_now(add_one)
"""


class FakeClock:
   def __init__(self) -> None:
      self.now = 0.0

   def __call__(self) -> float:
      return self.now

   async def sleep(self, seconds: float) -> None:
      self.now += seconds

      await asyncio.sleep(0)


class Wire:
   def __init__(self, answers: list[str] | None = None) -> None:
      self.answers = list(answers or [])
      self.departures = 0

   async def send(self, request: Request) -> Response:
      self.departures += 1
      answer = self.answers.pop(0) if self.answers else "applied"
      body = b'{"data": {"applied": true}}'

      if answer == "unrecognised":
         body = UNRECOGNISED_REJECTION_BODY

      return Response(
         status_code=200,
         headers={"content-type": "application/json"},
         content=body,
         final_url=request.url,
      )


def a_session() -> Session:
   session = Session(sessionid="sessionid-value", ds_user_id="1234567890", csrftoken="csrf-value")
   session.fb_dtsg = "fb-dtsg-value"

   return session


def a_write() -> WriteRequest:
   return WriteRequest(Request(method="POST", url=WRITE_URL, content=b"x"), operation="a_write")


def shared_ledger(path: Path, clock: FakeClock, wall_offset: float = 0.0) -> FileLedger:
   return FileLedger(path, clock=lambda: WALL_START + wall_offset + clock.now)


def paced(
   wire: Wire,
   clock: FakeClock,
   ledger: FileLedger | None = None,
   behavior: Behavior = TWO_AN_HOUR,
) -> PacedSender:
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0, ledger=ledger)

   return PacedSender(wire, pacer, pacing_for(behavior), write_policy_for(behavior))


def run_writing_process(
   ledger_path: Path,
   *,
   writes: int,
   wall_offset: float = 0.0,
   answer: str = "applied",
) -> dict[str, object]:
   finished = subprocess.run(
      [
         sys.executable,
         "-c",
         WRITING_PROCESS,
         str(ledger_path),
         str(WALL_START + wall_offset),
         str(writes),
         answer,
      ],
      cwd=ENGINE,
      capture_output=True,
      text=True,
      timeout=60,
   )

   assert finished.returncode == 0, finished.stderr

   report: dict[str, object] = json.loads(finished.stdout)

   return report


def test_two_processes_on_one_session_file_share_one_write_budget(tmp_path: Path) -> None:
   """Catches a budget that resets with each process, which is the 1.0.0 limitation."""

   ledger_path = ledger_path_for(tmp_path / "session.json")

   first = run_writing_process(ledger_path, writes=2)
   second = run_writing_process(ledger_path, writes=1, wall_offset=60.0)

   assert first == {"outcomes": ["applied", "applied"], "departures": 2}
   assert second == {"outcomes": ["rate_limited"], "departures": 0}


def test_a_write_stop_seen_by_one_process_refuses_writes_in_another(tmp_path: Path) -> None:
   """Catches a stop kept in the memory of the process that saw the rejection."""

   ledger_path = ledger_path_for(tmp_path / "session.json")

   first = run_writing_process(ledger_path, writes=1, answer="unrecognised")
   second = run_writing_process(ledger_path, writes=1, wall_offset=60.0)

   assert first["departures"] == 1
   assert second == {"outcomes": [f"rejected:{WRITES_STOPPED}"], "departures": 0}


def test_the_write_stop_survives_a_restart_long_after_the_window(tmp_path: Path) -> None:
   """Catches a stop that lapses with the budget window instead of waiting for a person."""

   ledger_path = ledger_path_for(tmp_path / "session.json")

   run_writing_process(ledger_path, writes=1, answer="unrecognised")
   a_day_later = run_writing_process(ledger_path, writes=1, wall_offset=24 * HOUR)

   assert a_day_later == {"outcomes": [f"rejected:{WRITES_STOPPED}"], "departures": 0}


def test_concurrent_increments_under_the_lock_are_not_lost(tmp_path: Path) -> None:
   """Catches a read, change and rename that two processes can interleave, losing one change."""

   ledger_path = tmp_path / "session.json.ledger"
   processes = 4
   increments = 100
   start_at = time.time() + 2.0

   running = [
      subprocess.Popen(
         [
            sys.executable,
            "-c",
            INCREMENTING_PROCESS,
            str(ledger_path),
            str(start_at),
            str(increments),
         ],
         cwd=ENGINE,
      )
      for _ in range(processes)
   ]

   exit_codes = [process.wait(timeout=120) for process in running]
   record = FileLedger(ledger_path).read_now()

   assert exit_codes == [0] * processes
   assert len(record.departures) == processes * increments


@pytest.mark.asyncio
async def test_the_rolling_window_frees_the_shared_budget(tmp_path: Path) -> None:
   """Catches departures that never leave the window, which would refuse writes for good."""

   ledger_path = tmp_path / "session.json.ledger"

   first_clock = FakeClock()
   first_wire = Wire()
   first = paced(first_wire, first_clock, shared_ledger(ledger_path, first_clock))

   await send_write(first, a_session(), a_write())
   await send_write(first, a_session(), a_write())

   later_clock = FakeClock()
   later_wire = Wire()
   later = paced(later_wire, later_clock, shared_ledger(ledger_path, later_clock, HOUR + 10.0))

   await send_write(later, a_session(), a_write())

   assert first_wire.departures == 2
   assert later_wire.departures == 1
   assert len(FileLedger(ledger_path).read_now().departures) == 1


@pytest.mark.asyncio
async def test_a_budget_spent_elsewhere_during_the_wait_refuses_the_write(tmp_path: Path) -> None:
   """Catches a ledger read once and trusted, so a write takes a slot another process took."""

   ledger_path = tmp_path / "session.json.ledger"
   clock = FakeClock()
   wire = Wire()
   spaced = replace(TWO_AN_HOUR, write_spacing=Spacing(floor_seconds=30.0, mean_jitter_seconds=0.0))
   sender = paced(wire, clock, shared_ledger(ledger_path, clock), spaced)

   await send_write(sender, a_session(), a_write())

   elsewhere = shared_ledger(ledger_path, clock)

   async def spend_the_budget_elsewhere_then_sleep(seconds: float) -> None:
      await elsewhere.update(lambda record, now: record.departures.append(now))
      await clock.sleep(seconds)

   sender.pacer._sleep = spend_the_budget_elsewhere_then_sleep

   with pytest.raises(RateLimited):
      await send_write(sender, a_session(), a_write())

   assert wire.departures == 1
   assert clock.now == pytest.approx(30.0)


@pytest.mark.asyncio
async def test_a_stop_shared_by_another_process_refuses_before_the_wait(tmp_path: Path) -> None:
   """Catches a stop checked only after a write has sat out its spacing."""

   ledger_path = tmp_path / "session.json.ledger"
   clock = FakeClock()
   wire = Wire()
   spaced = replace(TWO_AN_HOUR, write_spacing=Spacing(floor_seconds=30.0, mean_jitter_seconds=0.0))
   sender = paced(wire, clock, shared_ledger(ledger_path, clock), spaced)

   await send_write(sender, a_session(), a_write())

   def stop(record: WriteRecord, now: float) -> None:
      record.writes_stopped = True
      record.stopped_at = now

   shared_ledger(ledger_path, clock).update_now(stop)

   with pytest.raises(UpstreamRejected) as stopped:
      await send_write(sender, a_session(), a_write())

   assert stopped.value.code == WRITES_STOPPED
   assert wire.departures == 1
   assert clock.now == 0.0


@pytest.mark.asyncio
async def test_a_corrupt_ledger_refuses_writes_and_is_left_as_it_was(tmp_path: Path) -> None:
   """Catches an unreadable ledger read as empty, which would forget a stop it held."""

   ledger_path = tmp_path / "session.json.ledger"
   corrupt = b'{"schema_version": 1, "writes_stopped": tr'
   ledger_path.write_bytes(corrupt)

   clock = FakeClock()
   wire = Wire(["unrecognised"])
   sender = paced(wire, clock, shared_ledger(ledger_path, clock))

   with pytest.raises(UpstreamRejected) as refused:
      await send_write(sender, a_session(), a_write())

   assert refused.value.code == WRITES_STOPPED
   assert wire.departures == 0
   assert ledger_path.read_bytes() == corrupt


@pytest.mark.asyncio
async def test_a_ledger_from_a_newer_engine_refuses_writes_and_is_left_as_it_was(
   tmp_path: Path,
) -> None:
   """Catches a newer schema read as this one, and then overwritten in the older form."""

   ledger_path = tmp_path / "session.json.ledger"
   newer = json.dumps(
      {"schema_version": 2, "departures": [], "writes_stopped": False, "stopped_at": None}
   ).encode()
   ledger_path.write_bytes(newer)

   clock = FakeClock()
   wire = Wire()
   sender = paced(wire, clock, shared_ledger(ledger_path, clock))

   with pytest.raises(UpstreamRejected) as refused:
      await send_write(sender, a_session(), a_write())

   assert refused.value.code == WRITES_STOPPED
   assert wire.departures == 0
   assert ledger_path.read_bytes() == newer


@pytest.mark.asyncio
async def test_pacers_over_a_bare_session_keep_their_own_budgets(
   tmp_path: Path,
   monkeypatch: pytest.MonkeyPatch,
) -> None:
   """Catches a default that persists pacing when no session file was ever named."""

   monkeypatch.chdir(tmp_path)

   for _ in range(2):
      clock = FakeClock()
      wire = Wire()
      sender = paced(wire, clock)

      await send_write(sender, a_session(), a_write())
      await send_write(sender, a_session(), a_write())

      assert wire.departures == 2
      assert isinstance(sender.pacer.ledger, MemoryLedger)

   assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_clients_from_a_session_file_keep_the_ledger_beside_it(tmp_path: Path) -> None:
   """Catches a client built from a file that still keeps its pacing in memory."""

   session_path = tmp_path / "session.json"
   a_session().save(session_path)

   from_file = AsyncClient.from_session_file(session_path)
   blocking_from_file = SyncClient.from_session_file(session_path)
   from_bare_session = AsyncClient(a_session())

   try:
      ledgers = [
         from_file._sender.pacer.ledger,
         blocking_from_file._impl._sender.pacer.ledger,
      ]

      assert all(isinstance(ledger, FileLedger) for ledger in ledgers)
      assert [ledger.path for ledger in ledgers if isinstance(ledger, FileLedger)] == [
         tmp_path / "session.json.ledger",
         tmp_path / "session.json.ledger",
      ]
      assert isinstance(from_bare_session._sender.pacer.ledger, MemoryLedger)
   finally:
      await from_file.aclose()
      await from_bare_session.aclose()
      blocking_from_file.close()


def run_session_command(session_path: Path, *extra: str) -> tuple[int, str, str]:
   out = io.StringIO()
   errors = io.StringIO()

   code = main(
      ["--json", "--session", str(session_path), "session", *extra],
      environment={},
      stdout=out,
      stderr=errors,
   )

   return code, out.getvalue(), errors.getvalue()


def test_clearing_the_write_stop_keeps_the_hours_departures(tmp_path: Path) -> None:
   """Catches a reset that lifts the stop by forgetting the budget with it."""

   session_path = tmp_path / "session.json"
   a_session().save(session_path)
   ledger_path = ledger_path_for(session_path)

   run_writing_process(ledger_path, writes=1)
   run_writing_process(ledger_path, writes=1, answer="unrecognised")

   code, out, _ = run_session_command(session_path, "--clear-write-stop")
   after_clearing = run_writing_process(ledger_path, writes=1, wall_offset=60.0)

   assert code == 0
   assert json.loads(out)["write_stop_cleared"] is True
   assert after_clearing == {"outcomes": ["rate_limited"], "departures": 0}


def test_the_session_command_leaves_the_write_stop_unless_asked(tmp_path: Path) -> None:
   """Catches the stop lifted by a person who only asked to see the session."""

   session_path = tmp_path / "session.json"
   a_session().save(session_path)
   ledger_path = ledger_path_for(session_path)

   run_writing_process(ledger_path, writes=1, answer="unrecognised")

   code, out, _ = run_session_command(session_path)
   still_stopped = run_writing_process(ledger_path, writes=1, wall_offset=60.0)

   assert code == 0
   assert "write_stop_cleared" not in json.loads(out)
   assert still_stopped == {"outcomes": [f"rejected:{WRITES_STOPPED}"], "departures": 0}


def test_clearing_the_stop_on_an_unreadable_ledger_changes_nothing(tmp_path: Path) -> None:
   """Catches a reset that rewrites a ledger it could not read, forgetting what it held."""

   session_path = tmp_path / "session.json"
   a_session().save(session_path)
   ledger_path = ledger_path_for(session_path)
   corrupt = b"not a ledger"
   ledger_path.write_bytes(corrupt)

   code, _, errors = run_session_command(session_path, "--clear-write-stop")

   assert code == EXIT_BY_ERROR[SchemaChanged]
   assert "Nothing was cleared" in errors
   assert ledger_path.read_bytes() == corrupt
