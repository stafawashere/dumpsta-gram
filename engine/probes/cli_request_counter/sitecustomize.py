"""Counts every request a `dumpsta` process puts on the wire, for `phase3_cli_acceptance.py`.

Loaded by the interpreter at start up because the probe puts this directory on ``PYTHONPATH``
of each command it runs, and inert anywhere ``DUMPSTA_PROBE_REQUEST_LOG`` is unset. It wraps
``httpx.AsyncClient._send_single_request``, which every hop of a redirect passes through, so
the count is what left the machine rather than what the library asked for.

One JSON line per request: the probe's step number, host, method, friendly name, status and
offset. No path beyond a first segment from a fixed list, no query, no header value but the
friendly name, and nothing from a body. The cap is shared across processes by counting lines already written, and
a request over it is refused before it departs.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

REQUEST_LOG_ENV = "DUMPSTA_PROBE_REQUEST_LOG"
REQUEST_CAP_ENV = "DUMPSTA_PROBE_REQUEST_CAP"
STEP_ENV = "DUMPSTA_PROBE_STEP"

NAMED_PATH_SEGMENTS = ("", "ajax", "api", "graphql", "instagram", "sync")
"""First path segments safe to record. Anything else may be a username, so it is not."""


def install(request_log: Path, request_cap: int, step: str) -> None:
   import httpx

   original_send = httpx.AsyncClient._send_single_request
   started_at = time.monotonic()
   in_flight = [0]

   async def counted_send(client: httpx.AsyncClient, request: httpx.Request) -> httpx.Response:
      already_sent = 0

      if request_log.exists():
         already_sent = len(request_log.read_text(encoding="utf-8").splitlines())

      if already_sent + in_flight[0] >= request_cap:
         raise RuntimeError(f"refusing request {already_sent + 1}, the cap is {request_cap}")

      first_segment = request.url.path.strip("/").split("/")[0]
      is_a_named_segment = first_segment in NAMED_PATH_SEGMENTS
      recorded_segment = first_segment if is_a_named_segment else "other"
      entry: dict[str, object] = {
         "step": step,
         "host": request.url.host,
         "method": request.method,
         "name": request.headers.get("x-fb-friendly-name", f"/{recorded_segment}"),
         "offset_ms": int((time.monotonic() - started_at) * 1000),
      }

      in_flight[0] += 1

      try:
         response = await original_send(client, request)
      except Exception as failure:
         entry["failed_with"] = type(failure).__name__
         append(request_log, entry)
         raise
      finally:
         in_flight[0] -= 1

      entry["status"] = response.status_code
      append(request_log, entry)

      return response

   httpx.AsyncClient._send_single_request = counted_send  # type: ignore[method-assign]


def append(request_log: Path, entry: dict[str, object]) -> None:
   with request_log.open("a", encoding="utf-8") as stream:
      stream.write(json.dumps(entry) + "\n")


request_log_path = os.environ.get(REQUEST_LOG_ENV)

if request_log_path:
   install(
      Path(request_log_path),
      int(os.environ.get(REQUEST_CAP_ENV, "0")),
      os.environ.get(STEP_ENV, "?"),
   )
