"""Break the source, watch each feed gate go red, restore.

Same harness and same rule as ``verify_profile_gates.py``: one mutation per gate, only the
gate that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

The field-rename gates in ``tests/test_feed.py`` are parametrised over eight names and share
one mutation, because they share one mechanism: ``_required`` raising instead of returning a
default. That mutation is not repeated here, since ``verify_profile_gates.py`` already breaks
it and the feed gates run against the same function.

Three gates have no row. The facade parity gate reads attributes off both classes, so the only
mutation that reaches it is deleting a method the rest of the suite already covers, and the
two typed-return gates fire under the same mapper mutations as the union gates.

Run from ``engine/`` with ``uv run python scripts/verify_feed_gates.py``. Writes its result to
``engine/logs/``.
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

COMMANDS_FEED = "dumpstagram/_cli/commands/feed.py"
DOCUMENTS_FEED = "dumpstagram/_private/web/documents/feed.py"
PARSE_FEED = "dumpstagram/_private/web/parse/feed.py"
PARSE_MEDIA = "dumpstagram/_private/web/parse/media.py"
REQUESTS_FEED = "dumpstagram/_private/web/requests/feed.py"
CAPABILITY = "dumpstagram/_core/feed.py"
MAIN = "dumpstagram/_cli/main.py"
RENDER_FEED = "dumpstagram/_cli/render/feed.py"
RENDER_MEDIA = "dumpstagram/_cli/render/media.py"

FEED_HAS_ITS_OWN_PATH = """   finding_id="home-timeline-feed-page",
   url=GRAPHQL_QUERY_URL,
