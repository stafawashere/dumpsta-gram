"""Break the partial answer rule and E2 batch 2, the profile tabs, watch each gate go red,
restore.

Same harness and same rule as ``verify_direct_read_gates.py``: one mutation per entry below, only
the gate that should catch it is run, every anchor must be found exactly once, and every file is
restored from an in-memory copy in a ``finally`` so an interrupted run cannot leave a mutation
behind.

The mutations cover the classifier's partial answer rule (W52), the grid's mapper, requests and
walks, the highlights tray, the two suggested lists, the four commands, the namespace parity
gates for the new methods, and the canary's new replay steps.

Run from ``engine/`` with ``uv run python scripts/verify_profile_tabs_gates.py``. Writes its
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

CLASSIFY = "dumpstagram/_private/web/classify.py"
PARSE = "dumpstagram/_private/web/parse/profiles.py"
MEDIA_PARSE = "dumpstagram/_private/web/parse/media.py"
REQUESTS = "dumpstagram/_private/web/requests/profiles.py"
CORE = "dumpstagram/_core/profiles.py"
NAMESPACE = "dumpstagram/namespaces/profiles.py"
COMMANDS = "dumpstagram/_cli/commands/profiles.py"
RENDER = "dumpstagram/_cli/render/profiles.py"
CANARY = "dumpstagram/_private/web/canary.py"
GATES = "tests/test_profile_tabs.py"
CLASSIFY_GATES = "tests/test_classify.py"
PARITY_GATES = "tests/test_facade_parity.py"
DOCTOR_GATES = "tests/test_doctor.py"


def gate(name: str) -> str:
   return f"{GATES}::{name}"


def classify_gate(name: str) -> str:
   return f"{CLASSIFY_GATES}::{name}"


def parity(name: str, qualified: str) -> str:
   return f"{PARITY_GATES}::{name}[{qualified}]"


def doctor(name: str) -> str:
   return f"{DOCTOR_GATES}::{name}"


PARTIAL_PASSES = classify_gate("test_field_errors_beside_a_root_that_answered_are_a_partial_answer")
NOT_A_FIELD_ERROR = classify_gate(
   "test_an_error_that_is_not_a_field_error_beside_an_answer_is_still_refused"
)
GRID_ORDER = gate("test_a_grid_page_maps_every_post_in_the_upstream_order_with_its_own_terminator")
GRID_UNSEEN = gate("test_a_grid_post_carries_a_null_is_seen_and_reads_as_unseen")
LATER_PAGE = gate("test_a_later_grid_page_is_the_tab_connection_query_replayed_live")
HIGHLIGHT = gate("test_a_highlight_is_read_from_its_own_keys_and_the_tray_says_when_it_is_partial")
FLAGS = gate("test_a_rows_friendship_flags_are_each_read_from_their_own_key")
REASON = gate("test_a_suggestion_carries_the_items_reason_and_no_privacy_it_was_not_sent")
BOTH_LISTS = gate("test_both_suggested_lists_send_the_variables_replayed_live")
DUMPSTA_POSTS = gate("test_dumpsta_posts_walks_on_the_pages_own_cursor_and_stops_on_its_terminator")
FOR_YOU = gate("test_dumpsta_suggested_for_you_prints_each_accounts_reason")
GRID_NEXT_PAGE_REPLAY = doctor(
   "test_the_grid_next_page_is_replayed_on_the_first_pages_cursor_and_skipped_without_one"
)

MUTATIONS: list[dict[str, object]] = [
   {
      "gate": PARTIAL_PASSES,
      "defect": "any errors array is refused, as before W52",
      "edits": [
         (
            CLASSIFY,
            'refuses = bool(errors) and not _is_a_partial_answer(errors, parsed.get("data"))',
            "refuses = bool(errors)",
         )
      ],
   },
   {
      "gate": NOT_A_FIELD_ERROR,
      "defect": "a path of one element, the root itself, counts as a field error",
      "edits": [
         (
            CLASSIFY,
            "names_a_field = len(path) >= 2",
            "names_a_field = len(path) >= 1",
         )
      ],
   },
   {
      "gate": NOT_A_FIELD_ERROR,
      "defect": "one field error excuses a pathless error beside it",
      "edits": [
         (
            CLASSIFY,
            "return all(_is_a_field_error(error, data) for error in errors)",
            "return any(_is_a_field_error(error, data) for error in errors)",
         )
      ],
   },
   {
      "gate": classify_gate("test_a_field_error_under_a_null_root_is_refused"),
      "defect": "a root present but null counts as one that answered",
      "edits": [(CLASSIFY, "return data.get(root) is not None", "return root in data")],
   },
   {
      "gate": classify_gate("test_a_partial_answer_quoting_the_challenge_path_is_not_a_checkpoint"),
      "defect": "the body of a partial answer is scanned for a checkpoint",
      "edits": [
         (
            CLASSIFY,
            "   envelope_code = _envelope_code(parsed)\n",
            "   envelope_code = _envelope_code(parsed)\n"
            '   if parsed.get("errors"):\n'
            "      _raise_if_the_body_says_checkpoint(body)\n",
         )
      ],
   },
   {
      "gate": classify_gate("test_a_preloaded_result_follows_the_same_partial_answer_rule"),
      "defect": "the preloaded reader refuses any errors array",
      "edits": [
         (
            CLASSIFY,
            "   envelope_code = _envelope_code(result)\n",
            '   envelope_code = "errors" if result.get("errors") else _envelope_code(result)\n',
         )
      ],
   },
   {
      "gate": GRID_UNSEEN,
      "defect": "the grid mapper reads is_seen as the home timeline does and refuses the grid",
      "edits": [(PARSE, "null_is_unseen=True,", "null_is_unseen=False,")],
   },
   {
      "gate": GRID_UNSEEN,
      "defect": "a null is_seen reads as seen",
      "edits": [(MEDIA_PARSE, "return seen is True", "return seen is not False")],
   },
   {
      "gate": gate("test_the_home_timeline_still_refuses_a_null_is_seen"),
      "defect": "the home timeline reads a null is_seen too",
      "edits": [
         (
            MEDIA_PARSE,
            "def parse_post(node: Any, path: str, *, null_is_unseen: bool = False) -> Post:",
            "def parse_post(node: Any, path: str, *, null_is_unseen: bool = True) -> Post:",
         )
      ],
   },
   {
      "gate": gate("test_a_grid_is_seen_that_is_neither_null_nor_a_boolean_is_refused"),
      "defect": "anything on a grid's is_seen reads as unseen",
      "edits": [
         (
            MEDIA_PARSE,
            'seen = _optional_flag(node, "is_seen", path)',
            'seen = node.get("is_seen")',
         )
      ],
   },
   {
      "gate": GRID_ORDER,
      "defect": "the grid's cursor is read from start_cursor",
      "edits": [
         (
            PARSE,
            'end_cursor = _optional_string(page_info, "end_cursor", page_info_path)',
            'end_cursor = _optional_string(page_info, "start_cursor", page_info_path)',
         )
      ],
   },
   {
      "gate": gate("test_the_owners_grid_answered_beside_field_errors_is_read_whole"),
      "defect": "the owner's grid is refused for its field errors, as before W52",
      "edits": [
         (
            CLASSIFY,
            'refuses = bool(errors) and not _is_a_partial_answer(errors, parsed.get("data"))',
            "refuses = bool(errors)",
         )
      ],
   },
   {
      "gate": gate("test_the_first_grid_page_is_the_profile_pages_own_timeline_query"),
      "defect": "the first grid page asks for the resolution's one post",
      "edits": [
         (
            REQUESTS,
            "      variables = _profile_posts_variables(username, PROFILE_PAGE_POSTS)",
            "      variables = _profile_posts_variables(username, RESOLUTION_PAGE_SIZE)",
         )
      ],
   },
   {
      "gate": LATER_PAGE,
      "defect": "a later grid page sends the first page's query",
      "edits": [(REQUESTS, "      query = PROFILE_POSTS_NEXT_PAGE", "      query = PROFILE_POSTS")],
   },
   {
      "gate": LATER_PAGE,
      "defect": "a later grid page drops its cursor",
      "edits": [(REQUESTS, '"after": after,', '"after": None,')],
   },
   {
      "gate": gate("test_a_name_that_cannot_be_a_username_is_refused_before_anything_is_sent"),
      "defect": "a username goes into the referer's path unchecked",
      "edits": [
         (
            CORE,
            "   profile_page_url(username)\n\n   async def attempt() -> Page[Post]:",
            "   async def attempt() -> Page[Post]:",
         )
      ],
   },
   {
      "gate": gate(
         "test_the_async_grid_walk_crosses_to_the_next_page_query_on_the_first_pages_cursor"
      ),
      "defect": "the async grid walk asks for the first page again",
      "edits": [
         (
            NAMESPACE,
            "lambda cursor: self.posts(username, after=cursor)",
            "lambda cursor: self.posts(username, after=None)",
         )
      ],
   },
   {
      "gate": gate("test_the_blocking_grid_walk_crosses_to_the_next_page_query"),
      "defect": "the blocking grid walk asks for the first page again",
      "edits": [
         (
            NAMESPACE,
            "            client._impl.profiles.posts(username, after=cursor),",
            "            client._impl.profiles.posts(username, after=None),",
         )
      ],
   },
   {
      "gate": HIGHLIGHT,
      "defect": "a highlight's title is read from its id",
      "edits": [
         (
            PARSE,
            'title=_required_string(node, "title", path),',
            'title=_required_string(node, "id", path),',
         )
      ],
   },
   {
      "gate": HIGHLIGHT,
      "defect": "the tray never says it is partial",
      "edits": [
         (
            PARSE,
            "   has_more, _ = _page_info(connection, connection_path)",
            "   has_more = False",
         )
      ],
   },
   {
      "gate": gate("test_the_tray_is_the_profile_pages_query_keyed_on_the_account_id"),
      "defect": "the tray is sent keyed on id rather than user_id",
      "edits": [(REQUESTS, '{"user_id": user_id},', '{"id": user_id},')],
   },
   {
      "gate": gate("test_the_tray_is_the_profile_pages_query_keyed_on_the_account_id"),
      "defect": "a username reaches the tray query",
      "edits": [
         (
            CORE,
            "   refuse_what_is_not_a_user_id(user_id)\n\n   async def attempt() -> HighlightTray:",
            "   async def attempt() -> HighlightTray:",
         )
      ],
   },
   {
      "gate": FLAGS,
      "defect": "following is read from followed_by",
      "edits": [
         (
            PARSE,
            "   return ListFriendshipStatus(\n"
            '      following=_required_flag(raw, "following", status_path),',
            "   return ListFriendshipStatus(\n"
            '      following=_required_flag(raw, "followed_by", status_path),',
         )
      ],
   },
   {
      "gate": FLAGS,
      "defect": "the feed favorite and restricted flags are swapped",
      "edits": [
         (
            PARSE,
            'is_feed_favorite=_required_flag(raw, "is_feed_favorite", status_path),\n'
            '      is_restricted=_required_flag(raw, "is_restricted", status_path),',
            'is_feed_favorite=_required_flag(raw, "is_restricted", status_path),\n'
            '      is_restricted=_required_flag(raw, "is_feed_favorite", status_path),',
         )
      ],
   },
   {
      "gate": gate(
         "test_a_row_without_the_two_list_only_flags_reads_them_as_none_and_a_required_one_raises"
      ),
      "defect": "followed_by is required of every list",
      "edits": [
         (
            PARSE,
            'followed_by=_flag_if_carried(raw, "followed_by", status_path),',
            'followed_by=_required_flag(raw, "followed_by", status_path),',
         )
      ],
   },
   {
      "gate": REASON,
      "defect": "a suggestion's reason is read from another key of the item",
      "edits": [
         (
            PARSE,
            'reason=_required_string(item, "social_context", item_path),',
            'reason=_required_string(item, "uuid", item_path),',
         )
      ],
   },
   {
      "gate": REASON,
      "defect": "a row without is_private reads as public",
      "edits": [
         (
            PARSE,
            'is_private=_flag_if_carried(row, "is_private", path),',
            'is_private=bool(row.get("is_private")),',
         )
      ],
   },
   {
      "gate": gate("test_every_suggested_row_is_read_by_its_pk_with_its_privacy_and_picture"),
      "defect": "the high resolution picture is dropped where the row carries it",
      "edits": [
         (
            PARSE,
            '   carries_hd_picture = "hd_profile_pic_url_info" in row\n',
            "   carries_hd_picture = False\n",
         )
      ],
   },
   {
      "gate": BOTH_LISTS,
      "defect": "the suggestions beside a profile are asked for with another module",
      "edits": [
         (
            REQUESTS,
            '{"module": "profile", "target_id": user_id},',
            '{"module": "discover_people", "target_id": user_id},',
         )
      ],
   },
   {
      "gate": BOTH_LISTS,
      "defect": "the suggested accounts list asks for another page size",
      "edits": [(REQUESTS, "SUGGESTED_ACCOUNTS_SHOWN = 5\n", "SUGGESTED_ACCOUNTS_SHOWN = 10\n")],
   },
   {
      "gate": BOTH_LISTS,
      "defect": "a username reaches the suggestions beside a profile",
      "edits": [
         (
            CORE,
            "   refuse_what_is_not_a_user_id(user_id)\n\n"
            "   async def attempt() -> tuple[ProfileSummary, ...]:",
            "   async def attempt() -> tuple[ProfileSummary, ...]:",
         )
      ],
   },
   {
      "gate": DUMPSTA_POSTS,
      "defect": "dumpsta posts passes its first cursor again",
      "edits": [(COMMANDS, "      cursor = page.end_cursor\n", "      cursor = arguments.after\n")],
   },
   {
      "gate": DUMPSTA_POSTS,
      "defect": "dumpsta posts reads past a last page",
      "edits": [
         (
            COMMANDS,
            "      if not page.has_next_page:\n         break\n\n      cursor = page.end_cursor",
            "      cursor = page.end_cursor",
         )
      ],
   },
   {
      "gate": gate("test_dumpsta_highlights_says_when_the_tray_is_partial"),
      "defect": "dumpsta highlights prints a partial tray as whole",
      "edits": [
         (
            RENDER,
            'more = "  more_available: True" if tray.has_more else ""',
            'more = ""',
         )
      ],
   },
   {
      "gate": FOR_YOU,
      "defect": "the text form drops each account's reason",
      "edits": [
         (
            RENDER,
            'f"{_summary_line(suggestion.account)}\\n   {suggestion.reason}"',
            'f"{_summary_line(suggestion.account)}"',
         )
      ],
   },
   {
      "gate": FOR_YOU,
      "defect": "the JSON form drops each account's reason",
      "edits": [(RENDER, '"reason": suggestion.reason}', '"reason": None}')],
   },
   {
      "gate": gate("test_dumpsta_suggested_and_highlights_refuse_a_username"),
      "defect": "dumpsta suggested takes a username",
      "edits": [
         (
            COMMANDS,
            '   suggested.add_argument(\n      "user_id", metavar="USER_ID", type=account_id,',
            '   suggested.add_argument(\n      "user_id", metavar="USER_ID", type=str,',
         )
      ],
   },
   {
      "gate": parity(
         "test_a_namespace_method_reaches_the_core_capability_the_table_names",
         "profiles.highlights",
      ),
      "defect": "highlights reaches the suggestions' core function",
      "edits": [
         (NAMESPACE, "         read_highlight_tray(\n", "         read_suggested_beside_profile(\n")
      ],
   },
   {
      "gate": parity(
         "test_a_blocking_namespace_method_forwards_every_argument_on_the_loop_thread",
         "profiles.posts",
      ),
      "defect": "the blocking posts drops its cursor",
      "edits": [
         (
            NAMESPACE,
            "         self._client._impl.profiles.posts(username, after=after),\n",
            "         self._client._impl.profiles.posts(username, after=None),\n",
         )
      ],
   },
   {
      "gate": GRID_NEXT_PAGE_REPLAY,
      "defect": "the canary sends the grid's next page with no cursor learned",
      "edits": [
         (
            CANARY,
            '      query=PROFILE_POSTS_NEXT_PAGE,\n      requires="posts_cursor",',
            '      query=PROFILE_POSTS_NEXT_PAGE,\n      requires="username",',
         )
      ],
   },
   {
      "gate": GRID_NEXT_PAGE_REPLAY,
      "defect": "the canary's grid step learns no cursor",
      "edits": [
         (
            CANARY,
            "      read=_learn_grid_cursor,",
            "      read=_mapped_by(parse_user_id),",
         )
      ],
   },
   {
      "gate": GRID_NEXT_PAGE_REPLAY,
      "defect": "the canary keeps a cursor the first page did not hand out",
      "edits": [
         (
            CANARY,
            "      arguments.posts_cursor = page.end_cursor",
            '      arguments.posts_cursor = "a-cursor"',
         )
      ],
   },
   {
      "gate": doctor("test_every_read_replays_ok_when_each_answer_is_one_its_mapper_accepts"),
      "defect": "the canary reads the tray with another list's mapper",
      "edits": [
         (
            CANARY,
            "   tray = parse_highlight_tray(payload)",
            "   tray = parse_suggested_accounts(payload)",
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
   log_path = LOG_DIR / f"mutation-profile-tabs-{stamp}.json"
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
