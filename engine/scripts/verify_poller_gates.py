"""Break the inbox poller and what Step 23 built around it, watch each gate go red, restore.

Same harness and same rule as ``verify_events_gates.py``: one mutation per line below, only the
gate that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

Run from ``engine/`` with ``uv run python scripts/verify_poller_gates.py``. Writes its result to
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
CLI = "dumpstagram/_cli/main.py"
PARSE = "dumpstagram/_private/web/parse.py"
POLLER = "dumpstagram/_core/realtime/poller.py"
PUMP = "dumpstagram/_core/realtime/pump.py"
RENDER = "dumpstagram/_cli/render.py"
POLLER_GATES = "tests/test_poller.py"
INBOX_GATES = "tests/test_inbox_listing.py"
CLI_GATES = "tests/test_cli.py"


def gate(name: str, suite: str = POLLER_GATES) -> str:
   return f"{suite}::{name}"


MUTATIONS: list[dict[str, object]] = [
   {
      "gate": gate("test_the_first_poll_reads_the_inbox_once_and_delivers_nothing"),
      "defect": "the first poll takes the whole inbox as new",
      "edits": [
         (
            POLLER,
            "      newest_before = self._newest_activity_ms\n",
            "      newest_before = self._newest_activity_ms or 0\n",
         )
      ],
   },
   {
      "gate": gate("test_a_quiet_inbox_costs_one_request_a_poll_and_delivers_nothing"),
      "defect": "every row with a message is read back, moved or not",
      "edits": [
         (
            POLLER,
            "         gained_a_message = newest_id_moved and has_a_newest_message\n",
            "         gained_a_message = has_a_newest_message\n",
         )
      ],
   },
   {
      "gate": gate("test_a_thread_that_gained_messages_delivers_exactly_those"),
      "defect": "the read back does not stop at the known message",
      "edits": [
         (
            POLLER,
            "            is_the_known_message = message.id == known_message_id\n",
            "            is_the_known_message = False\n",
         )
      ],
   },
   {
      "gate": gate("test_paging_back_follows_the_cursor_to_the_known_message"),
      "defect": "the read back drops the cursor",
      "edits": [(POLLER, "         cursor = page.end_cursor\n", "         cursor = None\n")],
   },
   {
      "gate": gate("test_a_thread_past_the_page_bound_leaves_a_marker_for_that_thread"),
      "defect": "a read back that hits its bound says nothing",
      "edits": [
         (
            POLLER,
            "   if not catch_up.reached_the_known_point:\n",
            "   if False:\n",
         )
      ],
   },
   {
      "gate": gate("test_a_known_message_that_was_removed_still_closes_the_gap"),
      "defect": "the read back pages on past the known point in time",
      "edits": [
         (
            POLLER,
            "            is_older_than_the_known_point = sent_at_ms(message) < known_ms\n",
            "            is_older_than_the_known_point = False\n",
         )
      ],
   },
   {
      "gate": gate(
         "test_a_thread_new_to_the_first_page_delivers_only_what_is_newer_than_the_last_poll"
      ),
      "defect": "a thread new to the first page is read from its first message",
      "edits": [
         (
            POLLER,
            "               row.thread_fbid, known_message_id=None, known_ms=newest_before\n",
            "               row.thread_fbid, known_message_id=None, known_ms=0\n",
         )
      ],
   },
   {
      "gate": gate("test_since_carried_by_a_row_is_caught_up_from_without_a_search"),
      "defect": "since is never looked for among the carried messages",
      "edits": [
         (
            POLLER,
            "      since_ms = carried_time_of(self._since, listing)\n",
            "      since_ms = None\n",
         )
      ],
   },
   {
      "gate": gate("test_since_found_on_a_thread_page_is_caught_up_from_that_same_page"),
      "defect": "the searched page is read again for the catch up",
      "edits": [
         (
            POLLER,
            "            first_page=searched_pages.get(row.thread_fbid),\n",
            "            first_page=None,\n",
         )
      ],
   },
   {
      "gate": gate("test_a_since_nowhere_to_be_found_is_reported_and_the_listener_carries_on"),
      "defect": "an unplaceable since is skipped in silence",
      "edits": [
         (
            POLLER,
            "         return [EventsDropped(count=None)]\n",
            "         return []\n",
         )
      ],
   },
   {
      "gate": gate("test_a_first_page_ending_newer_than_the_last_poll_is_reported"),
      "defect": "changes past the first page of the inbox are taken as none",
      "edits": [
         (
            POLLER,
            "   return listing.rows[-1].last_activity_ms > point_ms\n",
            "   return False\n",
         )
      ],
   },
   {
      "gate": gate("test_a_poll_sends_only_the_listing_and_the_scrolling_query"),
      "defect": "a thread is read back by opening it, as a browser does before marking it seen",
      "edits": [
         (
            POLLER,
            "         return build_thread_older_page_request(\n"
            "            self._session, thread_fbid, after=after, user_agent=self._user_agent\n"
            "         )\n",
            "         return build_thread_detail_request(\n"
            "            self._session, thread_fbid, user_agent=self._user_agent\n"
            "         )\n",
         ),
         (
            POLLER,
            "   build_inbox_listing_request,\n",
            "   build_inbox_listing_request,\n   build_thread_detail_request,\n",
         ),
      ],
   },
   {
      "gate": gate("test_a_stale_token_is_fetched_once_within_the_poll"),
      "defect": "the poll gives up on a stale token",
      "edits": [
         (
            POLLER,
            "      return await with_one_token_recovery(attempt, session=self._session)\n",
            "      return await attempt()\n",
         )
      ],
   },
   {
      "gate": gate("test_a_poll_makes_one_attempt_and_leaves_the_retry_to_the_pump"),
      "defect": "the poll retries inside the pump's retry",
      "edits": [
         (
            POLLER,
            "from dumpstagram._core.tokens import with_one_token_recovery\n",
            "from dumpstagram._core.tokens import with_token_recovery\n",
         ),
         (
            POLLER,
            "      return await with_one_token_recovery(attempt, session=self._session)\n",
            "      return await with_token_recovery(\n"
            "         attempt, sender=self._sender, session=self._session\n"
            "      )\n",
         ),
      ],
   },
   {
      "gate": gate("test_every_request_a_poll_sends_passes_the_accounts_pacer"),
      "defect": "the poller reaches past the paced sender to the transport",
      "edits": [
         (
            POLLER,
            "      self._sender = context.sender\n",
            "      self._sender = context.sender._sender  # type: ignore[assignment]\n",
         )
      ],
   },
   {
      "gate": gate("test_a_client_polls_the_inbox_by_default"),
      "defect": "the client keeps a source that never reads the inbox",
      "edits": [
         (
            AIO,
            "      self._event_source: SourceFactory = inbox_poller\n",
            "      self._event_source: SourceFactory = lambda context: type(\n"
            '         "Silent", (), {"poll": lambda self: asyncio.sleep(0, ())}\n'
            "      )()\n",
         )
      ],
   },
   {
      "gate": gate("test_a_gap_a_source_reports_reaches_the_consumer_ahead_of_that_polls_messages"),
      "defect": "the pump drops a source's gap marker",
      "edits": [
         (
            PUMP,
            "      for gap in gaps:\n         emit(gap)\n",
            "      for gap in gaps:\n         pass\n",
         )
      ],
   },
   {
      "gate": gate("test_each_rows_carried_messages_map_in_order_with_their_times", INBOX_GATES),
      "defect": "a row's carried messages come out reversed",
      "edits": [
         (
            PARSE,
            "   return tuple(carried)\n",
            "   return tuple(reversed(carried))\n",
         )
      ],
   },
   {
      "gate": gate("test_events_prints_one_json_object_per_event_and_a_summary", CLI_GATES),
      "defect": "--json is ignored for the event stream",
      "edits": [
         (
            CLI,
            "      if arguments.json:\n"
            "         line = json.dumps(describe_event(event, ids_only=arguments.ids_only))\n",
            "      if False:\n"
            "         line = json.dumps(describe_event(event, ids_only=arguments.ids_only))\n",
         )
      ],
   },
   {
      "gate": gate("test_events_ids_only_never_prints_a_messages_text_or_sender_name", CLI_GATES),
      "defect": "--ids-only still prints the message in the JSON form",
      "edits": [
         (
            RENDER,
            "      if not ids_only:\n"
            '         return {"event": "new_message", "message": describe_message(message)}\n',
            "      if True:\n"
            '         return {"event": "new_message", "message": describe_message(message)}\n',
         )
      ],
   },
   {
      "gate": gate("test_events_ids_only_never_prints_a_messages_text_or_sender_name", CLI_GATES),
      "defect": "--ids-only still prints the message in the text form",
      "edits": [
         (
            RENDER,
            "      if ids_only:\n         return line\n",
            "      if False:\n         return line\n",
         )
      ],
   },
   {
      "gate": gate("test_events_stops_the_listener_when_the_duration_ends", CLI_GATES),
      "defect": "the command returns with its listener still running",
      "edits": [
         (
            CLI,
            "   finally:\n      listener.stop()\n",
            "   finally:\n      pass\n",
         )
      ],
   },
   {
      "gate": gate(
         "test_a_listener_stopped_by_a_checkpoint_exits_with_the_checkpoint_code", CLI_GATES
      ),
      "defect": "the listener's final event is printed and ignored",
      "edits": [
         (
            CLI,
            "      if isinstance(event, ListenerStopped):\n         raise event.error\n",
            "      if isinstance(event, ListenerStopped):\n         return\n",
         )
      ],
   },
   {
      "gate": gate("test_events_on_the_async_surface_reads_the_async_iterator", CLI_GATES),
      "defect": "--surface async runs the blocking listener",
      "edits": [(CLI, '   if arguments.surface == "async":\n', "   if False:\n")],
   },
   {
      "gate": gate("test_events_on_the_async_surface_reads_the_async_iterator", CLI_GATES),
      "defect": "--interval never reaches the client's behavior",
      "edits": [
         (
            CLI,
            "   return replace(PARITY, poll_interval_seconds=arguments.interval)\n",
            "   return PARITY\n",
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
   log_path = LOG_DIR / f"mutation-poller-{stamp}.json"
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
