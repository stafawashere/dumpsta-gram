"""Break E2 batch 7, discovery, watch each gate go red, restore.

Same harness and same rule as ``verify_account_gates.py``: one mutation per entry below, only the
gate that should catch it is run, every anchor must be found exactly once, and every file is
restored from an in-memory copy in a ``finally`` so an interrupted run cannot leave a mutation
behind.

The mutations cover the explore grid's sections, posts and more flag, the REST keys read as null
and the carousel slides, the refusals, the place's fields, the place's grid and its more flag,
the new posts flag, the four requests, the identifier and tab refusals, the one request each read
sends, both namespaces, the commands, the canary's place steps, and the namespace parity gates
for the new methods.

Run from ``engine/`` with ``uv run python scripts/verify_discovery_gates.py``. Writes its result
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

PARSE = "dumpstagram/_private/web/parse/discovery.py"
REQUESTS = "dumpstagram/_private/web/requests/discovery.py"
CORE = "dumpstagram/_core/discovery.py"
MODELS = "dumpstagram/models/discovery.py"
NAMESPACE = "dumpstagram/namespaces/feeds.py"
RENDER = "dumpstagram/_cli/render/discovery.py"
COMMANDS = "dumpstagram/_cli/commands/discovery.py"
CANARY = "dumpstagram/_private/web/canary.py"
GATES = "tests/test_discovery.py"
DOCTOR_GATES = "tests/test_doctor.py"
PARITY_GATES = "tests/test_facade_parity.py"


def gate(name: str) -> str:
   return f"{GATES}::{name}"


def parity(name: str, qualified: str) -> str:
   return f"{PARITY_GATES}::{name}[{qualified}]"


EXPLORE = gate("test_the_explore_grid_maps_every_section_with_its_featured_and_fill_posts_in_order")
ABSENT = gate("test_an_explore_post_reads_what_the_rest_shape_leaves_out_as_null")
CAROUSEL = gate(
   "test_an_explore_carousel_maps_every_slide_though_its_photo_slides_carry_no_video_keys"
)
REFUSED = gate("test_an_unknown_block_a_refusal_and_a_key_outside_the_absent_set_are_not_mapped")
PLACE = gate("test_a_place_maps_every_field_from_its_own_key")
GRID = gate("test_a_places_grid_maps_each_post_as_a_thumbnail_in_order_with_the_more_flag")
NEW_POSTS = gate("test_the_new_posts_check_is_the_upstreams_flag")
REQUESTS_SENT = gate("test_the_four_reads_send_what_the_replays_sent")
IDENTIFIERS = gate("test_a_name_or_an_unobserved_tab_is_refused_before_anything_is_sent")
ONE_REQUEST = gate("test_each_feeds_read_sends_its_one_request_and_nothing_pages_a_places_grid")
BLOCKING = gate("test_the_blocking_feeds_reads_answer_as_their_async_twins")
DUMPSTA = gate("test_dumpsta_explore_place_location_and_new_posts_print_everything_read")
DUMPSTA_REFUSES = gate("test_dumpsta_place_and_location_refuse_a_name")
PLACE_STEPS = (
   f"{DOCTOR_GATES}::"
   "test_the_place_steps_read_the_first_place_a_post_names_and_are_skipped_without_one"
)
REACHES_CORE = "test_a_namespace_method_reaches_the_core_capability_the_table_names"

MUTATIONS: list[dict[str, object]] = [
   {
      "gate": EXPLORE,
      "defect": "the featured posts are read from the fill tiles",
      "edits": [
         (
            PARSE,
            "for index, item in enumerate(featured_items)",
            "for index, item in enumerate(fill_items)",
         )
      ],
   },
   {
      "gate": EXPLORE,
      "defect": "the first section is dropped",
      "edits": [
         (
            PARSE,
            "for index, section in enumerate(sections)",
            "for index, section in enumerate(sections[1:])",
         )
      ],
   },
   {
      "gate": EXPLORE,
      "defect": "the more flag is a constant",
      "edits": [
         (
            PARSE,
            'more_available=_required_flag(payload, "more_available", _EXPLORE),',
            "more_available=True,",
         )
      ],
   },
   {
      "gate": EXPLORE,
      "defect": "the grid's posts put each section's fill tiles before its featured ones",
      "edits": [
         (
            MODELS,
            "for post in (*section.featured, *section.posts)",
            "for post in (*section.posts, *section.featured)",
         )
      ],
   },
   {
      "gate": ABSENT,
      "defect": "an absent is_seen is read as a required flag",
      "edits": [
         (
            PARSE,
            "parse_post(_absent_as_null(node), path, null_is_unseen=True)",
            "parse_post(_absent_as_null(node), path, null_is_unseen=False)",
         )
      ],
   },
   {
      "gate": ABSENT,
      "defect": "an absent video_versions is not read as null",
      "edits": [(PARSE, '      "video_versions",\n   }\n)', "   }\n)")],
   },
   {
      "gate": CAROUSEL,
      "defect": "the carousel's slides are not given the absent keys",
      "edits": [
         (
            PARSE,
            'graph_node["carousel_media"] = [_absent_as_null(slide) for slide in slides]',
            'graph_node["carousel_media"] = slides',
         )
      ],
   },
   {
      "gate": REFUSED,
      "defect": "a section block the mapper does not know is dropped",
      "edits": [(PARSE, "   if unknown:\n", "   if unknown and False:\n")],
   },
   {
      "gate": REFUSED,
      "defect": "a REST refusal is mapped",
      "edits": [(PARSE, '   _raise_unless_ok(payload, "explore grid")\n', "")],
   },
   {
      "gate": PLACE,
      "defect": "lat is read from lng",
      "edits": [
         (PARSE, 'lat=_coordinate(info, "lat", path),', 'lat=_coordinate(info, "lng", path),')
      ],
   },
   {
      "gate": PLACE,
      "defect": "the city is read from the zip code",
      "edits": [
         (
            PARSE,
            'city=_required_string(info, "location_city", path),',
            'city=_required_string(info, "location_zip", path),',
         )
      ],
   },
   {
      "gate": PLACE,
      "defect": "the price range is read from the post count",
      "edits": [
         (
            PARSE,
            'price_range=_required_integer(info, "price_range", path),',
            'price_range=_required_integer(info, "media_count", path),',
         )
      ],
   },
   {
      "gate": GRID,
      "defect": "the first post of a place's grid is dropped",
      "edits": [
         (
            PARSE,
            "      for index, edge in enumerate(edges)\n",
            "      for index, edge in enumerate(edges[1:])\n",
         )
      ],
   },
   {
      "gate": GRID,
      "defect": "the grid's more flag is a constant",
      "edits": [
         (
            PARSE,
            'has_more=_required_flag(page_info, "has_next_page", page_info_path),',
            "has_more=True,",
         )
      ],
   },
   {
      "gate": NEW_POSTS,
      "defect": "the new posts flag is a constant",
      "edits": [
         (
            PARSE,
            '   return _required_flag(root, "new_feed_posts_exist", ".".join(NEW_FEED_POSTS_PATH))',
            "   return False",
         )
      ],
   },
   {
      "gate": REQUESTS_SENT,
      "defect": "the explore grid sends another module",
      "edits": [(REQUESTS, '"module": "explore_popular",', '"module": "explore",')],
   },
   {
      "gate": REQUESTS_SENT,
      "defect": "the explore grid's referer is the site root",
      "edits": [(REQUESTS, '"referer": EXPLORE_REFERER,', '"referer": f"{ORIGIN}/",')],
   },
   {
      "gate": REQUESTS_SENT,
      "defect": "the place's header asks for nearby places",
      "edits": [(REQUESTS, '"show_nearby": False}', '"show_nearby": True}')],
   },
   {
      "gate": REQUESTS_SENT,
      "defect": "the grid asks for another page size",
      "edits": [(REQUESTS, '"first": LOCATION_PAGE_SIZE,', '"first": 24,')],
   },
   {
      "gate": REQUESTS_SENT,
      "defect": "the grid sends another tab",
      "edits": [(REQUESTS, '"tab": tab.value,', '"tab": "recent",')],
   },
   {
      "gate": REQUESTS_SENT,
      "defect": "the new posts check's referer is the explore page",
      "edits": [(REQUESTS, 'referer=f"{ORIGIN}/",', 'referer=f"{ORIGIN}/explore/",')],
   },
   {
      "gate": IDENTIFIERS,
      "defect": "a place id is not checked",
      "edits": [
         (
            REQUESTS,
            "is_a_location_id = _LOCATION_ID.fullmatch(location_id) is not None",
            "is_a_location_id = True",
         )
      ],
   },
   {
      "gate": IDENTIFIERS,
      "defect": "the tab is not checked before sending",
      "edits": [(CORE, "   tab = LocationTab(tab)\n", "")],
   },
   {
      "gate": ONE_REQUEST,
      "defect": "the explore grid spends a bootstrap on every read",
      "edits": [
         (
            CORE,
            "      request = build_explore_grid_request(\n",
            "      await bootstrap(sender, session, user_agent=user_agent)\n"
            "      request = build_explore_grid_request(\n",
         )
      ],
   },
   {
      "gate": BLOCKING,
      "defect": "the blocking place reads the place's grid",
      "edits": [
         (
            NAMESPACE,
            "         self._client._impl.feeds.place(location_id),",
            "         self._client._impl.feeds.location(location_id),",
         )
      ],
   },
   {
      "gate": DUMPSTA,
      "defect": "the explore post count counts sections",
      "edits": [(RENDER, '"post_count": len(grid.posts),', '"post_count": len(grid.sections),')],
   },
   {
      "gate": DUMPSTA,
      "defect": "the featured posts are left out of the JSON",
      "edits": [
         (
            RENDER,
            '"featured": [describe_post(post) for post in section.featured],',
            '"featured": [],',
         )
      ],
   },
   {
      "gate": DUMPSTA,
      "defect": "the place's grid more flag is inverted",
      "edits": [
         (RENDER, '"more_available": page.has_more,', '"more_available": not page.has_more,')
      ],
   },
   {
      "gate": DUMPSTA,
      "defect": "the place's grid text form leaves out the first post",
      "edits": [(RENDER, "   for post in page.posts:\n", "   for post in page.posts[1:]:\n")],
   },
   {
      "gate": DUMPSTA,
      "defect": "the new posts flag is inverted",
      "edits": [(COMMANDS, '"new_posts": has_new_posts}', '"new_posts": not has_new_posts}')],
   },
   {
      "gate": DUMPSTA_REFUSES,
      "defect": "the command takes a place name",
      "edits": [
         (
            COMMANDS,
            "is_a_location_id = _LOCATION_ID.fullmatch(value) is not None",
            "is_a_location_id = True",
         )
      ],
   },
   {
      "gate": PLACE_STEPS,
      "defect": "the grid step learns no place",
      "edits": [(CANARY, "   _learn_first_location(page.items, arguments)\n", "")],
   },
   {
      "gate": PLACE_STEPS,
      "defect": "the place header step is sent with no place",
      "edits": [
         (
            CANARY,
            '      query=LOCATION_INFO,\n      requires="location_id",',
            "      query=LOCATION_INFO,\n      requires=None,",
         )
      ],
   },
   {
      "gate": parity(REACHES_CORE, "feeds.explore"),
      "defect": "explore reaches the new posts check's core function",
      "edits": [(NAMESPACE, "         read_explore_grid(\n", "         read_new_feed_posts(\n")],
   },
   {
      "gate": parity(REACHES_CORE, "feeds.place"),
      "defect": "place reaches the grid's core function",
      "edits": [(NAMESPACE, "         read_location_info(\n", "         read_location_posts(\n")],
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
   log_path = LOG_DIR / f"mutation-discovery-{stamp}.json"
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
