"""Read only by default. Six live requests planned, three per surface, eight at most with two
bootstraps. With ``--send-arranged`` it writes twice per run, one direct message and its unsend,
and runs the planned acceptance: eleven listener requests and three for the writes.

Step 23's reduced live acceptance, under ruling 23's budget for the night. The planned run is
ten polls on each surface with one arranged incoming message, eleven requests each. That needs
someone to send the message, and the owner is asleep (ruling 10), so this run arranges nothing:
it runs `dumpsta events` for about three polls at a 60 s interval on each surface and records
that the loop runs live, that every request it sends holds the account's pacer slot, and that
nothing is printed with nothing happening.

The command is driven in process through `dumpstagram._cli.main.main`, the same function the
console script calls, with `--json --ids-only`. The only thing the probe changes is the client
factory: each client's paced sender is rebuilt over a counting transport that wraps the
client's own `HttpxTransport` and refuses a request past the cap. Nothing else is sent.

Recorded: per request its friendly name, offset, status, length and whether the pacer's slot
was held when it left, the command's exit code, and every line it printed. Those lines carry
ids and times only, because of `--ids-only`, so an unrelated message that arrives during the
run shows as its ids and never its text.

``--send-arranged`` runs the planned acceptance instead, ruling 30: `dumpsta events --duration
600 --interval 60`, ten polls, and one message the engine sends partway through into the thread
named by ``--thread-fbid``, the owner-named target's, with the text in ``IG_DM_TEXT``, which
never reaches the log. The writes go through a second `AsyncClient` on a thread of their own,
counted by a transport of their own. The message is sent 20 s after the third listing read
answers, and unsent 20 s after the listener's next request once the event carrying its id has
been printed, or once two more listing reads have gone without it. Both writes are timed off
the listener's own requests, since the writing client has a pacer of its own, and the log
records the smallest gap between a write request and a listener request. A request is timed at
departure and a printed line when it is written, on one monotonic clock, so the log carries the
seconds from the send's departure to the event's line, the upper bound on the latency the stop
condition asks for, because the message cannot be readable before it was sent. Nothing is sent
without ``--approve send-message``. A ``CheckpointRequired`` on either client stops both, and no
unsend is attempted after one.

Run it from `engine/` with:

   uv run python probes/events_live.py
   uv run python probes/events_live.py --surface async
   uv run python probes/events_live.py --surface sync --send-arranged --approve send-message \\
      --thread-fbid FBID
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import threading
import time
from pathlib import Path
from typing import Any

from _probe_support import SESSION_PATH, load_env, report_run

from dumpstagram._cli.exits import EXIT_BY_ERROR
from dumpstagram._cli.main import main
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import Request, Response, Sender
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import Behavior
from dumpstagram.client import SyncClient
from dumpstagram.errors import CheckpointRequired

NON_CREDENTIAL_KEYS = ("IG_SESSION_FILE", "IG_DM_TEXT")

REQUEST_CAP_PER_SURFACE = 4
"""Three polls, and one bootstrap if the stored token is refused."""

DURATION_SECONDS = 150.0
"""Room for polls at about 0, 63 and 126 s and not for a fourth at about 189 s."""

INTERVAL_SECONDS = 60.0

CHECKPOINT_EXIT_CODE = EXIT_BY_ERROR[CheckpointRequired]

ARRANGED_DURATION_SECONDS = 600.0
"""Ten polls about 63 s apart start by about 570 s, and an eleventh would start after 600 s."""

ARRANGED_LISTENER_CAP = 12
"""Ten listing reads, the arranged thread's read, and one bootstrap."""

ARRANGED_WRITER_CAP = 4
"""The send, the thread open and the unsend, and one bootstrap."""

SEND_AFTER_LISTING_READS = 3

WRITE_DELAY_SECONDS = 20.0
"""How long after the listener's latest request a write leaves, a third of the poll interval."""

UNSEND_AFTER_MORE_LISTING_READS = 2
"""Listing reads after the send without the event, after which the message is unsent anyway."""


