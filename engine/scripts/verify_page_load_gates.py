"""Break the page load companions, watch each of their gates go red, restore.

Same harness and same rule as ``verify_parity_gates.py``: one mutation per gate, only the gate
that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

Run from ``engine/`` with ``uv run python scripts/verify_page_load_gates.py``. Writes its
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


REQUESTS_PAGE_LOAD = "dumpstagram/_private/web/requests/page_load.py"
PRELOAD = "dumpstagram/_private/web/preload.py"
PAGE_LOAD = "dumpstagram/_core/page_load.py"
FEED = "dumpstagram/_core/feed.py"
FEEDS_NAMESPACE = "dumpstagram/namespaces/feeds.py"
PROFILES_NAMESPACE = "dumpstagram/namespaces/profiles.py"
BEHAVIOR = "dumpstagram/behavior.py"
GATES = "tests/test_page_load.py"

MUTATIONS: list[dict[str, object]] = [
   {
      "gate": f"{GATES}::test_a_home_load_sends_the_recorded_burst_in_its_groups",
      "defect": "the home badge count goes out after the jewel group",
      "edits": [
         (
            REQUESTS_PAGE_LOAD,
            "      _badge_group(session, device_id, referer, user_agent),\n"
            "      _jewel_group(session, device_id, referer, user_agent),\n"
            "      [_companion(session, QUICK_PROMOTION, page_surfaces, referer, user_agent)],\n",
            "      _jewel_group(session, device_id, referer, user_agent),\n"
            "      _badge_group(session, device_id, referer, user_agent),\n"
            "      [_companion(session, QUICK_PROMOTION, page_surfaces, referer, user_agent)],\n",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_a_profile_load_sends_the_recorded_burst_in_its_groups",
      "defect": "the profile page's two quick promotion calls go out as two groups",
      "edits": [
         (
            REQUESTS_PAGE_LOAD,
            "         _companion(session, QUICK_PROMOTION, page_surfaces, referer, user_agent),\n"
            "         _companion(session, QUICK_PROMOTION, login_surface, referer, user_agent),\n"
            "      ],\n",
            "         _companion(session, QUICK_PROMOTION, page_surfaces, referer, user_agent),\n"
            "      ],\n"
            "      [_companion(session, QUICK_PROMOTION, login_surface, referer, user_agent)],\n",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_a_home_load_sends_the_recorded_burst_in_its_groups",
      "defect": "a group is sent one request at a time",
      "edits": [
         (
            PAGE_LOAD,
            "      responses = await action.send_together(group)\n",
            "      responses = [await action.send(request) for request in group]\n",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_the_device_id_reader_takes_the_documents_client_id",
      "defect": "the device id pattern stops matching",
      "edits": [(PRELOAD, '\\["IGDMqttWebDeviceID"', '\\["IGDMqttDeviceID"')],
   },
   {
      "gate": f"{GATES}::test_a_document_without_a_device_id_reads_as_none",
      "defect": "a missing device id is made up",
      "edits": [
         (
            PRELOAD,
            "return match.group(1) if match is not None else None",
            "return match.group(1) if match is not None else "
            '"00000000-0000-4000-8000-000000000000"',
         )
      ],
   },
   {
      "gate": f"{GATES}::test_a_document_without_a_device_id_leaves_out_only_the_iris_queries",
      "defect": "a document without a device id drops the whole burst",
      "edits": [
         (
            FEED,
            "         if companions:\n",
            "         if companions and read_iris_device_id(response.text):\n",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_the_iris_queries_carry_the_documents_device_id",
      "defect": "the chat tabs jewel carries a device id the document never issued",
      "edits": [
         (
            REQUESTS_PAGE_LOAD,
            'iris = {"device_id_for_iris_subscription": device_id}\n   jewel = ',
            'iris = {"device_id_for_iris_subscription": "00000000-0000-4000-8000-000000000000"}\n'
            "   jewel = ",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_the_page_surfaces_name_the_profile_on_a_profile_page_only",
      "defect": "the profile page's quick promotion call loses its trigger context",
      "edits": [
         (
            REQUESTS_PAGE_LOAD,
            "_quick_promotion_variables(PAGE_SURFACES, profile_trigger)",
            "_quick_promotion_variables(PAGE_SURFACES, None)",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_every_companion_names_its_page_as_referer",
      "defect": "the profile page's companions claim the home page as referer",
      "edits": [
         (
            REQUESTS_PAGE_LOAD,
            "   referer = profile_page_url(username)\n   stories_tray_variables",
            '   referer = f"{ORIGIN}/"\n   stories_tray_variables',
         )
      ],
   },
   {
      "gate": f"{GATES}::test_a_rejected_companion_does_not_cost_the_feed_page",
      "defect": "a rejected companion fails the read",
      "edits": [
         (
            PAGE_LOAD,
            "   except (UpstreamRejected, SchemaChanged):\n",
            "   except SchemaChanged:\n",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_a_checkpoint_on_a_companion_is_raised",
      "defect": "companion answers are never screened",
      "edits": [
         (
            PAGE_LOAD,
            "      for response in responses:\n"
            "         raise_only_what_concerns_the_account(response)\n",
            "      del responses\n",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_the_burst_is_paced_as_part_of_the_document_action",
      "defect": "each companion group is paced as an action of its own",
      "edits": [
         (
            FEED,
            "            await send_companions(action, groups)\n\n      result =",
            "            pass\n\n"
            "      if companions:\n"
            "         for group in groups:\n"
            "            async with sender.action() as own_action:\n"
            "               await send_companions(own_action, [group])\n\n"
            "      result =",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_parity_sends_the_page_load_companions",
      "defect": "the parity default drops the companions",
      "edits": [
         (BEHAVIOR, "page_load_companions: bool = True", "page_load_companions: bool = False")
      ],
   },
   {
      "gate": f"{GATES}::test_the_client_sends_the_burst_under_the_default_behavior",
      "defect": "the client drops the setting on the way to the feed route",
      "edits": [
         (
            FEEDS_NAMESPACE,
            "            first_page=client._behavior.feed_first_page,\n"
            "            companions=client._behavior.page_load_companions,\n",
            "            first_page=client._behavior.feed_first_page,\n",
         )
      ],
   },
   {
      "gate": f"{GATES}::test_the_departure_drops_the_companions_and_nothing_else",
      "defect": "the profile route sends the companions whatever the behavior says",
      "edits": [
         (
            PROFILES_NAMESPACE,
            "            route=client._behavior.profile_route,\n"
            "            companions=client._behavior.page_load_companions,\n",
            "            route=client._behavior.profile_route,\n            companions=True,\n",
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
   log_path = LOG_DIR / f"mutation-page-load-{stamp}.json"
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
