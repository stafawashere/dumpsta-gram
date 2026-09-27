"""Break E2 batch 6, the viewer's own account, watch each gate go red, restore.

Same harness and same rule as ``verify_follow_lists_gates.py``: one mutation per entry below,
only the gate that should catch it is run, every anchor must be found exactly once, and every
file is restored from an in-memory copy in a ``finally`` so an interrupted run cannot leave a
mutation behind.

The mutations cover the follow requests' row and more flag, both requests, the activity feed's
items, links, optional fields, follow button, counters, sections and lists, the read that must
not mark the feed seen, both namespaces, both commands, and the namespace parity gates for the
new methods.

Run from ``engine/`` with ``uv run python scripts/verify_account_gates.py``. Writes its result
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

PARSE = "dumpstagram/_private/web/parse/account.py"
REQUESTS = "dumpstagram/_private/web/requests/account.py"
CORE = "dumpstagram/_core/account.py"
MODELS = "dumpstagram/models/account.py"
NAMESPACE = "dumpstagram/namespaces/account.py"
RENDER = "dumpstagram/_cli/render/account.py"
GATES = "tests/test_account.py"
PARITY_GATES = "tests/test_facade_parity.py"


def gate(name: str) -> str:
   return f"{GATES}::{name}"


def parity(name: str, qualified: str) -> str:
   return f"{PARITY_GATES}::{name}[{qualified}]"


ROW = gate("test_a_follow_request_row_reads_its_id_from_the_string_key_and_more_from_next_max_id")
NOT_OK = gate("test_an_account_answer_whose_status_is_not_ok_is_refused")
REQUESTS_GET = gate("test_the_follow_requests_read_is_the_inbox_loads_get")
ACTIVITY_POST = gate("test_the_activity_read_is_the_inbox_loads_form_post_with_only_the_page_token")
ITEMS = gate("test_every_activity_item_maps_in_order_with_its_kind_time_and_text")
LINKS = gate("test_each_link_names_the_account_its_span_of_the_text_shows")
OPTIONAL = gate("test_what_an_item_carries_only_sometimes_is_none_or_empty_where_it_is_absent")
FOLLOW_BUTTON = gate("test_a_follow_button_carries_its_account_and_the_viewers_relationship_to_it")
COUNTERS = gate("test_each_counter_is_read_from_its_own_key")
SECTIONS = gate("test_the_feed_carries_its_sections_last_page_flag_and_last_check")
LISTS = gate("test_new_and_priority_items_land_in_their_own_lists_and_items_joins_them_in_order")
NO_BOOTSTRAP = gate("test_the_follow_requests_read_is_one_get_and_spends_no_bootstrap")
NO_SEEN = gate("test_the_activity_read_is_one_post_and_never_marks_the_feed_seen")
ASYNC_NAMESPACE = gate("test_the_async_namespace_sends_each_read_once_and_nothing_else")
BLOCKING_NAMESPACE = gate("test_the_blocking_namespace_sends_each_read_once_and_nothing_else")
DUMPSTA_REQUESTS = gate("test_dumpsta_follow_requests_prints_every_account_and_whether_more_exist")
DUMPSTA_ACTIVITY = gate(
   "test_dumpsta_activity_prints_every_item_with_the_counts_and_the_last_page_flag"
)
REACHES_CORE = "test_a_namespace_method_reaches_the_core_capability_the_table_names"

MUTATIONS: list[dict[str, object]] = [
   {
      "gate": ROW,
      "defect": "the row's id is read from the numeric pk",
      "edits": [(PARSE, ', id_key="id")', ")")],
   },
   {
      "gate": ROW,
      "defect": "more is read from big_list",
      "edits": [
         (
            PARSE,
            'has_more=payload.get("next_max_id") is not None',
            'has_more=payload.get("big_list") is True',
         )
      ],
   },
   {
      "gate": NOT_OK,
      "defect": "the follow requests' REST status is not read",
      "edits": [(PARSE, '   _raise_unless_ok(payload, "follow requests")\n', "")],
   },
   {
      "gate": NOT_OK,
      "defect": "the activity feed's REST status is not read",
      "edits": [(PARSE, '   _raise_unless_ok(payload, "activity feed")\n', "")],
   },
   {
      "gate": REQUESTS_GET,
      "defect": "the reads carry the site root as referer",
      "edits": [
         (REQUESTS, '      "referer": ACCOUNT_READ_REFERER,', '      "referer": f"{ORIGIN}/",')
      ],
   },
   {
      "gate": REQUESTS_GET,
      "defect": "the GET carries a page size",
      "edits": [
         (
            REQUESTS,
            "      url=_FOLLOW_REQUESTS_URL,\n"
            "      headers=_account_read_headers(session, web_session_id, user_agent),\n"
            "      params={},",
            "      url=_FOLLOW_REQUESTS_URL,\n"
            "      headers=_account_read_headers(session, web_session_id, user_agent),\n"
            '      params={"count": "12"},',
         )
      ],
   },
   {
      "gate": ACTIVITY_POST,
      "defect": "the form's two fields are sent in the other order",
      "edits": [
         (
            REQUESTS,
            'fields = {"fb_dtsg": token, "jazoest": jazoest_for(token)}',
            'fields = {"jazoest": jazoest_for(token), "fb_dtsg": token}',
         )
      ],
   },
   {
      "gate": ACTIVITY_POST,
      "defect": "the POST drops the revision header",
      "edits": [(REQUESTS, '      "x-instagram-ajax": revision,\n', "")],
   },
   {
      "gate": ACTIVITY_POST,
      "defect": "the POST is built without a token",
      "edits": [
         (
            REQUESTS,
            "   if not token:\n"
            "      raise AuthenticationFailed(\n"
            '         "session has no fb_dtsg, so it has not been bootstrapped since it was '
            'loaded"\n'
            "      )\n"
            "\n"
            "   spin = session.spin\n",
            "   if token is None and token:\n"
            "      raise AuthenticationFailed(\n"
            '         "session has no fb_dtsg, so it has not been bootstrapped since it was '
            'loaded"\n'
            "      )\n"
            "\n"
            "   spin = session.spin\n",
         )
      ],
   },
   {
      "gate": ITEMS,
      "defect": "the kind is read from the aggregation type",
      "edits": [
         (
            PARSE,
            'kind=_required_string(raw, "notif_name", path),',
            'kind=_required_string(args, "aggregation_type", f"{path}.args"),',
         )
      ],
   },
   {
      "gate": ITEMS,
      "defect": "the line is read from its markup form",
      "edits": [
         (
            PARSE,
            'text=_required_string(args, "text", args_path),',
            'text=_required_string(args, "rich_text", args_path),',
         )
      ],
   },
   {
      "gate": ITEMS,
      "defect": "the items come out in reverse",
      "edits": [
         (
            PARSE,
            "for index, raw in enumerate(_list_of(payload, key, _FEED))",
            "for index, raw in enumerate(reversed(_list_of(payload, key, _FEED)))",
         )
      ],
   },
   {
      "gate": LINKS,
      "defect": "a link's start and end are swapped",
      "edits": [
         (
            PARSE,
            'start=_required_integer(raw, "start", path),\n'
            '      end=_required_integer(raw, "end", path),',
            'start=_required_integer(raw, "end", path),\n'
            '      end=_required_integer(raw, "start", path),',
         )
      ],
   },
   {
      "gate": OPTIONAL,
      "defect": "the second account is read from the first",
      "edits": [
         (
            PARSE,
            'second_account_id=_string_if_carried(args, "second_profile_id", args_path),',
            'second_account_id=_string_if_carried(args, "profile_id", args_path),',
         )
      ],
   },
   {
      "gate": OPTIONAL,
      "defect": "a thumbnail's image is read from its shortcode",
      "edits": [
         (
            PARSE,
            'image_url=_required_string(raw, "image", path),',
            'image_url=_required_string(raw, "shortcode", path),',
         )
      ],
   },
   {
      "gate": FOLLOW_BUTTON,
      "defect": "the follow button is dropped",
      "edits": [
         (PARSE, "   if carries_a_follow_button:\n", "   if carries_a_follow_button and False:\n")
      ],
   },
   {
      "gate": COUNTERS,
      "defect": "every counter is read from likes",
      "edits": [
         (
            PARSE,
            "**{name: _required_integer(counts, name, counts_path) for name in _COUNTERS}",
            '**{name: _required_integer(counts, "likes", counts_path) for name in _COUNTERS}',
         )
      ],
   },
   {
      "gate": SECTIONS,
      "defect": "the last page flag is a constant",
      "edits": [
         (
            PARSE,
            'is_last_page=_required_flag(payload, "is_last_page", _FEED),',
            "is_last_page=True,",
         )
      ],
   },
   {
      "gate": SECTIONS,
      "defect": "titles and indices of unequal length are accepted",
      "edits": [
         (PARSE, "   lengths_match = len(titles) == len(indices)\n", "   lengths_match = True\n")
      ],
   },
   {
      "gate": LISTS,
      "defect": "the new list is read from the priority list",
      "edits": [
         (
            PARSE,
            'new_items=_parse_items(payload, "new_stories"),',
            'new_items=_parse_items(payload, "priority_stories"),',
         )
      ],
   },
   {
      "gate": LISTS,
      "defect": "items joins new before priority",
      "edits": [
         (
            MODELS,
            "return self.priority_items + self.new_items + self.earlier_items",
            "return self.new_items + self.priority_items + self.earlier_items",
         )
      ],
   },
   {
      "gate": NO_BOOTSTRAP,
      "defect": "the follow requests read spends a bootstrap",
      "edits": [
         (
            CORE,
            "   async def attempt() -> FollowRequests:\n",
            "   async def attempt() -> FollowRequests:\n"
            "      await bootstrap(sender, session, user_agent=user_agent)\n",
         )
      ],
   },
   {
      "gate": NO_SEEN,
      "defect": "the activity read sends a second request after it",
      "edits": [
         (
            CORE,
            "      return parse_activity_feed(classify(response))\n",
            "      await sender.send(request)\n"
            "      return parse_activity_feed(classify(response))\n",
         )
      ],
   },
   {
      "gate": ASYNC_NAMESPACE,
      "defect": "follow_requests reaches the activity read",
      "edits": [(NAMESPACE, "         read_follow_requests(\n", "         read_activity_feed(\n")],
   },
   {
      "gate": BLOCKING_NAMESPACE,
      "defect": "the blocking activity reads the follow requests",
      "edits": [
         (
            NAMESPACE,
            "         self._client._impl.account.activity(),\n",
            "         self._client._impl.account.follow_requests(),\n",
         )
      ],
   },
   {
      "gate": DUMPSTA_REQUESTS,
      "defect": "the JSON inverts the more flag",
      "edits": [
         (
            RENDER,
            '"more_available": requests.has_more,',
            '"more_available": not requests.has_more,',
         )
      ],
   },
   {
      "gate": DUMPSTA_REQUESTS,
      "defect": "the text form leaves out the first account",
      "edits": [
         (
            RENDER,
            "      for account in requests.accounts\n",
            "      for account in requests.accounts[1:]\n",
         )
      ],
   },
   {
      "gate": DUMPSTA_ACTIVITY,
      "defect": "the earlier count counts the new items",
      "edits": [
         (
            RENDER,
            '"earlier_count": len(feed.earlier_items),',
            '"earlier_count": len(feed.new_items),',
         )
      ],
   },
   {
      "gate": DUMPSTA_ACTIVITY,
      "defect": "the text form leaves out the first item",
      "edits": [(RENDER, " for item in feed.items]", " for item in feed.items[1:]]")],
   },
   {
      "gate": parity(REACHES_CORE, "account.activity"),
      "defect": "activity reaches the follow requests' core function",
      "edits": [(NAMESPACE, "         read_activity_feed(\n", "         read_follow_requests(\n")],
   },
   {
      "gate": parity(REACHES_CORE, "account.follow_requests"),
      "defect": "follow_requests reaches the activity feed's core function",
      "edits": [(NAMESPACE, "         read_follow_requests(\n", "         read_activity_feed(\n")],
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
   log_path = LOG_DIR / f"mutation-account-{stamp}.json"
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
