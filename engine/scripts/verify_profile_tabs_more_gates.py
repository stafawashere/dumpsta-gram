"""Break E2 batch 11a, the reels and tagged tabs and the following list, watch each gate go red,
restore.

Same harness and same rule as ``verify_follow_lists_gates.py``: one mutation per entry below,
only the gate that should catch it is run, every anchor must be found exactly once, and every
file is restored from an in-memory copy in a ``finally`` so an interrupted run cannot leave a
mutation behind.

The mutations cover both tab mappers and their flags, both tab queries and their registry
entries, the following page's mapper and request, the action that sends its statuses, the
setting, both walks, the three commands, the canary's two steps and the namespace parity gates.

Run from ``engine/`` with ``uv run python scripts/verify_profile_tabs_more_gates.py``. Writes its
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

DOCUMENTS = "dumpstagram/_private/web/documents/profiles.py"
PARSE = "dumpstagram/_private/web/parse/profiles.py"
REQUESTS = "dumpstagram/_private/web/requests/profiles.py"
CANARY = "dumpstagram/_private/web/canary.py"
CORE = "dumpstagram/_core/profiles.py"
NAMESPACE = "dumpstagram/namespaces/profiles.py"
COMMANDS = "dumpstagram/_cli/commands/profiles.py"
RENDER = "dumpstagram/_cli/render/profile_tabs.py"
GATES = "tests/test_profile_tabs_more.py"
DOCTOR_GATES = "tests/test_doctor.py"
PARITY_GATES = "tests/test_facade_parity.py"


def gate(name: str) -> str:
   return f"{GATES}::{name}"


def parity(name: str, qualified: str) -> str:
   return f"{PARITY_GATES}::{name}[{qualified}]"


REELS_MAP = gate("test_a_reels_tab_maps_each_reel_from_its_media_with_the_tabs_own_flag")
PLAY_COUNT = gate("test_a_reel_whose_play_count_is_null_maps_with_none")
TAGGED_MAP = gate("test_a_tagged_tab_maps_each_post_with_the_account_that_posted_it")
REELS_REQUEST = gate("test_the_reels_tab_is_the_browsers_query_with_the_account_id_twice")
TAGGED_REQUEST = gate("test_the_tagged_tab_is_the_browsers_query_keyed_on_the_account_id")
FOLLOWING_MAP = gate(
   "test_a_following_page_maps_every_account_with_the_numeric_offset_as_its_cursor"
)
FOLLOWING_REQUEST = gate("test_a_following_page_is_the_lists_rest_read_without_a_search_surface")
FOLLOWING_ACTION = gate(
   "test_a_following_page_is_followed_in_its_action_by_the_statuses_of_its_accounts"
)
FOLLOWING_WITHOUT = gate(
   "test_a_following_page_without_statuses_is_one_request_and_a_username_is_refused"
)
ASYNC_WALK = gate("test_the_async_walk_asks_for_the_next_page_at_the_first_pages_offset")
BLOCKING_WALK = gate("test_the_blocking_walk_asks_for_the_next_page_at_the_first_pages_offset")
DEFAULT_STATUSES = gate("test_following_sends_the_statuses_under_the_default_behavior")
DUMPSTA_FOLLOWING = gate(
   "test_dumpsta_following_reads_the_following_list_and_stops_on_its_terminator"
)
DUMPSTA_TABS = gate("test_dumpsta_profile_reels_and_tagged_print_the_tab_and_its_flag")
DOCTOR_TABS = f"{DOCTOR_GATES}::test_the_profile_tab_steps_read_the_viewers_own_account"


def refuses_username(command: str) -> str:
   return gate(f"test_each_new_command_refuses_a_username[{command}]")


MUTATIONS: list[dict[str, object]] = [
   {
      "gate": REELS_MAP,
      "defect": "the play count is read from the null view count",
      "edits": [
         (
            PARSE,
            'play_count=_optional_integer(media, "play_count", media_path),',
            'play_count=_optional_integer(media, "view_count", media_path),',
         )
      ],
   },
   {
      "gate": REELS_MAP,
      "defect": "the like count is read from the comment count",
      "edits": [
         (
            PARSE,
            'like_count=_required_integer(media, "like_count", media_path),',
            'like_count=_required_integer(media, "comment_count", media_path),',
         )
      ],
   },
   {
      "gate": REELS_MAP,
      "defect": "the reel is read from the edge node rather than its media",
      "edits": [(PARSE, '   media = _object_at(node, ("media",))\n', "   media = node\n")],
   },
   {
      "gate": REELS_MAP,
      "defect": "the reels tab never says it is partial",
      "edits": [
         (
            PARSE,
            "   return ProfileReels(reels=reels, has_more=has_more)",
            "   return ProfileReels(reels=reels, has_more=False)",
         )
      ],
   },
   {
      "gate": PLAY_COUNT,
      "defect": "a null play count is refused",
      "edits": [
         (
            PARSE,
            'play_count=_optional_integer(media, "play_count", media_path),',
            'play_count=_required_integer(media, "play_count", media_path),',
         )
      ],
   },
   {
      "gate": TAGGED_MAP,
      "defect": "the tagged tab never says it is partial",
      "edits": [
         (
            PARSE,
            "   return TaggedPosts(posts=posts, has_more=has_more)",
            "   return TaggedPosts(posts=posts, has_more=False)",
         )
      ],
   },
   {
      "gate": TAGGED_MAP,
      "defect": "the tagged posts come out in reverse",
      "edits": [
         (
            PARSE,
            "      for index, edge in enumerate(edges)\n   )\n"
            "   has_more, _ = _page_info(connection, connection_path)\n\n   return TaggedPosts(",
            "      for index, edge in enumerate(reversed(edges))\n   )\n"
            "   has_more, _ = _page_info(connection, connection_path)\n\n   return TaggedPosts(",
         )
      ],
   },
   {
      "gate": REELS_REQUEST,
      "defect": "the account id is sent once",
      "edits": [(REQUESTS, '         "target_user_id": user_id,\n', "")],
   },
   {
      "gate": REELS_REQUEST,
      "defect": "the reels tab is posted to the other GraphQL path",
      "edits": [
         (
            DOCUMENTS,
            '   finding_id="read-a-profile-s-reels-tab",\n   url=GRAPHQL_QUERY_URL,\n',
            '   finding_id="read-a-profile-s-reels-tab",\n',
         )
      ],
   },
   {
      "gate": REELS_REQUEST,
      "defect": "the reels tab is sent with the bare origin as referer",
      "edits": [
         (
            REQUESTS,
            'session, PROFILE_REELS, variables, referer=f"{ORIGIN}/", user_agent=user_agent',
            "session, PROFILE_REELS, variables, referer=ORIGIN, user_agent=user_agent",
         )
      ],
   },
   {
      "gate": REELS_REQUEST,
      "defect": "a username reaches the reels query",
      "edits": [
         (
            CORE,
            "   refuse_what_is_not_a_user_id(user_id)\n\n   async def attempt() -> ProfileReels:",
            "   async def attempt() -> ProfileReels:",
         )
      ],
   },
   {
      "gate": TAGGED_REQUEST,
      "defect": "the tagged count goes out under another name",
      "edits": [
         (
            REQUESTS,
            '      "count": PROFILE_TAB_PAGE_SIZE,\n',
            '      "first": PROFILE_TAB_PAGE_SIZE,\n',
         )
      ],
   },
   {
      "gate": TAGGED_REQUEST,
      "defect": "a username reaches the tagged query",
      "edits": [
         (
            CORE,
            "   refuse_what_is_not_a_user_id(user_id)\n\n   async def attempt() -> TaggedPosts:",
            "   async def attempt() -> TaggedPosts:",
         )
      ],
   },
   {
      "gate": FOLLOWING_MAP,
      "defect": "the following page's REST status is not read",
      "edits": [(PARSE, '   _raise_unless_ok(payload, "following page")\n', "")],
   },
   {
      "gate": FOLLOWING_REQUEST,
      "defect": "the following page sends the followers list's surface",
      "edits": [
         (
            REQUESTS,
            '   params = {"count": str(FOLLOWING_PAGE_SIZE)}',
            '   params = {"count": str(FOLLOWING_PAGE_SIZE), '
            '"search_surface": _FOLLOW_LIST_SURFACE}',
         )
      ],
   },
   {
      "gate": FOLLOWING_REQUEST,
      "defect": "the following page asks another page size",
      "edits": [(REQUESTS, "FOLLOWING_PAGE_SIZE = 12\n", "FOLLOWING_PAGE_SIZE = 20\n")],
   },
   {
      "gate": FOLLOWING_ACTION,
      "defect": "the following read sends the followers page",
      "edits": [
         (
            CORE,
            "      build_page=build_following_request,\n",
            "      build_page=build_followers_request,\n",
         )
      ],
   },
   {
      "gate": FOLLOWING_WITHOUT,
      "defect": "the following read sends the statuses whatever it is told",
      "edits": [
         (
            CORE,
            "      parse_page=parse_following_page,\n      after=after,\n"
            "      with_statuses=with_statuses,\n",
            "      parse_page=parse_following_page,\n      after=after,\n"
            "      with_statuses=True,\n",
         )
      ],
   },
   {
      "gate": ASYNC_WALK,
      "defect": "the async walk asks for the first page again",
      "edits": [
         (
            NAMESPACE,
            "self.following(user_id, after=offset)",
            "self.following(user_id, after=None)",
         )
      ],
   },
   {
      "gate": BLOCKING_WALK,
      "defect": "the blocking walk asks for the first page again",
      "edits": [
         (
            NAMESPACE,
            "client._impl.profiles.following(user_id, after=offset),",
            "client._impl.profiles.following(user_id, after=None),",
         )
      ],
   },
   {
      "gate": DEFAULT_STATUSES,
      "defect": "following ignores the setting that governs the followers list",
      "edits": [
         (
            NAMESPACE,
            "         read_following_page(\n"
            "            client._sender,\n"
            "            client._session,\n"
            "            user_id,\n"
            "            after=after,\n"
            "            with_statuses=client._behavior.follow_list_statuses,",
            "         read_following_page(\n"
            "            client._sender,\n"
            "            client._session,\n"
            "            user_id,\n"
            "            after=after,\n"
            "            with_statuses=False,",
         )
      ],
   },
   {
      "gate": DUMPSTA_FOLLOWING,
      "defect": "dumpsta following reads the followers list",
      "edits": [
         (
            COMMANDS,
            'lists_the_accounts_followed = arguments.command == "following"',
            "lists_the_accounts_followed = False",
         )
      ],
   },
   {
      "gate": DUMPSTA_TABS,
      "defect": "the reel count is off by one",
      "edits": [(RENDER, '"reel_count": len(tab.reels),', '"reel_count": len(tab.reels) + 1,')],
   },
   {
      "gate": DUMPSTA_TABS,
      "defect": "the tagged text leaves out that the tab may be partial",
      "edits": [
         (
            RENDER,
            'lines.append(f"posts: {len(tab.posts)}  more_available: {tab.has_more}")',
            'lines.append(f"posts: {len(tab.posts)}")',
         )
      ],
   },
   {
      "gate": refuses_username("following"),
      "defect": "dumpsta following takes a username for the id",
      "edits": [
         (
            COMMANDS,
            '   following.add_argument(\n      "user_id", metavar="USER_ID", type=account_id,',
            '   following.add_argument(\n      "user_id", metavar="USER_ID", type=str,',
         )
      ],
   },
   {
      "gate": refuses_username("profile-reels"),
      "defect": "dumpsta profile-reels takes a username for the id",
      "edits": [
         (
            COMMANDS,
            '   profile_reels.add_argument(\n      "user_id", metavar="USER_ID", type=account_id,',
            '   profile_reels.add_argument(\n      "user_id", metavar="USER_ID", type=str,',
         )
      ],
   },
   {
      "gate": refuses_username("tagged"),
      "defect": "dumpsta tagged takes a username for the id",
      "edits": [
         (
            COMMANDS,
            '   tagged.add_argument(\n      "user_id", metavar="USER_ID", type=account_id,',
            '   tagged.add_argument(\n      "user_id", metavar="USER_ID", type=str,',
         )
      ],
   },
   {
      "gate": DOCTOR_TABS,
      "defect": "the canary reads the tagged tab of the account its username names",
      "edits": [
         (
            CANARY,
            "build_profile_tagged_request(\n         session, arguments.viewer_id,",
            "build_profile_tagged_request(\n         session, _required(arguments.username),",
         )
      ],
   },
   {
      "gate": DOCTOR_TABS,
      "defect": "the canary reads the reels tab with the tagged tab's mapper",
      "edits": [
         (
            CANARY,
            "      read=_mapped_by(parse_profile_reels),\n",
            "      read=_mapped_by(parse_tagged_posts),\n",
         )
      ],
   },
   {
      "gate": parity(
         "test_a_namespace_method_reaches_the_core_capability_the_table_names",
         "profiles.reels",
      ),
      "defect": "reels reaches the tagged tab's core function",
      "edits": [(NAMESPACE, "         read_profile_reels(\n", "         read_tagged_posts(\n")],
   },
   {
      "gate": parity(
         "test_a_blocking_namespace_method_forwards_every_argument_on_the_loop_thread",
         "profiles.following",
      ),
      "defect": "the blocking following drops its cursor",
      "edits": [
         (
            NAMESPACE,
            "         self._client._impl.profiles.following(user_id, after=after),\n",
            "         self._client._impl.profiles.following(user_id, after=None),\n",
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
   log_path = LOG_DIR / f"mutation-profile-tabs-more-{stamp}.json"
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