class CountingTransport:
   def __init__(
      self,
      inner: Sender,
      pacer: Pacer,
      cap: int,
      started_at: float | None = None,
      halted: threading.Event | None = None,
   ) -> None:
      self.inner = inner
      self.pacer = pacer
      self.cap = cap
      self.sent: list[dict[str, object]] = []
      self.started_at = time.monotonic() if started_at is None else started_at
      self.halted = halted

   async def send(self, request: Request) -> Response:
      if len(self.sent) >= self.cap:
         raise RuntimeError(f"refusing request {len(self.sent) + 1}, the cap is {self.cap}")

      if self.halted is not None and self.halted.is_set():
         raise RuntimeError("refusing request, the run was halted")

      entry: dict[str, object] = {
         "name": request.headers.get("x-fb-friendly-name", "document"),
         "offset_ms": int((time.monotonic() - self.started_at) * 1000),
         "held_the_pacer_slot": self.pacer._lock.locked(),
      }
      self.sent.append(entry)

      response = await self.inner.send(request)
      entry["status"] = response.status_code
      entry["length"] = len(response.content)

      return response

   async def aclose(self) -> None:
      closer = getattr(self.inner, "aclose", None)

      if closer is not None:
         await closer()


def counted(
   client: AsyncClient,
   counters: list[CountingTransport],
   cap: int = REQUEST_CAP_PER_SURFACE,
   started_at: float | None = None,
   halted: threading.Event | None = None,
) -> CountingTransport:
   paced = client._sender
   counter = CountingTransport(paced._sender, paced.pacer, cap, started_at, halted)
   counters.append(counter)
   client._sender = PacedSender(counter, paced.pacer, paced.pacing, paced.writes)

   return counter


class TimedLines(io.StringIO):
   """Standard output that also records when each line was written, on the run's clock."""

   def __init__(self, started_at: float) -> None:
      super().__init__()
      self.started_at = started_at
      self.line_offsets_ms: list[int] = []
      self.lines: list[str] = []
      self._partial = ""

   def write(self, text: str) -> int:
      self._partial += text

      while "\n" in self._partial:
         line, self._partial = self._partial.split("\n", 1)
         self.lines.append(line)
         self.line_offsets_ms.append(int((time.monotonic() - self.started_at) * 1000))

      return super().write(text)


