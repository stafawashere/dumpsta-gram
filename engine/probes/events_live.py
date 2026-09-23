"""Read only. Six live requests planned, three per surface, eight at most with two bootstraps.

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

Run it from `engine/` with:

   uv run python probes/events_live.py
   uv run python probes/events_live.py --surface async
"""

from __future__ import annotations

import argparse
import io
import json
import time
from pathlib import Path
from typing import Any

from _probe_support import SESSION_PATH, load_env, report_run

from dumpstagram._cli.main import main
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import Request, Response, Sender
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import Behavior
from dumpstagram.client import SyncClient

NON_CREDENTIAL_KEYS = ("IG_SESSION_FILE",)

REQUEST_CAP_PER_SURFACE = 4
"""Three polls, and one bootstrap if the stored token is refused."""

DURATION_SECONDS = 150.0
"""Room for polls at about 0, 63 and 126 s and not for a fourth at about 189 s."""

INTERVAL_SECONDS = 60.0


class CountingTransport:
   def __init__(self, inner: Sender, pacer: Pacer, cap: int) -> None:
      self.inner = inner
      self.pacer = pacer
      self.cap = cap
      self.sent: list[dict[str, object]] = []
      self.started_at = time.monotonic()

   async def send(self, request: Request) -> Response:
      if len(self.sent) >= self.cap:
         raise RuntimeError(f"refusing request {len(self.sent) + 1}, the cap is {self.cap}")

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


def counted(client: AsyncClient, counters: list[CountingTransport]) -> None:
   paced = client._sender
   counter = CountingTransport(paced._sender, paced.pacer, REQUEST_CAP_PER_SURFACE)
   counters.append(counter)
   client._sender = PacedSender(counter, paced.pacer, paced.pacing, paced.writes)


def run(surface: str) -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}
   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   counters: list[CountingTransport] = []

   def blocking_factory(path: Path, *, user_agent: str | None, behavior: Behavior) -> Any:
      client = SyncClient.from_session_file(path, user_agent=user_agent, behavior=behavior)
      counted(client._impl, counters)

      return client

   def async_factory(path: Path, *, user_agent: str | None, behavior: Behavior) -> Any:
      client = AsyncClient.from_session_file(path, user_agent=user_agent, behavior=behavior)
      counted(client, counters)

      return client

   out = io.StringIO()
   errors = io.StringIO()
   argv = [
      "--session",
      str(session_path),
      "--json",
      "events",
      "--surface",
      surface,
      "--duration",
      str(DURATION_SECONDS),
      "--interval",
      str(INTERVAL_SECONDS),
      "--ids-only",
   ]

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

   report_run(f"events-live-{surface}", report)

   return exit_code


def parse_arguments() -> argparse.Namespace:
   parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
   parser.add_argument("--surface", choices=("sync", "async"), default="sync")

   return parser.parse_args()


if __name__ == "__main__":
   raise SystemExit(run(parse_arguments().surface))
