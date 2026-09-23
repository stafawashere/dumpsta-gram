"""Break the profile page route, watch each of its gates go red, restore.

Same harness and same rule as ``verify_parity_gates.py``: one mutation per gate, only the gate
that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

Run from ``engine/`` with ``uv run python scripts/verify_profile_page_gates.py``. Writes its
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


PRELOAD = "dumpstagram/_private/web/preload.py"
REQUESTS = "dumpstagram/_private/web/requests.py"
PROFILES = "dumpstagram/_core/profiles.py"
PAGE_LOAD = "dumpstagram/_core/page_load.py"
REQUESTING = "dumpstagram/_core/requesting.py"
BEHAVIOR = "dumpstagram/behavior.py"
AIO = "dumpstagram/aio.py"
GATES = "tests/test_profile_page.py"

MUTATIONS: list[dict[str, object]] = [
   {
      "gate": f"{GATES}::test_the_id_reader_takes_the_account_the_page_is_about",
      "defect": "the reader takes the first number after any id key",
      "edits": [
         (
            PRELOAD,
            """_PROFILE_ID = re.compile(r'"page_id":"profilePage_(\\d+)","profile_id":"(\\d+)"')""",
            """_PROFILE_ID = re.compile(r'"(container)_id":"(\\d+)"')""",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_a_page_naming_two_accounts_raises_rather_than_one_being_picked",
      "defect": "two disagreeing accounts are resolved by picking one",
      "edits": [(PRELOAD, "   if len(account_ids) > 1:", "   if False:")],
   },
   {
      "gate": f"{GATES}::test_a_username_that_cannot_exist_is_refused_before_any_request",
      "defect": "any string is sent as the profile page path",
      "edits": [(REQUESTS, "   if not is_a_possible_username:", "   if False:")],
   },
   {
      "gate": (
         f"{GATES}::test_the_page_route_loads_the_page_then_sends_the_six_queries_in_page_order"
      ),
      "defect": "a companion is dropped from the burst",
      "edits": [(REQUESTS, '      (PROFILE_SCHOOL_BADGE, {"igid": user_id}),\n', "")],
   },
   {
      "gate": f"{GATES}::test_every_query_is_keyed_on_the_id_the_page_carried",
      "defect": "a companion is keyed on the username instead of the id",
      "edits": [
         (
            REQUESTS,
            '(PROFILE_NOTE_BUBBLE, {"user_id": user_id})',
            '(PROFILE_NOTE_BUBBLE, {"user_id": username})',
         )
      ],
   },
   {
      "gate": f"{GATES}::test_the_six_queries_are_in_flight_together",
      "defect": "the six queries are sent one after another",
      "edits": [
         (
            REQUESTING,
            """      async with asyncio.TaskGroup() as group:
         tasks = [group.create_task(self._sender.send(request)) for request in requests]

      return [task.result() for task in tasks]""",
            """      return [await self._sender.send(request) for request in requests]""",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_the_page_load_is_paced_as_one_action",
      "defect": "each request of the page load is paced as its own action",
      "edits": [
         (
            REQUESTING,
            "      async with self.pacer.slot(self.pacing):\n"
            "         yield ActionSender(self._sender)",
            "      yield ActionSender(self)",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_the_queries_carry_the_tokens_the_page_carried",
      "defect": "the page's fresh tokens are thrown away",
      "edits": [
         (
            PROFILES,
            "         apply_tokens(session, tokens_from(document))",
            "         tokens_from(document)",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_a_page_about_no_account_is_not_found_and_sends_no_query",
      "defect": "a page about no account is queried anyway",
      "edits": [(PROFILES, "         if user_id is None:", "         if False:")],
   },
   {
      "gate": f"{GATES}::test_a_companion_the_upstream_rejects_does_not_cost_the_profile",
      "defect": "a rejected companion fails the whole read",
      "edits": [
         (
            PAGE_LOAD,
            "   except (UpstreamRejected, SchemaChanged):\n      return",
            "   except SchemaChanged:\n      return",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_a_checkpoint_in_a_companion_is_raised",
      "defect": "companion responses are never looked at",
      "edits": [
         (
            PROFILES,
            "            raise_only_what_concerns_the_account(companion)",
            "            pass",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_parity_reads_a_profile_from_its_page",
      "defect": "the parity preset defaults to the departure",
      "edits": [
         (
            BEHAVIOR,
            "   profile_route: ProfileRoute = ProfileRoute.PAGE",
            "   profile_route: ProfileRoute = ProfileRoute.QUERIES",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_the_core_keeps_the_queries_route_unless_told_otherwise",
      "defect": "the core moves its callers onto the page route unasked",
      "edits": [
         (
            PROFILES,
            "   route: ProfileRoute = ProfileRoute.QUERIES,",
            "   route: ProfileRoute = ProfileRoute.PAGE,",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_the_client_loads_the_page_under_the_default_behavior",
      "defect": "the client drops the behavior setting",
      "edits": [(AIO, "         route=self._behavior.profile_route,\n", "")],
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
   log_path = LOG_DIR / f"mutation-profile-page-{stamp}.json"
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
