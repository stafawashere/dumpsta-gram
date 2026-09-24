"""Break the pagination iterators of E1 item 5, watch each gate go red, restore.

Same harness and same rule as ``verify_poller_gates.py``: one mutation per entry below, only the
gate that should catch it is run, every anchor must be found exactly once, and every file is
restored from an in-memory copy in a ``finally`` so an interrupted run cannot leave a mutation
behind. A gate named without parameters runs every surface and every iterator it covers, and is
red when any of them fails.

Run from ``engine/`` with ``uv run python scripts/verify_iterator_gates.py``. Writes its result to
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

GATE_TIMEOUT_SECONDS = 300

PAGING = "dumpstagram/_core/paging.py"
DIRECT = "dumpstagram/namespaces/direct.py"
FEEDS = "dumpstagram/namespaces/feeds.py"
MEDIA = "dumpstagram/namespaces/media.py"
ITERATOR_GATES = "tests/test_iterators.py"
PARITY_GATES = "tests/test_facade_parity.py"

FAST_BEHAVIOR = '__import__("dumpstagram.behavior", fromlist=["FAST"]).FAST'

ASYNC_ITER_HOME = (
   "   def iter_home(self, *, limit: int | None, after: str | None = None) -> "
   "AsyncIterator[FeedItem]:\n"
)
SYNC_ITER_HOME = (
   "   def iter_home(self, *, limit: int | None, after: str | None = None) -> Iterator[FeedItem]:\n"
)


def gate(name: str, suite: str = ITERATOR_GATES) -> str:
   return f"{suite}::{name}"


MUTATIONS: list[dict[str, object]] = [
   {
      "gate": gate("test_the_walk_ends_on_the_page_whose_has_next_page_is_false"),
      "defect": "has_next_page false does not end the walk",
      "edits": [
         (
            PAGING,
            "      has_no_next_page = not page.has_next_page\n",
            "      has_no_next_page = False\n",
         )
      ],
   },
   {
      "gate": gate("test_an_empty_or_short_page_that_says_more_exist_is_followed"),
      "defect": "an empty page ends the walk",
      "edits": [
         (
            PAGING,
            "      has_no_next_page = not page.has_next_page\n",
            "      has_no_next_page = not page.has_next_page or not page.items\n",
         )
      ],
   },
   {
      "gate": gate("test_an_empty_or_short_page_that_says_more_exist_is_followed"),
      "defect": "a page shorter than two items ends the walk",
      "edits": [
         (
            PAGING,
            "      has_no_next_page = not page.has_next_page\n",
            "      has_no_next_page = not page.has_next_page or 0 < len(page.items) < 2\n",
         )
      ],
   },
   {
      "gate": gate("test_the_limit_is_honoured_exactly_without_reading_a_page_it_does_not_use"),
      "defect": "a reached limit does not stop the next page read",
      "edits": [
         (
            PAGING,
            "      return not self.finished and not limit_reached\n",
            "      return not self.finished\n",
         )
      ],
   },
   {
      "gate": gate("test_the_limit_is_honoured_exactly_without_reading_a_page_it_does_not_use"),
      "defect": "the limit yields one item too many",
      "edits": [
         (
            PAGING,
            "         if self.remaining == 0:\n",
            "         if self.remaining == -1:\n",
         )
      ],
   },
   {
      "gate": gate("test_each_page_is_asked_for_with_the_end_cursor_of_the_page_before_it"),
      "defect": "the starting cursor is dropped",
      "edits": [(PAGING, "      self.cursor = after\n", "      self.cursor = None\n")],
   },
   {
      "gate": gate("test_each_page_is_asked_for_with_the_end_cursor_of_the_page_before_it"),
      "defect": "the cursor never advances past the first page",
      "edits": [(PAGING, "      self.cursor = cursor_after(page)\n", "      cursor_after(page)\n")],
   },
   {
      "gate": gate("test_a_page_that_says_more_exist_without_a_cursor_raises"),
      "defect": "a page claiming more with no cursor is followed with no cursor",
      "edits": [(PAGING, "   if page.end_cursor is None:\n", "   if False:\n")],
   },
   {
      "gate": gate("test_a_negative_limit_is_refused_when_the_iterator_is_made"),
      "defect": "a negative limit is taken as no limit",
      "edits": [(PAGING, "   if limit < 0:\n", "   if False:\n")],
   },
   {
      "gate": gate("test_every_page_of_a_walk_departs_through_the_pacer_spaced_like_a_read"),
      "defect": "the async walk reads its pages with no read spacing",
      "edits": [
         (
            MEDIA,
            "lambda cursor: self.comments(post_pk, after=cursor), limit=limit, after=after\n",
            f"lambda cursor: self._client.with_behavior({FAST_BEHAVIOR}).media.comments("
            "post_pk, after=cursor), limit=limit, after=after\n",
         )
      ],
   },
   {
      "gate": gate("test_every_page_of_a_walk_departs_through_the_pacer_spaced_like_a_read"),
      "defect": "the blocking walk reads its pages with no read spacing",
      "edits": [
         (
            MEDIA,
            "            client._impl.media.comments(post_pk, after=cursor),\n",
            f"            client._impl.with_behavior({FAST_BEHAVIOR}).media.comments("
            "post_pk, after=cursor),\n",
         )
      ],
   },
   {
      "gate": gate("test_closing_a_blocking_iterator_early_leaves_nothing_running_on_the_loop"),
      "defect": "the blocking walk reads the next page ahead of its caller",
      "edits": [
         (
            PAGING,
            "   while walk.wants_a_page:\n      page = read_page(walk.cursor)\n",
            '   ahead = __import__("concurrent.futures").futures.ThreadPoolExecutor(1)\n'
            "   prefetched = None\n"
            "\n"
            "   while walk.wants_a_page:\n"
            "      page = prefetched.result() if prefetched else read_page(walk.cursor)\n"
            "      prefetched = (\n"
            "         ahead.submit(read_page, page.end_cursor) if page.has_next_page else None\n"
            "      )\n",
         )
      ],
   },
   {
      "gate": gate(
         "test_an_iterator_takes_its_reads_parameters_plus_a_required_limit_on_both_surfaces",
         PARITY_GATES,
      ),
      "defect": "the blocking iterator's limit gains a default",
      "edits": [
         (
            FEEDS,
            SYNC_ITER_HOME,
            SYNC_ITER_HOME.replace("limit: int | None,", "limit: int | None = 20,"),
         )
      ],
   },
   {
      "gate": gate(
         "test_an_iterator_takes_its_reads_parameters_plus_a_required_limit_on_both_surfaces",
         PARITY_GATES,
      ),
      "defect": "the async iterator is declared async",
      "edits": [(FEEDS, ASYNC_ITER_HOME, ASYNC_ITER_HOME.replace("   def ", "   async def "))],
   },
   {
      "gate": gate(
         "test_both_iterators_forward_every_argument_and_yield_the_same_items", PARITY_GATES
      ),
      "defect": "the blocking iterator drops newer_than_message_id",
      "edits": [(DIRECT, "               newer_than_message_id=newer_than_message_id,\n", "")],
   },
   {
      "gate": gate(
         "test_both_iterators_forward_every_argument_and_yield_the_same_items", PARITY_GATES
      ),
      "defect": "the async iterator drops newer_than_message_id",
      "edits": [
         (
            DIRECT,
            "            thread_fbid, after=cursor, newer_than_message_id=newer_than_message_id\n",
            "            thread_fbid, after=cursor\n",
         )
      ],
   },
   {
      "gate": gate(
         "test_both_iterators_forward_every_argument_and_yield_the_same_items", PARITY_GATES
      ),
      "defect": "the async walk yields each page in reverse",
      "edits": [
         (
            PAGING,
            "      page = await read_page(walk.cursor)\n",
            "      page = await read_page(walk.cursor)\n"
            "      page = type(page)(\n"
            "         items=page.items[::-1],\n"
            "         has_next_page=page.has_next_page,\n"
            "         end_cursor=page.end_cursor,\n"
            "      )\n",
         )
      ],
   },
   {
      "gate": gate(
         "test_a_blocking_iterator_raises_the_async_exception_under_its_own_name", PARITY_GATES
      ),
      "defect": "the blocking iterator's seam note names the page read",
      "edits": [
         (
            MEDIA,
            '            operation="SyncClient.media.iter_comments",\n',
            '            operation="SyncClient.media.comments",\n',
         )
      ],
   },
   {
      "gate": gate("test_every_paged_read_has_an_iterator", PARITY_GATES),
      "defect": "a paged read ships without an iterator",
      "edits": [
         (
            FEEDS,
            "\n\nclass SyncFeeds:",
            "\n\n   async def explore(self, *, after: str | None = None) -> Page[FeedItem]:\n"
            "      raise NotImplementedError\n"
            "\n\nclass SyncFeeds:",
         )
      ],
   },
   {
      "gate": gate(
         "test_iterator_discovery_finds_exactly_the_iterators_the_table_names", PARITY_GATES
      ),
      "defect": "an iterator is renamed without the table",
      "edits": [(FEEDS, ASYNC_ITER_HOME, ASYNC_ITER_HOME.replace("iter_home", "iter_timeline"))],
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
      timeout=GATE_TIMEOUT_SECONDS,
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
   log_path = LOG_DIR / f"mutation-iterators-{stamp}.json"
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