class ArrangedWriter:
   """Sends the arranged message partway through the listener's run and unsends it after."""

   def __init__(
      self,
      session_path: Path,
      thread_fbid: str,
      text: str,
      listener_counters: list[CountingTransport],
      out: TimedLines,
      started_at: float,
      halted: threading.Event,
      listening_done: threading.Event,
   ) -> None:
      self.session_path = session_path
      self.thread_fbid = thread_fbid
      self.text = text
      self.listener_counters = listener_counters
      self.out = out
      self.started_at = started_at
      self.halted = halted
      self.listening_done = listening_done
      self.counters: list[CountingTransport] = []
      self.record: dict[str, object] = {"text_length": len(text), "thread_fbid": thread_fbid}

   def listener_requests(self) -> list[dict[str, object]]:
      return [entry for counter in self.listener_counters for entry in counter.sent]

   def answered_listing_reads(self) -> int:
      return sum(
         entry["name"] == "PolarisDirectInboxQuery" and "status" in entry
         for entry in self.listener_requests()
      )

   def seconds_since_the_listeners_latest_request(self) -> float:
      offsets = [int(str(entry["offset_ms"])) for entry in self.listener_requests()]
      now_ms = (time.monotonic() - self.started_at) * 1000

      return (now_ms - max(offsets, default=0)) / 1000

   def printed_the_sent_id(self, sent_id: str) -> bool:
      return any(sent_id in line for line in list(self.out.lines))

   def wait_until(self, condition: Any) -> bool:
      while not condition():
         if self.halted.is_set() or self.listening_done.is_set():
            return False

         time.sleep(0.25)

      return True

   def wait_for_a_quiet_moment(self) -> bool:
      return self.wait_until(
         lambda: self.seconds_since_the_listeners_latest_request() >= WRITE_DELAY_SECONDS
      )

   def run(self) -> None:
      try:
         asyncio.run(self._write())
      except CheckpointRequired:
         self.halted.set()
         self.record["failed_with"] = "CheckpointRequired"
      except Exception as failure:
         self.record["failed_with"] = type(failure).__name__
         self.record["failure_text"] = str(failure)[:200]

   async def _write(self) -> None:
      reached_the_send_point = self.wait_until(
         lambda: self.answered_listing_reads() >= SEND_AFTER_LISTING_READS
      )

      if not reached_the_send_point or not self.wait_for_a_quiet_moment():
         self.record["sent"] = False

         return

      client = AsyncClient.from_session_file(self.session_path)
      counted(client, self.counters, ARRANGED_WRITER_CAP, self.started_at, self.halted)

      async with client:
         sent = await client.send_message(self.thread_fbid, self.text)
         send_entry = self.counters[0].sent[-1]
         self.record["sent"] = {
            "id": sent.id,
            "sent_at": sent.sent_at.isoformat(),
            "offline_threading_id": sent.offline_threading_id,
            "departed_offset_ms": send_entry["offset_ms"],
         }
         reads_at_send = self.answered_listing_reads()

         def printed_or_given_up() -> bool:
            more_reads = self.answered_listing_reads() - reads_at_send
            has_given_up = more_reads >= UNSEND_AFTER_MORE_LISTING_READS

            return self.printed_the_sent_id(sent.id) or has_given_up

         self.wait_until(printed_or_given_up)
         self.record["printed_before_unsend"] = self.printed_the_sent_id(sent.id)

         if self.halted.is_set():
            self.record["unsent"] = False

            return

         self.wait_until(
            lambda: self.seconds_since_the_listeners_latest_request() >= WRITE_DELAY_SECONDS
         )
         await client.unsend_message(self.thread_fbid, sent.id)
         self.record["unsent"] = True


def smallest_gap_ms(
   writes: list[dict[str, object]], listening: list[dict[str, object]]
) -> int | None:
   gaps = [
      abs(int(str(write["offset_ms"])) - int(str(read["offset_ms"])))
      for write in writes
      for read in listening
   ]

   return min(gaps, default=None)


def latency(
   writer: ArrangedWriter, out: TimedLines, requests: list[dict[str, object]]
) -> dict[str, object]:
   sent = writer.record.get("sent")

   if not isinstance(sent, dict):
      return {"measured": False}

   sent_id = str(sent["id"])
   departed_ms = int(sent["departed_offset_ms"])
   printed_at = [
      offset for line, offset in zip(out.lines, out.line_offsets_ms, strict=True) if sent_id in line
   ]
   listing_offsets = [
      int(str(entry["offset_ms"]))
      for entry in requests
      if entry["name"] == "PolarisDirectInboxQuery"
   ]
   first_listing_after = next((offset for offset in listing_offsets if offset > departed_ms), None)

   if not printed_at:
      return {"measured": True, "printed": False}

   seconds_from_send = (printed_at[0] - departed_ms) / 1000
   within_two_intervals = seconds_from_send <= 2 * INTERVAL_SECONDS

   return {
      "measured": True,
      "printed": True,
      "printed_times": len(printed_at),
      "send_departed_offset_ms": departed_ms,
      "printed_offset_ms": printed_at[0],
      "first_listing_read_after_the_send_offset_ms": first_listing_after,
      "seconds_from_send_departure_to_line": round(seconds_from_send, 3),
      "within_two_poll_intervals": within_two_intervals,
   }


