"""Break E2 batch 11b, the reels feed, the personalised typeahead and the keyword grid, watch
each gate go red, restore.

Same harness and same rule as ``verify_profile_tabs_more_gates.py``: one mutation per entry below,
only the gate that should catch it is run, every anchor must be found exactly once, and every
file is restored from an in-memory copy in a ``finally`` so an interrupted run cannot leave a
mutation behind.

The mutations cover the reels mapper and what it reads as ruled, the reels cursor and both reels
requests, both walks, the typeahead mapper's order, its request and session id, the route
setting on both methods, the keyword grid's mapper, rows and request, the four commands, the
canary's four steps and the namespace parity gates.

Run from ``engine/`` with ``uv run python scripts/verify_discovery_search_gates.py``. Writes its
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

BEHAVIOR = "dumpstagram/behavior.py"
DISCOVERY_PARSE = "dumpstagram/_private/web/parse/discovery.py"
DISCOVERY_REQUESTS = "dumpstagram/_private/web/requests/discovery.py"
DISCOVERY_CORE = "dumpstagram/_core/discovery.py"
SEARCH_PARSE = "dumpstagram/_private/web/parse/search.py"
SEARCH_REQUESTS = "dumpstagram/_private/web/requests/search.py"
SEARCH_CORE = "dumpstagram/_core/search.py"
CANARY = "dumpstagram/_private/web/canary.py"
FEEDS = "dumpstagram/namespaces/feeds.py"
SEARCH = "dumpstagram/namespaces/search.py"
DISCOVERY_COMMANDS = "dumpstagram/_cli/commands/discovery.py"
SEARCH_COMMANDS = "dumpstagram/_cli/commands/search.py"
DISCOVERY_RENDER = "dumpstagram/_cli/render/discovery.py"
GATES = "tests/test_discovery_search.py"
DOCTOR_GATES = "tests/test_doctor.py"
PARITY_GATES = "tests/test_facade_parity.py"


def gate(name: str) -> str:
   return f"{GATES}::{name}"


def parity(name: str, qualified: str) -> str:
   return f"{PARITY_GATES}::{name}[{qualified}]"


REELS_MAP = gate("test_a_reels_page_maps_every_reel_with_what_the_feed_leaves_out_read_as_ruled")
AUDIO = gate("test_an_original_sound_without_its_mute_flag_is_no_audio_and_a_song_is_read")
REELS_FIRST = gate("test_the_first_reels_page_is_the_tabs_query_with_its_constants")
REELS_NEXT = gate("test_the_next_reels_page_names_the_reels_the_page_before_it_showed")
CURSOR_REFUSED = gate("test_a_cursor_no_reels_page_handed_out_is_refused_before_anything_is_sent")
ASYNC_WALK = gate("test_the_async_reels_walk_reads_the_next_page_query_after_the_first")
BLOCKING_WALK = gate("test_the_blocking_reels_walk_answers_as_its_async_twin")
TYPEAHEAD_ORDER = gate("test_the_personalised_typeahead_orders_its_rows_by_the_upstreams_position")
TYPEAHEAD_REQUEST = gate(
   "test_the_personalised_typeahead_is_the_first_query_of_a_fresh_search_session"
)
ROUTE = gate("test_accounts_and_top_send_the_personalised_query_unless_the_route_departs")
KEYWORD_MAP = gate("test_the_keyword_grid_maps_every_post_of_its_grid_rows_in_order")
KEYWORD_ROW = gate("test_a_keyword_row_of_another_kind_or_a_filled_empty_row_raises")
KEYWORD_REQUEST = gate("test_the_keyword_grid_is_the_pages_query_with_one_session_id_sent_twice")
BLOCKING_SEARCH = gate("test_the_blocking_search_reads_answer_as_their_async_twins")
DUMPSTA_REELS = gate("test_dumpsta_reels_reads_pages_until_the_terminator_passing_each_cursor")
DUMPSTA_SEARCH = gate(
   "test_dumpsta_search_top_and_keyword_print_everything_read_on_the_chosen_route"
)
DOCTOR = (
   f"{DOCTOR_GATES}::test_the_reels_and_search_steps_of_batch_11b_read_what_earlier_steps_learned"
)
FORWARDS = "test_a_blocking_namespace_method_forwards_every_argument_on_the_loop_thread"
REACHES = "test_a_namespace_method_reaches_the_core_capability_the_table_names"


def mutation(gate: str, defect: str, path: str, find: str, replace: str) -> dict[str, object]:
   return {"gate": gate, "defect": defect, "edits": [(path, find, replace)]}


MUTATIONS: list[dict[str, object]] = [
   mutation(
      REELS_MAP,
      "a partnership flag the reel sends is overwritten with False",
      DISCOVERY_PARSE,
      '   node.setdefault("is_paid_partnership", False)\n',
      '   node["is_paid_partnership"] = False\n',
   ),
   mutation(
      REELS_MAP,
      "the id-only collaborator rows are read as accounts",
      DISCOVERY_PARSE,
      '   node.pop("coauthor_producers", None)\n',
      "",
   ),
   mutation(
      REELS_MAP,
      "the absent seen flag is not read as null",
      DISCOVERY_PARSE,
      'REEL_KEYS_ABSENT_AS_NULL = frozenset({"is_seen", "accessibility_caption"})',
      'REEL_KEYS_ABSENT_AS_NULL = frozenset({"accessibility_caption"})',
   ),
   mutation(
      REELS_MAP,
      "a reels page never says more exist",
      DISCOVERY_PARSE,
      '      has_next_page=_required_flag(page_info, "has_next_page", page_info_path),\n',
      "      has_next_page=False,\n",
   ),
   mutation(
      REELS_MAP,
      "the reel is read from the edge node rather than its media",
      DISCOVERY_PARSE,
      '   return parse_post(_reel_feed_node(media), f"{node_path}.media", null_is_unseen=True)',
      '   return parse_post(_reel_feed_node(node), f"{node_path}.media", null_is_unseen=True)',
   ),
   mutation(
      AUDIO,
      "an original sound that carries its mute flag is dropped too",
      DISCOVERY_PARSE,
      "   lacks_the_mute_flag = isinstance(original, "
      'dict) and "should_mute_audio" not in original\n',
      "   lacks_the_mute_flag = isinstance(original, dict)\n",
   ),
   mutation(
      AUDIO,
      "every reel's track is dropped, a song with the sounds",
      DISCOVERY_PARSE,
      "   if lacks_the_mute_flag:\n",
      "   if isinstance(metadata, dict):\n      metadata = {**metadata, 'music_info': None}\n",
   ),
   mutation(
      REELS_FIRST,
      "the first page asks for the next page's size",
      DISCOVERY_REQUESTS,
      "REELS_FIRST_PAGE_SIZE = 2\n",
      "REELS_FIRST_PAGE_SIZE = 10\n",
   ),
   mutation(
      REELS_FIRST,
      "the first page turns channel pagination on",
      DISCOVERY_REQUESTS,
      '      "useChannelsPagination": False,\n',
      '      "useChannelsPagination": True,\n',
   ),
   mutation(
      REELS_FIRST,
      "the reels pages carry the site root as referer",
      DISCOVERY_REQUESTS,
      'REELS_PAGE_URL = f"{ORIGIN}/reels/"',
      'REELS_PAGE_URL = f"{ORIGIN}/"',
   ),
   mutation(
      REELS_NEXT,
      "the next page names no reel as seen",
      DISCOVERY_REQUESTS,
      '         "seen_reels": seen_reels_text(seen_reel_pks),',
      '         "seen_reels": seen_reels_text(()),',
   ),
   mutation(
      REELS_NEXT,
      "seen_reels is not the browser's compact JSON string",
      DISCOVERY_REQUESTS,
      '   return json.dumps([{"id": pk} for pk in reel_pks], separators=(",", ":"))',
      '   return json.dumps([{"id": pk} for pk in reel_pks])',
   ),
   mutation(
      REELS_NEXT,
      "the engine's own cursor is sent as the upstream's",
      DISCOVERY_CORE,
      "            cursor=upstream_cursor,\n",
      "            cursor=after or upstream_cursor,\n",
   ),
   mutation(
      REELS_NEXT,
      "a page's cursor does not carry its reels forward",
      DISCOVERY_CORE,
      "      shown = tuple(reel.pk for reel in page.items)\n",
      "      shown: tuple[str, ...] = ()\n",
   ),
   mutation(
      REELS_NEXT,
      "the next page asks for the first page's size",
      DISCOVERY_REQUESTS,
      "REELS_NEXT_PAGE_SIZE = 10\n",
      "REELS_NEXT_PAGE_SIZE = 2\n",
   ),
   mutation(
      CURSOR_REFUSED,
      "a cursor naming anything but reel pks is let through",
      DISCOVERY_CORE,
      "   names_only_reels = all(pk.isascii() and pk.isdigit() for pk in seen_reel_pks)\n",
      "   names_only_reels = True\n",
   ),
   mutation(
      CURSOR_REFUSED,
      "an empty cursor reads the first page",
      DISCOVERY_CORE,
      "   next_page_key = None if after is None else split_reels_cursor(after)\n",
      "   next_page_key = None if not after else split_reels_cursor(after)\n",
   ),
   mutation(
      ASYNC_WALK,
      "the async walk rereads the first page",
      FEEDS,
      "      return iterate_pages(lambda cursor: self"
      ".reels(after=cursor), limit=limit, after=after)",
      "      return iterate_pages(lambda cursor: self.reels(after=None), limit=limit, after=after)",
   ),
   mutation(
      BLOCKING_WALK,
      "the blocking walk drops its cursor",
      FEEDS,
      "            client._impl.feeds.reels(after=cursor),\n",
      "            client._impl.feeds.reels(after=None),\n",
   ),
   mutation(
      TYPEAHEAD_ORDER,
      "the rows are left in list order",
      SEARCH_PARSE,
      "   positioned = sorted([*keywords, *accounts], key=lambda result: result.position or 0)\n",
      "   positioned = [*keywords, *accounts]\n",
   ),
   mutation(
      TYPEAHEAD_ORDER,
      "hashtag rows are dropped",
      SEARCH_PARSE,
      "   return SearchResults(results=(*positioned, *hashtags, *places))",
      "   return SearchResults(results=(*positioned, *places))",
   ),
   mutation(
      TYPEAHEAD_REQUEST,
      "include_reel is sent as a boolean",
      SEARCH_REQUESTS,
      '   "include_reel": "true",\n',
      '   "include_reel": True,\n',
   ),
   mutation(
      TYPEAHEAD_REQUEST,
      "a rank token is sent",
      SEARCH_REQUESTS,
      '      "rank_token": "",\n',
      '      "rank_token": None,\n',
   ),
   mutation(
      TYPEAHEAD_REQUEST,
      "one session id is reused by every search",
      SEARCH_REQUESTS,
      "   return str(uuid.uuid4())\n",
      '   return "00000000-0000-4000-8000-000000000000"\n',
   ),
   mutation(
      TYPEAHEAD_REQUEST,
      "the typeahead carries the explore page as referer",
      SEARCH_REQUESTS,
      '      {"data": data, "hasQuery": True},\n      referer=f"{ORIGIN}/",',
      '      {"data": data, "hasQuery": True},\n      referer=f"{ORIGIN}/explore/",',
   ),
   mutation(
      ROUTE,
      "the default route is the non-profiled query",
      BEHAVIOR,
      "   typeahead_route: TypeaheadRoute = TypeaheadRoute.PERSONALISED\n",
      "   typeahead_route: TypeaheadRoute = TypeaheadRoute.NON_PERSONALISED\n",
   ),
   mutation(
      ROUTE,
      "accounts ignores the departure",
      SEARCH_CORE,
      "   if route is TypeaheadRoute.NON_PERSONALISED:\n "
      "     return await read_non_personalised_typeahead(",
      "   if False:\n      return await read_non_personalised_typeahead(",
   ),
   mutation(
      ROUTE,
      "top ignores the departure",
      SEARCH_CORE,
      "   if route is TypeaheadRoute.NON_PERSONALISED:\n      accounts = await",
      "   if False:\n      accounts = await",
   ),
   mutation(
      ROUTE,
      "the departure's accounts are given a position",
      SEARCH_PARSE,
      "         SearchResult(kind=SearchResultKind.AC"
      "COUNT, account=account) for account in accounts",
      "         SearchResult(kind=SearchResultKind.ACCOUNT, position=0, account=account)\n"
      "         for account in accounts",
   ),
   mutation(
      KEYWORD_MAP,
      "the like count is read from the comment count",
      SEARCH_PARSE,
      '      like_count=_required_integer(node, "like_count", path),',
      '      like_count=_required_integer(node, "comment_count", path),',
   ),
   mutation(
      KEYWORD_MAP,
      "the view count is dropped",
      SEARCH_PARSE,
      '      view_count=_optional_integer(node, "view_count", path),',
      "      view_count=None,",
   ),
   mutation(
      KEYWORD_MAP,
      "the grid never says it is complete",
      SEARCH_PARSE,
      '      has_more=_required_flag(page_info, "has_next_page", page_info_path),',
      "      has_more=True,",
   ),
   mutation(
      KEYWORD_MAP,
      "only the first post of each grid row is read",
      SEARCH_PARSE,
      '      items = _list_of(unit, "items", path)\n',
      '      items = _list_of(unit, "items", path)[:1]\n',
   ),
   mutation(
      KEYWORD_ROW,
      "a row of any kind is skipped",
      SEARCH_PARSE,
      "   is_an_empty_row = kind in EMPTY_KEYWORD_UNITS and not carries_something\n",
      "   is_an_empty_row = True\n",
   ),
   mutation(
      KEYWORD_ROW,
      "a header row that carries something is skipped",
      SEARCH_PARSE,
      "   is_an_empty_row = kind in EMPTY_KEYWORD_UNITS and not carries_something\n",
      "   is_an_empty_row = kind in EMPTY_KEYWORD_UNITS\n",
   ),
   mutation(
      KEYWORD_REQUEST,
      "the grid's two ids are two sessions",
      SEARCH_REQUESTS,
      '      "serp_session_id": search_session_id,\n',
      '      "serp_session_id": new_search_session_id(),\n',
   ),
   mutation(
      KEYWORD_REQUEST,
      "the keyword page's query is not escaped",
      SEARCH_REQUESTS,
      "   return f\"{ORIGIN}/explore/search/keyword/?{urlencode({'q': query}, quote_via=quote)}\"",
      '   return f"{ORIGIN}/explore/search/keyword/?q={query}"',
   ),
   mutation(
      KEYWORD_REQUEST,
      "a blank keyword query is sent",
      SEARCH_CORE,
      "   refuse_what_is_not_a_query(query)\n   search_session_id = new_search_session_id()\n\n"
      "   async def attempt() -> KeywordResults:",
      "   search_session_id = new_search_session_id()\n\n   async def attempt() -> KeywordResults:",
   ),
   mutation(
      BLOCKING_SEARCH,
      "the blocking keyword read asks for the top results",
      SEARCH,
      "         self._client._impl.search.keyword(query),\n",
      "         self._client._impl.search.top(query),\n",
   ),
   mutation(
      DUMPSTA_REELS,
      "dumpsta reels passes no cursor after the first page",
      DISCOVERY_COMMANDS,
      "      cursor = page.end_cursor\n",
      "      cursor = None\n",
   ),
   mutation(
      DUMPSTA_REELS,
      "the text trailer leaves out the reel count",
      DISCOVERY_RENDER,
      '   lines.append(f"pages: {len(pages)}  reels: {'
      'reel_count}  more_available: {more_available}")',
      '   lines.append(f"pages: {len(pages)}  more_available: {more_available}")',
   ),
   mutation(
      DUMPSTA_SEARCH,
      "--non-personalised is ignored",
      SEARCH_COMMANDS,
      "   if not arguments.non_personalised:\n",
      "   if True:\n",
   ),
   mutation(
      DUMPSTA_SEARCH,
      "dumpsta keyword strips the hash from a tag",
      SEARCH_COMMANDS,
      "      grid = client.search.keyword(arguments.query)\n",
      '      grid = client.search.keyword(arguments.query.lstrip("#"))\n',
   ),
   mutation(
      DOCTOR,
      "the canary's next reels page names no reel as seen",
      CANARY,
      "         seen_reel_pks=arguments.seen_reel_pks,\n",
      "         seen_reel_pks=(),\n",
   ),
   mutation(
      DOCTOR,
      "the keyword grid is replayed on unverified text",
      CANARY,
      'CANARY_KEYWORD = "instagram"\n',
      'CANARY_KEYWORD = "instagrams"\n',
   ),
   mutation(
      DOCTOR,
      "the next reels page is replayed after a last page",
      CANARY,
      "   if page.has_next_page:\n      arguments.reels_cursor = page.end_cursor\n",
      "   if True:\n      arguments.reels_cursor = page.end_cursor\n",
   ),
   mutation(
      DOCTOR,
      "the personalised typeahead is replayed on the viewer's id",
      CANARY,
      "         _required(arguments.username),\n     "
      "    search_session_id=new_search_session_id(),",
      "         arguments.viewer_id,\n         search_session_id=new_search_session_id(),",
   ),
   mutation(
      parity(FORWARDS, "search.top"),
      "the blocking top drops its query",
      SEARCH,
      "         self._client._impl.search.top(query),\n",
      '         self._client._impl.search.top("another query"),\n',
   ),
   mutation(
      parity(FORWARDS, "feeds.reels"),
      "the blocking reels drops its cursor",
      FEEDS,
      "         self._client._impl.feeds.reels(after=after),\n",
      "         self._client._impl.feeds.reels(after=None),\n",
   ),
   mutation(
      parity(REACHES, "search.keyword"),
      "the keyword method reaches the top results read",
      SEARCH,
      "         read_keyword_results(\n",
      "         read_top_results(\n",
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
   log_path = LOG_DIR / f"mutation-discovery-search-{stamp}.json"
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
