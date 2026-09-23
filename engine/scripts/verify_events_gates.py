"""Break the listener behind ``events()``, watch each of its gates go red, restore.

Same harness and same rule as ``verify_inbox_gates.py``: one mutation per line below, only the
gate that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

The first ten mutations are the gate table of Step 22 in ``docs/build-plan.md``, each under
exactly the mutation that table names. The rest cover what the step added around them. The
gate on the placeholder source went with the placeholder in Step 23, and its successor, that a
client polls the inbox by default, is in ``verify_poller_gates.py``.

Run from ``engine/`` with ``uv run python scripts/verify_events_gates.py``. Writes its result to
``engine/logs/``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
LOG_DIR = ENGINE / "logs"

GATE_TIMEOUT_SECONDS = 300

AIO = "dumpstagram/aio.py"
BEHAVIOR = "dumpstagram/behavior.py"
BUFFER = "dumpstagram/_core/realtime/buffer.py"
CLIENT = "dumpstagram/client.py"
LISTENER = "dumpstagram/listener.py"
PUMP = "dumpstagram/_core/realtime/pump.py"
EVENTS = "tests/test_events.py"
PARITY = "tests/test_facade_parity.py"


def gate(name: str, suite: str = EVENTS) -> str:
   return f"{suite}::{name}"


MUTATIONS: list[dict[str, object]] = [
   {
      "gate": gate("test_drain_from_another_thread_returns_every_event_exactly_once"),
      "defect": "drain takes the buffer without its lock",
      "edits": [
         (
            BUFFER,
            "      with self._lock:\n         return self._take_all()\n",
            "      if True:\n         return self._take_all()\n",
         )
      ],
   },
   {
      "gate": gate("test_overflow_drops_the_oldest_and_leaves_a_marker_carrying_the_count"),
      "defect": "a full buffer drops the newest event instead of the oldest",
      "edits": [
         (
            BUFFER,
            "            self._events.popleft()\n            self._dropped += 1\n",
            "            self._dropped += 1\n            return\n",
         )
      ],
   },
   {
      "gate": gate("test_a_message_id_seen_twice_is_one_event"),
      "defect": "the seen-id check is dropped",
      "edits": [
         (
            PUMP,
            "         is_new = seen.add(message.id)\n",
            "         seen.add(message.id)\n         is_new = True\n",
         )
      ],
   },
   {
      "gate": gate("test_events_within_a_thread_arrive_in_ascending_sent_at"),
      "defect": "events are emitted in inbox order",
      "edits": [
         (
            PUMP,
            "   return sorted(messages, key=lambda message: message.sent_at)\n",
            "   return list(messages)\n",
         )
      ],
   },
   {
      "gate": gate("test_a_terminal_failure_stops_the_listener_and_the_sync_side_sees_it_in_band"),
      "defect": "a poll failure is swallowed and polling carries on",
      "edits": [
         (
            PUMP,
            "   except SURVIVABLE as failure:\n",
            "   except Exception as failure:\n",
         )
      ],
   },
   {
      "gate": gate("test_a_checkpoint_during_a_poll_is_never_retried"),
      "defect": "CheckpointRequired is added to the listener's retry set",
      "edits": [
         (
            PUMP,
            "from dumpstagram.errors import RateLimited, TransportFailure\n",
            "from dumpstagram.errors import CheckpointRequired, RateLimited, TransportFailure\n",
         ),
         (
            PUMP,
            "= (TransportFailure, RateLimited)\n",
            "= (TransportFailure, RateLimited, CheckpointRequired)\n",
         ),
      ],
   },
   {
      "gate": gate("test_every_poll_passes_the_pacer"),
      "defect": "the listener's source gets its own unpaced sender",
      "edits": [
         (
            AIO,
            "            sender=self._sender,\n            session=self._session,\n",
            "            sender=self._sender._sender,\n            session=self._session,\n",
         )
      ],
   },
   {
      "gate": gate("test_stop_releases_the_loop_thread_reference_and_the_task"),
      "defect": "stop leaves the poll task running",
      "edits": [
         (
            LISTENER,
            '            loop.run(self._halt(), operation="EventListener.stop")\n',
            "            pass\n",
         )
      ],
   },
   {
      "gate": gate("test_both_listener_methods_share_every_parameter_except_the_handler", PARITY),
      "defect": "a parameter is added to the async events method only",
      "edits": [
         (
            AIO,
            "   async def events(self, *, since: str | None = None) -> AsyncIterator[Event]:\n",
            "   async def events(\n"
            "      self, *, since: str | None = None, limit: int | None = None\n"
            "   ) -> AsyncIterator[Event]:\n",
         )
      ],
   },
   {
      "gate": gate("test_no_blocking_call_runs_on_the_loop_thread"),
      "defect": "the poll calls time.sleep on the loop thread",
      "edits": [
         (
            PUMP,
            "      messages = await poll_once(source, pacer)\n",
            '      __import__("time").sleep(0.3)\n'
            "      messages = await poll_once(source, pacer)\n",
         )
      ],
   },
   {
      "gate": gate("test_a_final_event_survives_a_full_buffer"),
      "defect": "a put after the final event is still accepted",
      "edits": [
         (
            BUFFER,
            "      with self._lock:\n         if self._finished:\n            return\n\n"
            "         is_full",
            "      with self._lock:\n         is_full",
         )
      ],
   },
   {
      "gate": gate("test_wait_for_events_wakes_when_an_event_arrives"),
      "defect": "a put does not wake a parked consumer",
      "edits": [
         (
            BUFFER,
            "         self._events.append(event)\n         self._changed.notify_all()\n",
            "         self._events.append(event)\n",
         )
      ],
   },
   {
      "gate": gate("test_the_async_iterator_reraises_the_original_failure"),
      "defect": "the async iterator wraps the failure",
      "edits": [
         (
            AIO,
            "                  raise event.error\n",
            '                  raise RuntimeError("the listener stopped") from event.error\n',
         )
      ],
   },
   {
      "gate": gate("test_the_listener_polls_through_a_transport_failure_that_outlasts_its_retries"),
      "defect": "the listener survives nothing",
      "edits": [
         (
            PUMP,
            "= (TransportFailure, RateLimited)\n",
            "= ()\n",
         )
      ],
   },
   {
      "gate": gate("test_the_listener_waits_the_behaviors_poll_interval"),
      "defect": "the interval ignores the behavior setting",
      "edits": [
         (
            AIO,
            "            interval_seconds=self._behavior.poll_interval_seconds,\n",
            "            interval_seconds=60.0,\n",
         )
      ],
   },
   {
      "gate": gate("test_the_poll_interval_defaults_to_a_minute_and_refuses_a_negative"),
      "defect": "a negative poll interval is accepted",
      "edits": [
         (
            BEHAVIOR,
            "      if has_negative_interval:\n         raise ValueError",
            "      if False:\n         raise ValueError",
         )
      ],
   },
   {
      "gate": gate("test_since_is_never_delivered_again"),
      "defect": "since is not counted as delivered",
      "edits": [
         (
            PUMP,
            "   if since is not None:\n      seen.add(since)\n",
            "",
         )
      ],
   },
   {
      "gate": gate("test_the_blocking_listener_hands_since_to_its_source"),
      "defect": "the blocking facade drops since",
      "edits": [
         (
            CLIENT,
            "         return async_client._poll_for_events(emit, since=since)\n",
            "         return async_client._poll_for_events(emit, since=None)\n",
         )
      ],
   },
   {
      "gate": gate("test_the_seen_id_memory_is_bounded"),
      "defect": "the seen ids are never forgotten",
      "edits": [
         (
            PUMP,
            "      while len(self._order) > self._capacity:\n",
            "      while False:\n",
         )
      ],
   },
   {
      "gate": gate("test_with_a_handler_events_go_to_it_on_its_own_thread_and_not_the_buffer"),
      "defect": "the handler is called on the loop thread",
      "edits": [
         (
            LISTENER,
            "         await self._pump(self._buffer.put)\n",
            "         await self._pump(self._on_event or self._buffer.put)\n",
         )
      ],
   },
   {
      "gate": gate("test_every_listener_method_is_in_the_snapshot_on_both_surfaces", PARITY),
      "defect": "the listener exclusion names a method no surface has",
      "edits": [
         (
            PARITY,
            'LISTENER_METHODS = {"events"}\n',
            'LISTENER_METHODS = {"events", "listen"}\n',
         )
      ],
   },
]


def run_gate(gate: str) -> subprocess.CompletedProcess[str]:
   """Run one gate in a subprocess that cannot read a stale `.pyc`.

   The reason is the one ``verify_cli_gates.py`` records: CPython validates cached bytecode
   against the source's size and its mtime in whole seconds, so a same-length edit applied and
   undone inside one second is invisible to that check.
   """

   environment = dict(os.environ)
   environment["PYTHONDONTWRITEBYTECODE"] = "1"

   for cached in ENGINE.glob("**/__pycache__"):
      shutil.rmtree(cached, ignore_errors=True)

   return subprocess.run(
      [sys.executable, "-B", "-m", "pytest", gate, "-q", "--no-header", "-p", "no:cacheprovider"],
      cwd=ENGINE,
      capture_output=True,
      text=True,
      env=environment,
      timeout=GATE_TIMEOUT_SECONDS,
   )


def apply_edits(edits: list[tuple[str, str, str]], gate: str) -> dict[Path, str]:
   originals: dict[Path, str] = {}

   try:
      for relative, find, replace in edits:
         path = ENGINE / relative
         originals.setdefault(path, path.read_text(encoding="utf-8"))
         current = path.read_text(encoding="utf-8")

         occurrences = current.count(find)

         if occurrences != 1:
            raise SystemExit(
               f"mutation anchor found {occurrences} times in {relative} for {gate}, "
               "expected exactly once"
            )

         path.write_text(current.replace(find, replace, 1), encoding="utf-8")
   except BaseException:
      restore(originals)

      raise

   return originals


def restore(originals: dict[Path, str]) -> None:
   for path, original in originals.items():
      path.write_text(original, encoding="utf-8")


def main() -> int:
   results = []

   for mutation in MUTATIONS:
      gate = str(mutation["gate"])
      edits = mutation["edits"]
      assert isinstance(edits, list)

      originals = apply_edits(edits, gate)

      try:
         mutated = run_gate(gate)
      finally:
         restore(originals)

      restored = run_gate(gate)

      results.append(
         {
            "gate": gate,
            "defect": mutation["defect"],
            "mutated_files": sorted({relative for relative, _, _ in edits}),
            "red_under_mutation": mutated.returncode != 0,
            "green_after_restore": restored.returncode == 0,
            "mutated_tail": mutated.stdout.strip().splitlines()[-1:],
         }
      )

   every_gate_fired = bool(results) and all(
      entry["red_under_mutation"] and entry["green_after_restore"] for entry in results
   )

   LOG_DIR.mkdir(parents=True, exist_ok=True)
   stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
   log_path = LOG_DIR / f"mutation-events-{stamp}.json"
   log_path.write_text(
      json.dumps({"every_gate_fired": every_gate_fired, "gates": results}, indent=2) + "\n",
      encoding="utf-8",
   )

   for entry in results:
      fired = entry["red_under_mutation"] and entry["green_after_restore"]
      status = "red then green" if fired else "DID NOT FIRE"
      print(f"{status}: {entry['gate'].split('::')[1]}  ({entry['defect']})")

   print(f"log written to {log_path}")

   return 0 if every_gate_fired else 1


if __name__ == "__main__":
   raise SystemExit(main())
