"""Break E2 batch 9, the direct inbox's page load, watch each gate go red, restore.

Same harness and same rule as ``verify_search_gates.py``: one mutation per entry below, only the
gate that should catch it is run, every anchor must be found exactly once, and every file is
restored from an in-memory copy in a ``finally`` so an interrupted run cannot leave a mutation
behind.

The mutations cover the burst's order, grouping and membership, the document's device id and the
fresh one that replaces it, the thread detail prefetches, the referer, which answer each read
takes, a refused or checkpointed answer nobody reads, the one action, the cookie sync tail, the
core's default route, the parity preset, the setting on its way down through the namespace, and
the inbox walk after a first page read from the load.

Run from ``engine/`` with ``uv run python scripts/verify_page_models_gates.py``. Writes its result
to ``engine/logs/``.
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

INBOX = "dumpstagram/_core/inbox.py"
NOTES = "dumpstagram/_core/notes.py"
PAGE_LOAD_REQUESTS = "dumpstagram/_private/web/requests/page_load.py"
PARSE = "dumpstagram/_private/web/parse/direct.py"
BEHAVIOR = "dumpstagram/behavior.py"
NAMESPACE = "dumpstagram/namespaces/direct.py"
GATES = "tests/test_page_models.py"


def gate(name: str) -> str:
   return f"{GATES}::{name}"


BURST = gate("test_an_inbox_load_sends_the_recorded_burst_in_its_groups")
IRIS = gate("test_the_iris_queries_carry_the_documents_device_id")
FRESH_ID = gate("test_a_document_without_a_device_id_keys_the_block_on_one_fresh_id")
DETAILS = gate("test_the_thread_details_are_the_first_pages_rows_pinned_first")
REFERER = gate("test_every_request_after_the_document_names_the_inbox_as_referer")
OWN_ANSWERS = gate("test_each_read_takes_its_own_answers_from_the_block")
REJECTED = gate("test_a_rejected_query_nobody_reads_does_not_cost_the_read")
CHECKPOINT = gate("test_a_checkpoint_anywhere_in_the_load_is_raised")
ONE_ACTION = gate("test_the_load_is_paced_as_one_action")
COOKIE_SYNC = gate("test_the_cookie_sync_starts_for_the_inbox_only_after_a_read_that_succeeded")
CORE_DEFAULT = gate("test_the_core_keeps_each_reads_own_queries_unless_told_otherwise")
PARITY_PRESET = gate("test_parity_reads_the_inbox_from_its_page")
CLIENT = gate("test_the_client_loads_the_inbox_for_each_of_the_three_reads")
DEPARTURES = gate("test_the_departures_send_what_they_name_and_nothing_else")
WALK = gate("test_the_blocking_walk_reads_the_first_page_from_the_load_then_the_next_page_query")

SCREEN = "            raise_only_what_concerns_the_account(response)\n"
STORIES_TRAY = "_companion(session, STORIES_TRAY, _stories_tray_variables(), referer, user_agent)"
LOGIN_SURFACE = "_companion(session, QUICK_PROMOTION, login_surface, referer, user_agent)"
TAIL_START = (
   "         cookie_sync.start(session, INBOX_PAGE_URL, loaded_at=loaded_at, "
   "user_agent=user_agent)\n"
)
BADGE_GROUP = "   groups = [\n      _badge_group(session, device_id, referer, user_agent),\n"
BADGE_DEVICE_ID = "               device_id=document_device_id,\n"


def mutation(gate: str, defect: str, relative: str, find: str, replace: str) -> dict[str, object]:
   return {"gate": gate, "defect": defect, "edits": [(relative, find, replace)]}


MUTATIONS: list[dict[str, object]] = [
   mutation(
      BURST,
      "the pending follow requests and the activity feed are left out",
      PAGE_LOAD_REQUESTS,
      "      thread_details,\n      account_reads,\n   ]",
      "      thread_details,\n   ]",
   ),
   mutation(
      BURST,
      "the presence setup and the inbox interstitial swap places in the block",
      PAGE_LOAD_REQUESTS,
      "      empty(PRESENCE_SETUP),\n      empty(INBOX_QP_INTERSTITIAL),\n",
      "      empty(INBOX_QP_INTERSTITIAL),\n      empty(PRESENCE_SETUP),\n",
   ),
   mutation(
      BURST,
      "the stories tray and the login interstitial go out as one group",
      PAGE_LOAD_REQUESTS,
      f"      [{STORIES_TRAY}],\n      [{LOGIN_SURFACE}],\n",
      f"      [\n         {STORIES_TRAY},\n         {LOGIN_SURFACE},\n      ],\n",
   ),
   mutation(
      BURST,
      "the thread details go out before the stories tray",
      PAGE_LOAD_REQUESTS,
      f"{BADGE_GROUP}      [_companion(",
      f"{BADGE_GROUP}      thread_details,\n      [_companion(",
   ),
   mutation(
      IRIS,
      "the badge count is keyed on a fresh id where the document carried one",
      INBOX,
      BADGE_DEVICE_ID,
      "               device_id=str(uuid.uuid4()),\n",
   ),
   mutation(
      IRIS,
      "the listing is keyed on a fresh id where the document carried one",
      INBOX,
      "build_inbox_listing_request(session, device_id=device_id, user_agent=user_agent)",
      "build_inbox_listing_request(session, device_id=str(uuid.uuid4()), user_agent=user_agent)",
   ),
   mutation(
      FRESH_ID,
      "the badge count goes out on the fresh id no document issued",
      INBOX,
      BADGE_DEVICE_ID,
      "               device_id=device_id,\n",
   ),
   mutation(
      FRESH_ID,
      "the pending folder draws an id of its own",
      INBOX,
      "            iris_device_id=device_id,\n            folder=PENDING_FOLDER,\n",
      "            iris_device_id=str(uuid.uuid4()),\n            folder=PENDING_FOLDER,\n",
   ),
   mutation(
      FRESH_ID,
      "a document without a device id fails the read",
      INBOX,
      "         device_id = document_device_id or str(uuid.uuid4())\n",
      '         device_id = document_device_id or ""\n'
      '         assert device_id, "the inbox document carried no device id"\n',
   ),
   mutation(
      DETAILS,
      "the prefetch is keyed on thread_fbid",
      PARSE,
      '   return _required_string(thread, "thread_key", thread_path)\n',
      '   return _required_string(thread, "thread_fbid", thread_path)\n',
   ),
   mutation(
      DETAILS,
      "the pinned threads are not sent first",
      PARSE,
      "   for index, item in enumerate(pinned):\n",
      "   for index, item in enumerate(pinned[:0]):\n",
   ),
   mutation(
      DETAILS,
      "the pinned threads are sent twice",
      PARSE,
      "   return tuple(dict.fromkeys(keys))\n",
      "   return tuple(keys)\n",
   ),
   mutation(
      DETAILS,
      "each detail claims its thread's page as referer",
      PAGE_LOAD_REQUESTS,
      "build_thread_detail_request(session, key, referer=referer, user_agent=user_agent)",
      "build_thread_detail_request(session, key, user_agent=user_agent)",
   ),
   mutation(
      REFERER,
      "the six empty block queries claim the home page",
      PAGE_LOAD_REQUESTS,
      "      return _companion(session, query, {}, INBOX_PAGE_URL, user_agent)\n",
      '      return _companion(session, query, {}, f"{ORIGIN}/", user_agent)\n',
   ),
   mutation(
      OWN_ANSWERS,
      "the inbox count takes the pending folder's answer",
      INBOX,
      "            inbox_unread_rows=answer_to[id(inbox_unread_rows)],\n",
      "            inbox_unread_rows=answer_to[id(pending_unread_rows)],\n",
   ),
   mutation(
      OWN_ANSWERS,
      "the notes read maps the listing's answer",
      NOTES,
      "         lambda answers: parse_inbox_tray(classify(answers.tray)),\n",
      "         lambda answers: parse_inbox_tray(classify(answers.listing)),\n",
   ),
   mutation(
      REJECTED,
      "every block answer is classified in full, so a refused one fails the read",
      INBOX,
      SCREEN,
      "            classify(response)\n",
   ),
   mutation(
      REJECTED,
      "a refused listing fails the thread detail keys",
      INBOX,
      "   except (UpstreamRejected, SchemaChanged):\n      return ()\n",
      "   except SchemaChanged:\n      return ()\n",
   ),
   mutation(
      CHECKPOINT,
      "the block's answers are not screened at all",
      INBOX,
      SCREEN,
      "            pass\n",
   ),
   mutation(
      ONE_ACTION,
      "each companion group is paced as an action of its own",
      INBOX,
      "            await send_companions(action, groups)\n\n      result = read(answers)",
      "            pass\n\n"
      "      if companions:\n"
      "         for group in groups:\n"
      "            async with sender.action() as own_action:\n"
      "               await send_companions(own_action, [group])\n\n"
      "      result = read(answers)",
   ),
   mutation(
      COOKIE_SYNC,
      "the tail is scheduled for the home page",
      INBOX,
      TAIL_START,
      '         cookie_sync.start(session, "https://www.instagram.com/", loaded_at=loaded_at)\n',
   ),
   mutation(
      COOKIE_SYNC,
      "the tail is scheduled before the read that can still fail",
      INBOX,
      f"      result = read(answers)\n\n      if cookie_sync is not None:\n{TAIL_START}",
      f"      if cookie_sync is not None:\n{TAIL_START}\n      result = read(answers)\n",
   ),
   mutation(
      CORE_DEFAULT,
      "the core's notes read defaults to the page load",
      NOTES,
      "   route: InboxRoute = InboxRoute.QUERIES,\n",
      "   route: InboxRoute = InboxRoute.PAGE,\n",
   ),
   mutation(
      PARITY_PRESET,
      "the parity preset defaults to the departure",
      BEHAVIOR,
      "   inbox_route: InboxRoute = InboxRoute.PAGE\n",
      "   inbox_route: InboxRoute = InboxRoute.QUERIES\n",
   ),
   mutation(
      CLIENT,
      "the namespace's notes drops the route on the way down",
      NAMESPACE,
      "         read_notes(\n"
      "            client._sender,\n"
      "            client._session,\n"
      "            route=client._behavior.inbox_route,\n",
      "         read_notes(\n            client._sender,\n            client._session,\n",
   ),
   mutation(
      CLIENT,
      "the namespace's unread counts drops the route on the way down",
      NAMESPACE,
      "         read_unread_counts(\n"
      "            client._sender,\n"
      "            client._session,\n"
      "            route=client._behavior.inbox_route,\n",
      "         read_unread_counts(\n            client._sender,\n            client._session,\n",
   ),
   mutation(
      DEPARTURES,
      "the companions go out whatever the setting says",
      INBOX,
      "         if companions:\n            groups = build_inbox_page_load_companions(",
      "         if True:\n            groups = build_inbox_page_load_companions(",
   ),
   mutation(
      WALK,
      "every inbox page is read from a fresh page load",
      INBOX,
      "   reads_the_page = next_page_key is None and route is InboxRoute.PAGE\n",
      "   reads_the_page = route is InboxRoute.PAGE\n",
   ),
   mutation(
      WALK,
      "the page load's first page hands out the upstream's bare cursor",
      INBOX,
      "         lambda answers: _public_page(parse_inbox_page(classify(answers.listing))),\n",
      "         lambda answers: parse_inbox_page(classify(answers.listing)).page,\n",
   ),
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
   log_path = LOG_DIR / f"mutation-page-models-{stamp}.json"
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
