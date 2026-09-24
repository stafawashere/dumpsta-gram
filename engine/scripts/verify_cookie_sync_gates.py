"""Break the page-load cookie sync tail, watch each of its gates go red, restore.

Same harness and same rule as ``verify_page_load_gates.py``: one mutation per line below, only
the gate that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

Run from ``engine/`` with ``uv run python scripts/verify_cookie_sync_gates.py``. Writes its
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


SYNC = "dumpstagram/_core/cookie_sync.py"
ADAPTER = "dumpstagram/_private/web/cookie_sync.py"
REQUESTING = "dumpstagram/_core/requesting.py"
PROFILES = "dumpstagram/_core/profiles.py"
CLIENT = "dumpstagram/aio.py"
PROFILES_NAMESPACE = "dumpstagram/namespaces/profiles.py"
BEHAVIOR = "dumpstagram/behavior.py"
GATES = "tests/test_cookie_sync.py"


WAIT_THEN_SEND = (
   "      await self.pacer.wait_out_hold()\n\n      return await self._sender.send(request)\n"
)


def gate(name: str) -> str:
   return f"{GATES}::{name}"


MUTATIONS: list[dict[str, object]] = [
   {
      "gate": gate("test_a_home_load_leaves_the_recorded_tail"),
      "defect": "the iframe's fetch goes out ahead of the exchange",
      "edits": [
         (
            SYNC,
            "         group.create_task(self._exchange_fr(session, page_url, user_agent))\n"
            "         group.create_task(self._relay(session, parameters, page_url, user_agent))\n",
            "         group.create_task(self._relay(session, parameters, page_url, user_agent))\n"
            "         group.create_task(self._exchange_fr(session, page_url, user_agent))\n",
         )
      ],
   },
   {
      "gate": gate("test_a_home_load_leaves_the_recorded_tail"),
      "defect": "the two flows run one after the other",
      "edits": [
         (
            SYNC,
            "      async with asyncio.TaskGroup() as group:\n"
            "         group.create_task(self._exchange_fr(session, page_url, user_agent))\n"
            "         group.create_task(self._relay(session, parameters, page_url, user_agent))\n",
            "      await self._exchange_fr(session, page_url, user_agent)\n"
            "      await self._relay(session, parameters, page_url, user_agent)\n",
         )
      ],
   },
   {
      "gate": gate("test_each_tail_request_goes_through_its_own_hosts_transport"),
      "defect": "the iframe's fetch goes through the transport carrying the account's cookies",
      "edits": [
         (
            SYNC,
            "fetched = await self._facebook.send(",
            "fetched = await self._instagram.send(",
         )
      ],
   },
   {
      "gate": gate("test_the_tail_departs_at_the_captured_delays_after_the_document"),
      "defect": "the tail leaves as soon as the document action ends",
      "edits": [
         (
            SYNC,
            "      await self._pacer.sleep(max(0.0, iframe_departs_at - self._pacer.now()))\n",
            "",
         )
      ],
   },
   {
      "gate": gate("test_the_tail_departs_at_the_captured_delays_after_the_document"),
      "defect": "the exchange goes out with no wait for the iframe to be ready",
      "edits": [(SYNC, "READY_GAP_SECONDS = (0.15, 2.45)", "READY_GAP_SECONDS = (0.0, 2.45)")],
   },
   {
      "gate": gate("test_the_delay_is_measured_from_the_documents_departure"),
      "defect": "the delay is counted from when the tail starts",
      "edits": [
         (
            SYNC,
            "      await self._pacer.sleep(max(0.0, iframe_departs_at - self._pacer.now()))\n",
            "      await self._pacer.sleep(self._draw(*IFRAME_DELAY_SECONDS))\n",
         )
      ],
   },
   {
      "gate": gate("test_the_tail_holds_no_pacer_slot"),
      "defect": "each tail request takes a pacer slot",
      "edits": [
         (
            REQUESTING,
            WAIT_THEN_SEND,
            "      async with self.pacer.slot():\n"
            "         return await self._sender.send(request)\n",
         )
      ],
   },
   {
      "gate": gate("test_the_next_action_is_spaced_from_the_document_and_not_from_the_tail"),
      "defect": "a tail request is recorded as the account's latest departure",
      "edits": [
         (
            REQUESTING,
            WAIT_THEN_SEND,
            "      await self.pacer.wait_out_hold()\n"
            "      self.pacer._last_departure_at = self.pacer.now()\n\n"
            "      return await self._sender.send(request)\n",
         )
      ],
   },
   {
      "gate": gate("test_the_tail_waits_out_a_throttle_hold"),
      "defect": "the tail ignores an account-wide hold",
      "edits": [
         (
            REQUESTING,
            WAIT_THEN_SEND,
            "      return await self._sender.send(request)\n",
         )
      ],
   },
   {
      "gate": gate("test_a_checkpointed_session_departs_nothing"),
      "defect": "the tail does not look at the checkpoint before the iframe document",
      "edits": [
         (
            SYNC,
            "      if session.checkpoint_active:\n         return\n\n      try:\n"
            "         document = ",
            "      try:\n         document = ",
         )
      ],
   },
   {
      "gate": gate("test_a_checkpoint_on_the_exchange_is_recorded_and_stops_the_post_back"),
      "defect": "a checkpoint on the exchange is not recorded on the session",
      "edits": [
         (
            SYNC,
            "         session.checkpoint_active = True\n         return\n",
            "         return\n",
         )
      ],
   },
   {
      "gate": gate("test_a_checkpoint_on_the_exchange_is_recorded_and_stops_the_post_back"),
      "defect": "the post back does not look at the checkpoint",
      "edits": [
         (
            SYNC,
            "      if session.checkpoint_active:\n         return\n\n      request = ",
            "      request = ",
         )
      ],
   },
   {
      "gate": gate("test_a_failing_tail_never_reaches_the_caller"),
      "defect": "a transport failure on the exchange escapes the tail",
      "edits": [
         (
            SYNC,
            "         answer = read_fr(response)\n      except DumpstagramError as failure:\n",
            "         answer = read_fr(response)\n      except CheckpointRequired as failure:\n",
         )
      ],
   },
   {
      "gate": gate("test_fr_follows_the_pages_rule"),
      "defect": "an empty answer is stored instead of removing fr",
      "edits": [(SYNC, "      session.fr = answer or None\n", "      session.fr = answer\n")],
   },
   {
      "gate": gate("test_fr_follows_the_pages_rule"),
      "defect": "the exchange sends no stored fr",
      "edits": [(ADAPTER, '"payload": session.fr}', '"payload": None}')],
   },
   {
      "gate": gate("test_a_failed_exchange_removes_fr_and_a_failed_fetch_does_not"),
      "defect": "a failed exchange keeps the stored fr",
      "edits": [
         (
            SYNC,
            "         session.fr = None\n         self._record(session, failure)\n",
            "         self._record(session, failure)\n",
         )
      ],
   },
   {
      "gate": gate("test_the_facebook_requests_carry_the_iframe_documents_parameters"),
      "defect": "the iframe's fetch carries no lsd from its document",
      "edits": [(ADAPTER, '"x-fb-lsd": parameters.lsd or "",', '"x-fb-lsd": "",')],
   },
   {
      "gate": gate("test_the_facebook_requests_carry_the_iframe_documents_parameters"),
      "defect": "the iframe document is requested as a top-level navigation",
      "edits": [(ADAPTER, '"sec-fetch-dest": "iframe",', '"sec-fetch-dest": "document",')],
   },
   {
      "gate": gate("test_the_post_back_carries_the_fetched_blob_in_the_page_envelope"),
      "defect": "the blob is dropped between the two hosts",
      "edits": [(ADAPTER, '"encrypted_data": encrypted_data,', '"encrypted_data": "",')],
   },
   {
      "gate": gate("test_a_profile_load_leaves_the_tail_with_the_profile_as_referer"),
      "defect": "the profile route starts no tail",
      "edits": [
         (
            PROFILES,
            "      if cookie_sync is not None:\n         cookie_sync.start(",
            "      if False:\n         cookie_sync.start(",
         )
      ],
   },
   {
      "gate": gate("test_a_page_the_sync_exempts_starts_nothing"),
      "defect": "the page's path rule is dropped",
      "edits": [
         (
            ADAPTER,
            "   return not any(marker in path for marker in SKIPPED_PATH_MARKERS)\n",
            "   return True\n",
         )
      ],
   },
   {
      "gate": gate("test_a_newer_load_replaces_a_pending_tail"),
      "defect": "a newer load leaves the pending tail running",
      "edits": [
         (
            SYNC,
            "      self.drop()\n\n      is_exempt_page",
            "      is_exempt_page",
         )
      ],
   },
   {
      "gate": gate("test_closing_cancels_a_pending_tail_and_starts_no_more"),
      "defect": "a closed sync still starts tails",
      "edits": [
         (SYNC, "      self._closed = True\n      tail = self._tail\n", "      tail = self._tail\n")
      ],
   },
   {
      "gate": gate("test_every_preset_runs_the_cookie_sync"),
      "defect": "the parity default is the departure",
      "edits": [(BEHAVIOR, "   cookie_sync: bool = True\n", "   cookie_sync: bool = False\n")],
   },
   {
      "gate": gate("test_the_client_leaves_a_tail_after_both_document_routes"),
      "defect": "the client does not pass the sync to the profile route",
      "edits": [
         (
            PROFILES_NAMESPACE,
            "            companions=client._behavior.page_load_companions,\n"
            "            cookie_sync=client._cookie_sync_if_on(),\n"
            "            user_agent=client._user_agent,\n"
            "         )\n      )\n\n   async def by_id",
            "            companions=client._behavior.page_load_companions,\n"
            "            user_agent=client._user_agent,\n"
            "         )\n      )\n\n   async def by_id",
         )
      ],
   },
   {
      "gate": gate("test_the_departure_drops_the_tail_and_nothing_else"),
      "defect": "the client ignores the setting",
      "edits": [
         (
            CLIENT,
            "      return self._cookie_sync if self._behavior.cookie_sync else None\n",
            "      return self._cookie_sync\n",
         )
      ],
   },
   {
      "gate": gate("test_the_departure_drops_the_tail_and_nothing_else"),
      "defect": "the page load companions setting governs the tail",
      "edits": [
         (
            CLIENT,
            "if self._behavior.cookie_sync else None",
            "if self._behavior.page_load_companions else None",
         )
      ],
   },
   {
      "gate": gate("test_a_checkpoint_on_a_later_call_drops_the_pending_tail"),
      "defect": "a checkpoint on a later call leaves the pending tail running",
      "edits": [
         (
            CLIENT,
            "         self._cookie_sync.drop()\n         raise\n",
            "         raise\n",
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
   log_path = LOG_DIR / f"mutation-cookie-sync-{stamp}.json"
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
