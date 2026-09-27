"""Break E2 batch 3, the relationship lists, watch each gate go red, restore.

Same harness and same rule as ``verify_profile_tabs_gates.py``: one mutation per entry below,
only the gate that should catch it is run, every anchor must be found exactly once, and every
file is restored from an in-memory copy in a ``finally`` so an interrupted run cannot leave a
mutation behind.

The mutations cover the followers page's mapper and terminator, the relationship statuses and
how they land on a row, both requests, the action that sends them, the behavior setting, both
walks, the command, and the namespace parity gates for the new methods.

Run from ``engine/`` with ``uv run python scripts/verify_follow_lists_gates.py``. Writes its
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

PARSE = "dumpstagram/_private/web/parse/profiles.py"
REQUESTS = "dumpstagram/_private/web/requests/profiles.py"
CORE = "dumpstagram/_core/profiles.py"
NAMESPACE = "dumpstagram/namespaces/profiles.py"
COMMANDS = "dumpstagram/_cli/commands/profiles.py"
RENDER = "dumpstagram/_cli/render/profiles.py"
GATES = "tests/test_follow_lists.py"
PARITY_GATES = "tests/test_facade_parity.py"


def gate(name: str) -> str:
   return f"{GATES}::{name}"


def parity(name: str, qualified: str) -> str:
   return f"{PARITY_GATES}::{name}[{qualified}]"


PAGE_MAP = gate("test_a_followers_page_maps_every_account_in_order_with_the_upstreams_cursor")
SHORT_PAGE = gate("test_a_short_page_still_says_more_exist_and_only_has_more_ends_the_list")
NOT_OK = gate("test_a_followers_answer_whose_status_is_not_ok_is_refused")
FLAGS = gate("test_each_relationship_flag_is_read_from_its_own_key")
LANDS = gate("test_each_status_lands_on_the_account_it_names_and_an_unnamed_account_keeps_none")
PAGE_REQUEST = gate("test_a_followers_page_is_the_follow_lists_rest_read")
STATUSES_REQUEST = gate("test_the_relationship_read_is_the_follow_lists_form_post")
ACTION = gate("test_a_page_is_followed_in_its_action_by_the_statuses_of_the_accounts_on_it")
WITHOUT = gate("test_without_statuses_one_request_is_sent_and_no_token_is_fetched")
EMPTY = gate("test_an_empty_page_asks_for_no_statuses_and_a_username_is_refused_unsent")
ASYNC_WALK = gate("test_the_async_walk_asks_for_the_next_page_with_the_first_pages_next_max_id")
BLOCKING_WALK = gate(
   "test_the_blocking_walk_asks_for_the_next_page_with_the_first_pages_next_max_id"
)
SETTING = gate("test_the_behavior_setting_reaches_the_read_through_the_namespace")
DUMPSTA_WALK = gate(
   "test_dumpsta_followers_walks_on_the_pages_own_cursor_and_stops_on_its_terminator"
)
DUMPSTA_TEXT = gate("test_dumpsta_followers_text_ends_on_the_trailer_and_the_cursor_to_resume_from")
DUMPSTA_USERNAME = gate("test_dumpsta_followers_refuses_a_username")

MUTATIONS: list[dict[str, object]] = [
   {
      "gate": PAGE_MAP,
      "defect": "the page carries no cursor",
      "edits": [
         (
            PARSE,
            "has_next_page=has_more, end_cursor=next_max_id)",
            "has_next_page=has_more, end_cursor=None)",
         )
      ],
   },
   {
      "gate": PAGE_MAP,
      "defect": "the accounts come out in reverse",
      "edits": [
         (
            PARSE,
            "      for index, user in enumerate(users)\n   )\n",
            "      for index, user in enumerate(reversed(users))\n   )\n",
         )
      ],
   },
   {
      "gate": SHORT_PAGE,
      "defect": "a page shorter than twelve ends the list",
      "edits": [
         (
            PARSE,
            'has_more = _required_flag(payload, "has_more", _FOLLOWERS)',
            "has_more = len(users) == 12",
         )
      ],
   },
   {
      "gate": SHORT_PAGE,
      "defect": "a page without next_max_id is refused",
      "edits": [
         (
            PARSE,
            'carries_a_cursor = payload.get("next_max_id") is not None',
            "carries_a_cursor = True",
         )
      ],
   },
   {
      "gate": NOT_OK,
      "defect": "the REST status is not read",
      "edits": [(PARSE, '   _raise_unless_ok(payload, "followers page")\n', "")],
   },
   {
      "gate": FLAGS,
      "defect": "following is read from the outgoing request flag",
      "edits": [
         (
            PARSE,
            "   return ListFriendshipStatus(\n"
            '      following=_required_flag(raw, "following", status_path),',
            "   return ListFriendshipStatus(\n"
            '      following=_required_flag(raw, "outgoing_request", status_path),',
         )
      ],
   },
   {
      "gate": LANDS,
      "defect": "every account gets the first status the answer lists",
      "edits": [
         (
            PARSE,
            "statuses.get(account.id, account.friendship_status)",
            "next(iter(statuses.values()), None)",
         )
      ],
   },
   {
      "gate": PAGE_REQUEST,
      "defect": "another page size",
      "edits": [(REQUESTS, "FOLLOWERS_PAGE_SIZE = 12\n", "FOLLOWERS_PAGE_SIZE = 20\n")],
   },
   {
      "gate": PAGE_REQUEST,
      "defect": "the cursor is sent under another name",
      "edits": [(REQUESTS, 'params["max_id"] = after', 'params["after"] = after')],
   },
   {
      "gate": PAGE_REQUEST,
      "defect": "the web session header is left out",
      "edits": [(REQUESTS, '      "x-web-session-id": web_session_id,\n', "")],
   },
   {
      "gate": PAGE_REQUEST,
      "defect": "the referer is the bare origin without its slash",
      "edits": [(REQUESTS, '      "referer": f"{ORIGIN}/",\n', '      "referer": ORIGIN,\n')],
   },
   {
      "gate": STATUSES_REQUEST,
      "defect": "the ids are joined with spaces",
      "edits": [(REQUESTS, '",".join(account_ids)', '" ".join(account_ids)')],
   },
   {
      "gate": STATUSES_REQUEST,
      "defect": "the form leaves the browser's order",
      "edits": [
         (
            REQUESTS,
            '"jazoest": jazoest_for(token), "fb_dtsg": token}',
            '"fb_dtsg": token, "jazoest": jazoest_for(token)}',
         )
      ],
   },
   {
      "gate": STATUSES_REQUEST,
      "defect": "the revision header of a form POST is left out",
      "edits": [(REQUESTS, '      "x-instagram-ajax": revision,\n', "")],
   },
   {
      "gate": ACTION,
      "defect": "the statuses are asked for by username",
      "edits": [
         (
            CORE,
            "[account.id for account in page.items],",
            "[account.username for account in page.items],",
         )
      ],
   },
   {
      "gate": ACTION,
      "defect": "the statuses request draws its own web session id",
      "edits": [
         (
            CORE,
            "            web_session_id=web_session_id,\n",
            "            web_session_id=new_web_session_id(),\n",
         )
      ],
   },
   {
      "gate": ACTION,
      "defect": "the page is returned without the statuses it read",
      "edits": [
         (CORE, "      return attach_friendship_statuses(page, statuses)", "      return page")
      ],
   },
   {
      "gate": WITHOUT,
      "defect": "a token is fetched for a read that sends none",
      "edits": [
         (
            CORE,
            "needs_a_token = with_statuses and not session.fb_dtsg",
            "needs_a_token = not session.fb_dtsg",
         )
      ],
   },
   {
      "gate": WITHOUT,
      "defect": "the statuses are sent whatever the setting says",
      "edits": [
         (
            CORE,
            "asks_for_statuses = with_statuses and bool(page.items)",
            "asks_for_statuses = bool(page.items)",
         )
      ],
   },
   {
      "gate": EMPTY,
      "defect": "the statuses are asked for an empty page",
      "edits": [
         (
            CORE,
            "asks_for_statuses = with_statuses and bool(page.items)",
            "asks_for_statuses = with_statuses",
         )
      ],
   },
   {
      "gate": EMPTY,
      "defect": "a username reaches the path",
      "edits": [
         (
            CORE,
            "   refuse_what_is_not_a_user_id(user_id)\n\n"
            "   async def attempt() -> Page[ProfileSummary]:",
            "   async def attempt() -> Page[ProfileSummary]:",
         )
      ],
   },
   {
      "gate": ASYNC_WALK,
      "defect": "the async walk asks for the first page again",
      "edits": [
         (
            NAMESPACE,
            "self.followers(user_id, after=next_max_id)",
            "self.followers(user_id, after=None)",
         )
      ],
   },
   {
      "gate": BLOCKING_WALK,
      "defect": "the blocking walk asks for the first page again",
      "edits": [
         (
            NAMESPACE,
            "client._impl.profiles.followers(user_id, after=next_max_id),",
            "client._impl.profiles.followers(user_id, after=None),",
         )
      ],
   },
   {
      "gate": SETTING,
      "defect": "the namespace ignores the behavior setting",
      "edits": [
         (
            NAMESPACE,
            "with_statuses=client._behavior.follow_list_statuses,",
            "with_statuses=True,",
         )
      ],
   },
   {
      "gate": DUMPSTA_WALK,
      "defect": "the command passes its first cursor again",
      "edits": [
         (
            COMMANDS,
            "      next_max_id = page.end_cursor\n",
            "      next_max_id = arguments.after\n",
         )
      ],
   },
   {
      "gate": DUMPSTA_WALK,
      "defect": "the command reads past the last page",
      "edits": [(COMMANDS, "      if reached_the_last_page:\n         break\n", "")],
   },
   {
      "gate": DUMPSTA_WALK,
      "defect": "the account count counts pages",
      "edits": [
         (
            RENDER,
            '"account_count": sum(len(page.items) for page in pages),',
            '"account_count": len(pages),',
         )
      ],
   },
   {
      "gate": DUMPSTA_TEXT,
      "defect": "the text form prints no cursor to resume from",
      "edits": [
         (RENDER, '   if described["end_cursor"]:', '   if described["end_cursor"] is None:')
      ],
   },
   {
      "gate": DUMPSTA_USERNAME,
      "defect": "the command takes a username for the id",
      "edits": [
         (
            COMMANDS,
            '   followers.add_argument(\n      "user_id", metavar="USER_ID", type=account_id,',
            '   followers.add_argument(\n      "user_id", metavar="USER_ID", type=str,',
         )
      ],
   },
   {
      "gate": parity(
         "test_a_namespace_method_reaches_the_core_capability_the_table_names",
         "profiles.followers",
      ),
      "defect": "followers reaches the tray's core function",
      "edits": [(NAMESPACE, "         read_followers_page(\n", "         read_highlight_tray(\n")],
   },
   {
      "gate": parity(
         "test_a_blocking_namespace_method_forwards_every_argument_on_the_loop_thread",
         "profiles.followers",
      ),
      "defect": "the blocking followers drops its cursor",
      "edits": [
         (
            NAMESPACE,
            "         self._client._impl.profiles.followers(user_id, after=after),\n",
            "         self._client._impl.profiles.followers(user_id, after=None),\n",
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
   log_path = LOG_DIR / f"mutation-follow-lists-{stamp}.json"
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
