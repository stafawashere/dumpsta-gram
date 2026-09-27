"""Break the direct read side of E2 batch 1, watch each gate go red, restore.

Same harness and same rule as ``verify_notes_gates.py``: one mutation per entry below, only the
gate that should catch it is run, every anchor must be found exactly once, and every file is
restored from an in-memory copy in a ``finally`` so an interrupted run cannot leave a mutation
behind.

The mutations cover the inbox pages, the message requests and the unread counts: the row
mapper, the unread rule, the inbox cursor, the four requests, the two folders, both iterators,
the three commands, the namespace parity gates for the new methods, and the canary's three new
replay steps.

Run from ``engine/`` with ``uv run python scripts/verify_direct_read_gates.py``. Writes its
result to ``engine/logs/``.
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

PARSE = "dumpstagram/_private/web/parse/direct.py"
REQUESTS = "dumpstagram/_private/web/requests/direct.py"
CORE = "dumpstagram/_core/inbox.py"
NAMESPACE = "dumpstagram/namespaces/direct.py"
COMMANDS = "dumpstagram/_cli/commands/direct.py"
RENDER = "dumpstagram/_cli/render/direct.py"
CANARY = "dumpstagram/_private/web/canary.py"
GATES = "tests/test_direct_read.py"
PARITY_GATES = "tests/test_facade_parity.py"
DOCTOR_GATES = "tests/test_doctor.py"


def gate(name: str) -> str:
   return f"{GATES}::{name}"


def parity(name: str, qualified: str) -> str:
   return f"{PARITY_GATES}::{name}[{qualified}]"


def doctor(name: str) -> str:
   return f"{DOCTOR_GATES}::{name}"


UNREAD_RULE = gate(
   "test_a_row_is_unread_exactly_when_the_viewers_receipt_is_older_than_its_last_activity"
)
MARKED_OR_UNRECEIPTED = gate(
   "test_a_read_row_marked_unread_or_without_the_viewers_receipt_is_unread"
)
CURSOR_GATE = gate("test_the_first_page_hands_out_a_cursor_that_carries_its_mailbox")
FOREIGN_CURSOR = gate("test_a_cursor_no_inbox_page_handed_out_is_refused_before_anything_is_sent")
UNREAD_COUNTS = gate("test_the_unread_counts_read_the_inbox_then_the_pending_folder_as_one_load")
HAS_READ_TO_THE_END = (
   "   has_read_to_the_end = bool(watermarks) and max(watermarks) >= last_activity_ms\n"
)
SYNC_ITERATOR_RETURN = (
   '            operation="SyncClient.direct.iter_inbox",\n'
   "         )\n\n"
   "      return iterate_pages_blocking(read_page, limit=limit, after=after)"
)

MUTATIONS: list[dict[str, object]] = [
   {
      "gate": gate("test_the_first_page_maps_every_row_in_the_upstream_order_by_its_thread_fbid"),
      "defect": "thread_key is taken for thread_fbid",
      "edits": [
         (
            PARSE,
            'thread_fbid=_required_string(row, "thread_fbid", row_path),',
            'thread_fbid=_required_string(row, "thread_key", row_path),',
         )
      ],
   },
   {
      "gate": UNREAD_RULE,
      "defect": "a receipt equal to the last activity counts as unread",
      "edits": [
         (
            PARSE,
            "max(watermarks) >= last_activity_ms",
            "max(watermarks) > last_activity_ms",
         )
      ],
   },
   {
      "gate": UNREAD_RULE,
      "defect": "the other person's receipt is read as the viewer's",
      "edits": [
         (
            PARSE,
            "is_the_participant = participant == participant_fbid",
            "is_the_participant = participant != participant_fbid",
         )
      ],
   },
   {
      "gate": MARKED_OR_UNRECEIPTED,
      "defect": "the marked unread flag is ignored",
      "edits": [
         (
            PARSE,
            "return is_marked_unread or not has_read_to_the_end",
            "return not has_read_to_the_end",
         )
      ],
   },
   {
      "gate": MARKED_OR_UNRECEIPTED,
      "defect": "a row without the viewer's receipt reads as read",
      "edits": [
         (
            PARSE,
            HAS_READ_TO_THE_END,
            "   has_read_to_the_end = (\n"
            "      max(watermarks, default=last_activity_ms) >= last_activity_ms\n"
            "   )\n",
         )
      ],
   },
   {
      "gate": gate("test_participants_are_the_other_users_by_their_account_id"),
      "defect": "a participant is keyed on the messaging id",
      "edits": [
         (
            PARSE,
            'user_id=_required_string(user, "id", path),',
            'user_id=_required_string(user, "interop_messaging_user_fbid", path),',
         )
      ],
   },
   {
      "gate": gate("test_the_newest_carried_message_names_the_last_message_and_the_snippet"),
      "defect": "the oldest carried message is read as the newest",
      "edits": [(PARSE, "   newest_edge = edges[0]\n", "   newest_edge = edges[-1]\n")],
   },
   {
      "gate": gate("test_the_newest_carried_message_names_the_last_message_and_the_snippet"),
      "defect": "the snippet is taken from the message text",
      "edits": [
         (
            PARSE,
            '_optional_string(newest, "igd_snippet", newest_path)',
            '_optional_string(newest, "text_body", newest_path)',
         )
      ],
   },
   {
      "gate": gate("test_the_flags_and_the_last_activity_come_from_their_own_keys"),
      "defect": "is_pinned is read from is_muted",
      "edits": [
         (
            PARSE,
            'is_pinned=_required_flag(row, "is_pin", row_path),',
            'is_pinned=_required_flag(row, "is_muted", row_path),',
         )
      ],
   },
   {
      "gate": gate("test_the_flags_and_the_last_activity_come_from_their_own_keys"),
      "defect": "the last activity is read as seconds",
      "edits": [
         (
            PARSE,
            "last_activity_at=datetime.fromtimestamp(last_activity_ms / MILLISECONDS_PER_SECOND,",
            "last_activity_at=datetime.fromtimestamp(last_activity_ms / 1,",
         )
      ],
   },
   {
      "gate": gate("test_the_next_page_maps_under_its_own_root_and_names_the_same_mailbox"),
      "defect": "the next page is read from the first page's root",
      "edits": [
         (
            PARSE,
            "return _thread_page(payload, INBOX_NEXT_PAGE_MAILBOX_PATH)",
            "return _thread_page(payload, INBOX_MAILBOX_PATH)",
         )
      ],
   },
   {
      "gate": gate("test_both_request_folders_map_from_their_own_root"),
      "defect": "the pending folder is read from the spam root",
      "edits": [
         (
            PARSE,
            "pending = _thread_page(payload, PENDING_REQUESTS_PATH).page",
            "pending = _thread_page(payload, SPAM_REQUESTS_PATH).page",
         )
      ],
   },
   {
      "gate": gate("test_the_unread_rows_are_counted_for_the_mailbox_as_the_viewer"),
      "defect": "the viewer of the unread rows is taken from a receipt",
      "edits": [
         (
            PARSE,
            "      if _is_unread(thread, viewer_fbid, thread_path):",
            "      other = next(\n"
            '         receipt["participant_fbid"]\n'
            '         for receipt in thread["slide_read_receipts"]\n'
            '         if receipt["participant_fbid"] != viewer_fbid\n'
            "      )\n\n"
            "      if _is_unread(thread, other, thread_path):",
         )
      ],
   },
   {
      "gate": gate("test_the_next_page_request_is_the_one_replayed_live"),
      "defect": "the next page asks for the thread page size",
      "edits": [(REQUESTS, '"count": INBOX_PAGE_SIZE,', '"count": PAGE_SIZE,')],
   },
   {
      "gate": gate("test_the_next_page_request_is_the_one_replayed_live"),
      "defect": "the next page carries another referer",
      "edits": [
         (
            REQUESTS,
            "      DIRECT_INBOX_NEXT_PAGE,\n      variables,\n      referer=BOOTSTRAP_URL,",
            "      DIRECT_INBOX_NEXT_PAGE,\n      variables,\n      referer=ORIGIN,",
         )
      ],
   },
   {
      "gate": gate("test_the_requests_query_sends_the_thirty_day_bound_as_an_integer"),
      "defect": "the requests bound is sent as a string",
      "edits": [
         (
            REQUESTS,
            '"__relay_internal__pv__IGD30DayAgoTimestampMsrelayprovider": '
            "now_ms - REQUESTS_WINDOW_MS,",
            '"__relay_internal__pv__IGD30DayAgoTimestampMsrelayprovider": str(\n'
            "         now_ms - REQUESTS_WINDOW_MS\n      ),",
         )
      ],
   },
   {
      "gate": gate("test_only_the_pending_folder_carries_the_thirty_day_bound_as_a_string"),
      "defect": "the inbox folder carries the thirty day bound too",
      "edits": [
         (
            REQUESTS,
            "   is_the_pending_folder = folder == PENDING_FOLDER\n",
            "   is_the_pending_folder = True\n",
         )
      ],
   },
   {
      "gate": CURSOR_GATE,
      "defect": "the first page hands out the upstream cursor without its mailbox",
      "edits": [
         (
            CORE,
            "      end_cursor = inbox_cursor(inbox_page.mailbox_id, upstream_cursor)",
            "      end_cursor = upstream_cursor",
         )
      ],
   },
   {
      "gate": CURSOR_GATE,
      "defect": "the cursor is split the wrong way round",
      "edits": [
         (
            CORE,
            "      mailbox_id, upstream_cursor = next_page_key",
            "      upstream_cursor, mailbox_id = next_page_key",
         )
      ],
   },
   {
      "gate": FOREIGN_CURSOR,
      "defect": "a foreign cursor is sent upstream",
      "edits": [
         (
            CORE,
            "   is_an_inbox_cursor = bool(separator) and names_a_mailbox and bool(upstream_cursor)",
            "   is_an_inbox_cursor = True",
         )
      ],
   },
   {
      "gate": UNREAD_COUNTS,
      "defect": "the inbox count reads the pending folder",
      "edits": [
         (
            CORE,
            "         folder=INBOX_FOLDER,\n",
            "         folder=PENDING_FOLDER,\n",
         )
      ],
   },
   {
      "gate": UNREAD_COUNTS,
      "defect": "the two folders are sent with two device ids",
      "edits": [
         (
            CORE,
            "iris_device_id=device_id,\n         folder=PENDING_FOLDER,",
            "iris_device_id=str(uuid.uuid4()),\n         folder=PENDING_FOLDER,",
         )
      ],
   },
   {
      "gate": gate("test_the_async_inbox_walk_crosses_to_the_next_page_query"),
      "defect": "the awaitable walk asks for the first page again",
      "edits": [
         (
            NAMESPACE,
            "iterate_pages(lambda cursor: self.inbox(after=cursor), limit=limit, after=after)",
            "iterate_pages(lambda cursor: self.inbox(after=None), limit=limit, after=after)",
         )
      ],
   },
   {
      "gate": gate("test_the_blocking_inbox_walk_crosses_to_the_next_page_query"),
      "defect": "the blocking walk asks for the first page again",
      "edits": [
         (
            NAMESPACE,
            "            client._impl.direct.inbox(after=cursor),\n"
            '            operation="SyncClient.direct.iter_inbox",',
            "            client._impl.direct.inbox(after=None),\n"
            '            operation="SyncClient.direct.iter_inbox",',
         )
      ],
   },
   {
      "gate": gate("test_dumpsta_inbox_walks_on_the_pages_own_cursor_and_stops_on_its_terminator"),
      "defect": "the command passes its first cursor again",
      "edits": [
         (
            COMMANDS,
            "      cursor = page.end_cursor\n\n   return pages",
            "      cursor = arguments.after\n\n   return pages",
         )
      ],
   },
   {
      "gate": gate("test_dumpsta_inbox_walks_on_the_pages_own_cursor_and_stops_on_its_terminator"),
      "defect": "the command reads past a last page",
      "edits": [
         (
            COMMANDS,
            "      pages.append(page)\n\n      if not page.has_next_page:\n         break\n\n"
            "      cursor = page.end_cursor\n\n   return pages",
            "      pages.append(page)\n\n      cursor = page.end_cursor\n\n   return pages",
         )
      ],
   },
   {
      "gate": gate("test_dumpsta_unread_marks_a_count_taken_over_part_of_a_folder"),
      "defect": "a partial inbox count is printed as the whole folder's",
      "edits": [(RENDER, 'inbox_bound = "+" if counts.inbox_has_more else ""', 'inbox_bound = ""')],
   },
   {
      "gate": gate("test_dumpsta_message_requests_prints_both_folders"),
      "defect": "the spam folder is left out of the JSON form",
      "edits": [
         (
            RENDER,
            '      "spam": [describe_thread(thread) for thread in requests.spam],\n',
            "",
         )
      ],
   },
   {
      "gate": parity(
         "test_a_namespace_method_reaches_the_core_capability_the_table_names",
         "direct.message_requests",
      ),
      "defect": "message_requests reaches the unread counts' core function",
      "edits": [
         (
            NAMESPACE,
            "         read_message_requests(\n",
            "         read_unread_counts(\n",
         )
      ],
   },
   {
      "gate": parity(
         "test_a_blocking_namespace_method_forwards_every_argument_on_the_loop_thread",
         "direct.inbox",
      ),
      "defect": "the blocking inbox drops its cursor",
      "edits": [
         (
            NAMESPACE,
            "         self._client._impl.direct.inbox(after=after),\n",
            "         self._client._impl.direct.inbox(after=None),\n",
         )
      ],
   },
   {
      "gate": parity(
         "test_a_blocking_namespace_method_raises_the_async_exception_under_its_own_name",
         "direct.unread_counts",
      ),
      "defect": "the blocking unread counts names another method in its seam note",
      "edits": [
         (
            NAMESPACE,
            'operation="SyncClient.direct.unread_counts",',
            'operation="SyncClient.direct.inbox",',
         )
      ],
   },
   {
      "gate": parity(
         "test_both_iterators_forward_every_argument_and_yield_the_same_items",
         "direct.iter_inbox",
      ),
      "defect": "the blocking inbox walk drops its starting cursor",
      "edits": [
         (
            NAMESPACE,
            SYNC_ITERATOR_RETURN,
            SYNC_ITERATOR_RETURN.replace("after=after)", "after=None)"),
         )
      ],
   },
   {
      "gate": doctor("test_every_read_replays_ok_when_each_answer_is_one_its_mapper_accepts"),
      "defect": "the canary reads the next page with the first page's mapper",
      "edits": [
         (
            CANARY,
            "      read=_mapped_by(parse_inbox_next_page),",
            "      read=_mapped_by(parse_inbox_listing),",
         )
      ],
   },
   {
      "gate": doctor("test_a_read_whose_argument_was_never_learned_is_skipped_and_not_sent"),
      "defect": "the canary sends the next page with no cursor learned",
      "edits": [
         (
            CANARY,
            '      query=DIRECT_INBOX_NEXT_PAGE,\n      requires="inbox_cursor",',
            '      query=DIRECT_INBOX_NEXT_PAGE,\n      requires="viewer_id",',
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
   log_path = LOG_DIR / f"mutation-direct-read-{stamp}.json"
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