"""

FEED_INHERITS_THE_DEFAULT_PATH = """   finding_id="home-timeline-feed-page",
"""

UNION_DEMANDS_ONE_SLOT = """   if len(filled) != 1:
      raise SchemaChanged(
         f"{path} filled {len(filled)} of its union slots rather than exactly one", path=path
      )

   slot = filled[0]"""

UNION_TAKES_WHATEVER_IS_THERE = """   if not filled:
      return FeedItem(kind=FeedItemKind.POST)

   slot = filled[0]"""

UNKNOWN_SLOT_RAISES = """   try:
      kind = FeedItemKind(slot)
   except ValueError as failure:
      raise SchemaChanged(
         f"{path}.{slot} is a union slot this version does not know", path=path
      ) from failure"""

UNKNOWN_SLOT_IS_A_POST = """   try:
      kind = FeedItemKind(slot)
   except ValueError:
      kind = FeedItemKind.POST"""

TAKEN_AT_IS_SECONDS = """   raw = _required(node, "taken_at", path)

   if isinstance(raw, bool) or not isinstance(raw, int):
      raise SchemaChanged(f"{path}.taken_at is not an integer", path=f"{path}.taken_at")

   return datetime.fromtimestamp(raw, tz=UTC)"""

TAKEN_AT_IS_MILLISECONDS = """   raw = _required(node, "taken_at", path)

   from dumpstagram._private.web.parse.common import MILLISECONDS_PER_SECOND

   return datetime.fromtimestamp(int(raw) / MILLISECONDS_PER_SECOND, tz=UTC)"""

POST_READS_BOTH_IDENTIFIERS = """   return Post(
      id=_required_string(node, "id", path),
      pk=_required_string(node, "pk", path),"""

POST_TREATS_THEM_AS_ONE = """   return Post(
      id=_required_string(node, "pk", path),
      pk=_required_string(node, "pk", path),"""

AUTHOR_COMES_FROM_USER = """   author = _required(node, "user", path)
   author_path = f"{path}.user\""""

AUTHOR_COMES_FROM_OWNER_ID = """   author = _required(node, "owner_id", path)
   author_path = f"{path}.owner_id\""""

IMAGES_KEEP_EVERY_CANDIDATE = """   return tuple(built)


MANIFEST_ROOT = """

IMAGES_KEEP_THE_FIRST = """   return tuple(built[:1])


MANIFEST_ROOT = """

CURSOR_COMES_FROM_PAGE_INFO = (
   '   has_next_page = _required_flag(page_info, "has_next_page", page_info_path)\n'
   '   end_cursor = _optional_string(page_info, "end_cursor", page_info_path)\n'
   "\n"
   "   return Page(items=items, has_next_page=has_next_page, end_cursor=end_cursor)"
)

CURSOR_COMES_FROM_A_LENGTH = """   has_next_page = len(items) >= 12
   end_cursor = _optional_string(page_info, "end_cursor", page_info_path)

   return Page(items=items, has_next_page=has_next_page, end_cursor=end_cursor)"""

FEED_SENDS_THE_CURSOR = """      "after": after,
      "before": None,
      "data": {"""

FEED_DROPS_THE_CURSOR = """      "after": None,
      "before": None,
      "data": {"""

CAPABILITY_PASSES_THE_CURSOR = (
   """      request = build_feed_page_request(session, after=after, user_agent=user_agent)"""
)

CAPABILITY_LOSES_THE_CURSOR = (
   """      request = build_feed_page_request(session, user_agent=user_agent)"""
)

CLI_STOPS_ON_THE_TERMINATOR = """      if not page.has_next_page:
         break

      cursor = page.end_cursor

   return pages"""

CLI_STOPS_ON_A_LENGTH = """      if len(page.items) < 12:
         break

      cursor = page.end_cursor

   return pages"""

CLI_SENDS_THE_CURSOR = """   pages: list[Page[FeedItem]] = []
   cursor = arguments.after"""

CLI_IGNORES_THE_CURSOR = """   pages: list[Page[FeedItem]] = []
   cursor = None"""

CLI_COUNTS_BOTH = (
   """      "post_count": sum(1 for item in items if item.kind is FeedItemKind.POST),"""
)

CLI_COUNTS_ITEMS_TWICE = """      "post_count": len(items),"""

CLI_TRAILER_SEES_EVERY_ITEM = """   items = [item for page in pages for item in page.items]
   shown = [item for item in items if item.post is not None] if arguments.posts_only else items

   payload = {
      "command": "feed",
      **describe_feed_pages(pages),"""

CLI_TRAILER_SEES_THE_FILTERED_LIST = """   items = [item for page in pages for item in page.items]
   shown = [item for item in items if item.post is not None] if arguments.posts_only else items

   payload = {
      "command": "feed",
      **describe_feed_pages([Page(items=tuple(shown), has_next_page=False, end_cursor=None)]),"""

FEED_CLOSES_UNDER_A_TRY = """   finally:
      client.close()

   items = [item for page in pages for item in page.items]"""

FEED_CLOSES_WITHOUT_ONE = """   finally:
      pass

   items = [item for page in pages for item in page.items]"""

MUTATIONS = [
   {
      "gate": "tests/test_feed.py::test_the_feed_request_goes_to_the_path_this_query_answers_on",
      "defect": "the feed is posted to the other path, which answers 200 with an empty feed",
      "file": DOCUMENTS_FEED,
      "find": FEED_HAS_ITS_OWN_PATH,
      "replace": FEED_INHERITS_THE_DEFAULT_PATH,
   },
   {
      "gate": (
         "tests/test_feed.py::test_the_feed_request_carries_its_document_and_the_cursor_it_was_given"
      ),
      "defect": "the cursor never reaches the wire, so every page is the first page",
      "file": REQUESTS_FEED,
      "find": FEED_SENDS_THE_CURSOR,
      "replace": FEED_DROPS_THE_CURSOR,
   },
   {
      "gate": (
         "tests/test_feed.py::test_an_item_with_no_filled_slot_raises_rather_than_being_skipped"
      ),
      "defect": "a union that stopped being a union is mapped as an empty post",
      "file": PARSE_FEED,
      "find": UNION_DEMANDS_ONE_SLOT,
      "replace": UNION_TAKES_WHATEVER_IS_THERE,
   },
   {
      "gate": "tests/test_feed.py::test_a_union_slot_this_version_does_not_know_raises",
      "defect": "a tenth slot arrives and is reported as a post that has no media",
      "file": PARSE_FEED,
      "find": UNKNOWN_SLOT_RAISES,
      "replace": UNKNOWN_SLOT_IS_A_POST,
   },
   {
      "gate": "tests/test_feed.py::test_taken_at_is_read_as_whole_seconds_and_not_as_milliseconds",
      "defect": "the unit is borrowed from a direct message, dating every post to 1970",
      "file": PARSE_MEDIA,
      "find": TAKEN_AT_IS_SECONDS,
      "replace": TAKEN_AT_IS_MILLISECONDS,
   },
   {
      "gate": "tests/test_feed.py::test_the_post_carries_both_identifiers_because_they_differ_here",
      "defect": "pk and id are treated as one value, which they are not on a media node",
      "file": PARSE_MEDIA,
      "find": POST_READS_BOTH_IDENTIFIERS,
      "replace": POST_TREATS_THEM_AS_ONE,
   },
   {
      "gate": (
         "tests/test_feed.py::test_the_author_comes_from_the_user_object_and_not_from_owner_id"
      ),
      "defect": "the author is read off owner_id, which is an object rather than the number",
      "file": PARSE_MEDIA,
      "find": AUTHOR_COMES_FROM_USER,
      "replace": AUTHOR_COMES_FROM_OWNER_ID,
   },
   {
      "gate": "tests/test_feed.py::test_every_image_rendition_is_kept_in_the_order_it_arrived",
      "defect": "one crop is picked here, making every other aspect ratio unreachable",
      "file": PARSE_MEDIA,
      "find": IMAGES_KEEP_EVERY_CANDIDATE,
      "replace": IMAGES_KEEP_THE_FIRST,
   },
   {
      "gate": "tests/test_feed.py::test_the_cursor_comes_from_page_info_and_never_from_an_edge",
      "defect": "the terminator is derived from a page length rather than from the server",
      "file": PARSE_FEED,
      "find": CURSOR_COMES_FROM_PAGE_INFO,
      "replace": CURSOR_COMES_FROM_A_LENGTH,
   },
   {
      "gate": "tests/test_feed.py::test_the_capability_passes_the_cursor_it_was_given_to_the_wire",
      "defect": "the capability accepts a cursor and drops it before building the request",
      "file": CAPABILITY,
      "find": CAPABILITY_PASSES_THE_CURSOR,
      "replace": CAPABILITY_LOSES_THE_CURSOR,
   },
   {
      "gate": (
         "tests/test_cli.py::test_the_feed_command_stops_on_the_terminator_and_not_on_a_page_length"
      ),
      "defect": "the command stops on a short page, which every measured page was",
      "file": COMMANDS_FEED,
      "find": CLI_STOPS_ON_THE_TERMINATOR,
      "replace": CLI_STOPS_ON_A_LENGTH,
   },
   {
      "gate": "tests/test_cli.py::test_the_feed_command_passes_a_given_cursor_to_the_first_request",
      "defect": "--after parses and is then ignored, so resuming silently restarts",
      "file": COMMANDS_FEED,
      "find": CLI_SENDS_THE_CURSOR,
      "replace": CLI_IGNORES_THE_CURSOR,
   },
   {
      "gate": "tests/test_cli.py::test_the_feed_json_form_separates_items_from_posts",
      "defect": "items and posts are conflated, and they differed on every measured page",
      "file": RENDER_FEED,
      "find": CLI_COUNTS_BOTH,
      "replace": CLI_COUNTS_ITEMS_TWICE,
   },
   {
      "gate": "tests/test_cli.py::test_posts_only_hides_the_other_items_but_still_counts_them",
      "defect": "the filter also filters the trailer, so a page looks shorter than it was",
      "file": COMMANDS_FEED,
      "find": CLI_TRAILER_SEES_EVERY_ITEM,
      "replace": CLI_TRAILER_SEES_THE_FILTERED_LIST,
   },
   {
      "gate": "tests/test_cli.py::test_the_feed_json_form_carries_the_post_identity_and_its_author",
      "defect": "a contract key is renamed under whatever scripts the command",
      "file": RENDER_MEDIA,
      "find": '      "like_count": post.like_count,',
      "replace": '      "likes": post.like_count,',
   },
   {
      "gate": "tests/test_cli.py::test_the_feed_command_prints_no_credential_when_the_read_fails",
      "defect": "a session token reaches stderr inside a message nobody wrote by hand",
      "file": MAIN,
      "find": '      print(redact(f"{type(failure).__name__}: {failure}"), file=errors)',
      "replace": '      print(f"{type(failure).__name__}: {failure}", file=errors)',
   },
   {
      "gate": "tests/test_cli.py::test_the_feed_command_closes_its_client_even_when_the_read_fails",
      "defect": "a failed read leaves the loop thread running, so the command hangs",
      "file": COMMANDS_FEED,
      "find": FEED_CLOSES_UNDER_A_TRY,
      "replace": FEED_CLOSES_WITHOUT_ONE,
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

   for cached in ENGINE.glob("dumpstagram/**/__pycache__"):
      shutil.rmtree(cached, ignore_errors=True)

   return subprocess.run(
      [sys.executable, "-B", "-m", "pytest", gate, "-q", "--no-header", "-p", "no:cacheprovider"],
      cwd=ENGINE,
      capture_output=True,
      text=True,
      env=environment,
   )


def apply_mutation(mutation: dict[str, str]) -> str:
   path = ENGINE / mutation["file"]
   original = path.read_text(encoding="utf-8")

   occurrences = original.count(mutation["find"])

   if occurrences != 1:
      raise SystemExit(
         f"mutation anchor found {occurrences} times in {mutation['file']} "
         f"for {mutation['gate']}, expected exactly once"
      )

   path.write_text(original.replace(mutation["find"], mutation["replace"], 1), encoding="utf-8")

   return original


def main() -> int:
   results = []

   for mutation in MUTATIONS:
      path = ENGINE / mutation["file"]
      original = apply_mutation(mutation)

      try:
         mutated = run_gate(mutation["gate"])
      finally:
         path.write_text(original, encoding="utf-8")

      restored = run_gate(mutation["gate"])

      results.append(
         {
            "gate": mutation["gate"],
            "defect": mutation["defect"],
            "mutated_file": mutation["file"],
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
   log_path = LOG_DIR / f"mutation-feed-{stamp}.json"
   log_path.write_text(
      json.dumps({"every_gate_fired": every_gate_fired, "gates": results}, indent=2) + "\n",
      encoding="utf-8",
   )

   for entry in results:
      status = (
         "red then green"
         if entry["red_under_mutation"] and entry["green_after_restore"]
         else "DID NOT FIRE"
      )
      print(f"{status}: {entry['gate']}")

   print(f"log written to {log_path}")

   return 0 if every_gate_fired else 1


if __name__ == "__main__":
   raise SystemExit(main())