def run(surface: str, arguments: argparse.Namespace) -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}
   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   counters: list[CountingTransport] = []
   send_arranged = arguments.send_arranged
   text = environment.get("IG_DM_TEXT", "")
   kind = f"events-live-{surface}-arranged" if send_arranged else f"events-live-{surface}"
   refusal = None

   if send_arranged and arguments.approve != "send-message":
      refusal = "not approved, pass --approve send-message"
   elif send_arranged and not arguments.thread_fbid:
      refusal = "--send-arranged needs --thread-fbid"
   elif send_arranged and not text:
      refusal = "no IG_DM_TEXT in .env"

   if refusal:
      report_run(f"{kind}-refused", {"surface": surface, "failed_with": refusal})

      return 2

   started_at = time.monotonic()
   halted = threading.Event()
   listening_done = threading.Event()
   cap = ARRANGED_LISTENER_CAP if send_arranged else REQUEST_CAP_PER_SURFACE
   duration = ARRANGED_DURATION_SECONDS if send_arranged else DURATION_SECONDS

   def blocking_factory(path: Path, *, user_agent: str | None, behavior: Behavior) -> Any:
      client = SyncClient.from_session_file(path, user_agent=user_agent, behavior=behavior)
      counted(client._impl, counters, cap, started_at, halted)

      return client

   def async_factory(path: Path, *, user_agent: str | None, behavior: Behavior) -> Any:
      client = AsyncClient.from_session_file(path, user_agent=user_agent, behavior=behavior)
      counted(client, counters, cap, started_at, halted)

      return client

   out = TimedLines(started_at)
   errors = io.StringIO()
   argv = [
      "--session",
      str(session_path),
      "--json",
      "events",
      "--surface",
      surface,
      "--duration",
      str(duration),
      "--interval",
      str(INTERVAL_SECONDS),
      "--ids-only",
   ]

   writer = None
   writer_thread = None

   if send_arranged:
      writer = ArrangedWriter(
         session_path,
         arguments.thread_fbid,
         text,
         counters,
         out,
         started_at,
         halted,
         listening_done,
      )
      writer_thread = threading.Thread(target=writer.run, name="arranged-writer")
      writer_thread.start()

   started = time.monotonic()
   raised: str | None = None

   try:
      exit_code = main(
         argv,
         listening_client_factory=blocking_factory,
         async_listening_client_factory=async_factory,
         stdout=out,
         stderr=errors,
      )
   except Exception as failure:
      raised = type(failure).__name__
      exit_code = 1

   ended_on_a_checkpoint = exit_code == CHECKPOINT_EXIT_CODE

   if ended_on_a_checkpoint:
      halted.set()

   listening_done.set()

   if writer_thread is not None:
      writer_thread.join()

   elapsed = time.monotonic() - started

   printed = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
   events = [line for line in printed if "event" in line]
   requests = [entry for counter in counters for entry in counter.sent]
   listing_reads = [entry for entry in requests if entry["name"] == "PolarisDirectInboxQuery"]

   report: dict[str, object] = {
      "surface": surface,
      "argv_after_session": argv[2:],
      "exit_code": exit_code,
      "raised": raised,
      "stderr_length": len(errors.getvalue()),
      "stderr_error_class": errors.getvalue().split(":")[0].strip() or None,
      "elapsed_seconds": round(elapsed, 1),
      "request_count": len(requests),
      "listing_reads": len(listing_reads),
      "every_request_held_the_pacer_slot": all(entry["held_the_pacer_slot"] for entry in requests),
      "every_answer_200": all(entry.get("status") == 200 for entry in requests),
      "events_printed": len(events),
      "events": events,
      "summary": printed[-1] if printed else None,
      "requests": requests,
   }

   if writer is not None:
      writes = [entry for counter in writer.counters for entry in counter.sent]
      report["arranged"] = writer.record
      report["write_requests"] = writes
      report["write_request_count"] = len(writes)
      report["smallest_gap_ms_between_a_write_and_a_listener_request"] = smallest_gap_ms(
         writes, requests
      )
      report["latency"] = latency(writer, out, requests)
      report["printed_line_offsets_ms"] = out.line_offsets_ms

   report_run(kind, report)

   return exit_code


def parse_arguments() -> argparse.Namespace:
   parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
   parser.add_argument("--surface", choices=("sync", "async"), default="sync")
   parser.add_argument("--send-arranged", action="store_true")
   parser.add_argument("--approve", default="")
   parser.add_argument("--thread-fbid", default="")

   return parser.parse_args()


if __name__ == "__main__":
   parsed = parse_arguments()

   raise SystemExit(run(parsed.surface, parsed))
