"""Break the facades, watch each parity gate go red, restore.

Same harness and same rule as ``verify_feed_gates.py``: one mutation per gate, only the gate
that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

Two of the mutations are the drifts the parity file exists for: a capability added to
``AsyncClient``, with the snapshot updated to match, and no facade method behind it, and a
facade method that grows a parameter its async twin does not take. The gates name no
capability, so neither mutation touches anything they were written against.

Run from ``engine/`` with ``uv run python scripts/verify_parity_gates.py``. Writes its result
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

CLIENT = "dumpstagram/client.py"
AIO = "dumpstagram/aio.py"
SNAPSHOT = "tests/public_surface.txt"
PARITY = "tests/test_facade_parity.py"

FORWARDS_THE_CURSOR = """         self._impl.thread_messages(
            thread_fbid,
            after=after,
            newer_than_message_id=newer_than_message_id,
         ),"""

DROPS_THE_CURSOR = """         self._impl.thread_messages(
            thread_fbid,
            newer_than_message_id=newer_than_message_id,
         ),"""

SWAPS_THE_CURSORS = """         self._impl.thread_messages(
            thread_fbid,
            after=newer_than_message_id,
            newer_than_message_id=after,
         ),"""

FEED_ON_THE_LOOP_THREAD = """      return self._loop.run(
         self._impl.feed(after=after),
         operation="SyncClient.feed",
      )"""

FEED_ON_A_LOOP_OF_ITS_OWN = """      import asyncio

      return asyncio.new_event_loop().run_until_complete(self._impl.feed(after=after))"""

PROFILE_BY_ID_NAMES_ITSELF = """         self._impl.profile_by_id(user_id),
         operation="SyncClient.profile_by_id","""

PROFILE_BY_ID_COPIED_FROM_PROFILE = """         self._impl.profile_by_id(user_id),
         operation="SyncClient.profile","""

FEED_TAKES_A_CURSOR = """   def feed(self, *, after: str | None = None) -> Page[FeedItem]:
      \"\"\"Read one page of the home timeline. Blocks until it has one."""

FEED_TAKES_A_CURSOR_AND_A_LIMIT = (
   "   def feed(self, *, after: str | None = None, limit: int = 12) -> Page[FeedItem]:\n"
   '      """Read one page of the home timeline. Blocks until it has one.'
)

FEED_IS_BLOCKING = """   def feed(self, *, after: str | None = None) -> Page[FeedItem]:"""

FEED_IS_A_COROUTINE = """   async def feed(self, *, after: str | None = None) -> Page[FeedItem]:"""

PROFILE_RETURNS_A_PROFILE = """   def profile(self, username: str) -> Profile:
      \"\"\"Read one account's profile by username. Blocks until it has one."""

PROFILE_RETURNS_ANYTHING = (
   "   def profile(self, username: str) -> object:\n"
   '      """Read one account\'s profile by username. Blocks until it has one.'
)

ASYNC_SURFACE_ENDS_WITH_FEED = """   def _refuse_when_closed(self) -> None:"""

ASYNC_SURFACE_GROWS_A_CAPABILITY = (
   "   async def saved_posts(self, *, after: str | None = None) -> Page[FeedItem]:\n"
   "      return await self.feed(after=after)\n"
   "\n"
   "   def _refuse_when_closed(self) -> None:"
)

SNAPSHOT_WITHOUT_SAVED_POSTS = (
   """def dumpstagram.aio.AsyncClient.profile(self, username: str) -> Profile"""
)

SNAPSHOT_WITH_SAVED_POSTS = (
   "def dumpstagram.aio.AsyncClient.profile(self, username: str) -> Profile\n"
   "def dumpstagram.aio.AsyncClient.saved_posts("
   "self, *, after: str | None = None) -> Page[FeedItem]"
)

DISCOVERY_READS_COROUTINES = """      is_awaitable = inspect.iscoroutinefunction(member)"""

DISCOVERY_FINDS_NOTHING = """      is_awaitable = inspect.isgeneratorfunction(member)"""

SESSION_IS_A_PROPERTY = """   @property
   def session(self) -> Session:
      \"\"\"The session this client was built with, which the caller still owns.\"\"\"

      return self._impl.session"""

SESSION_IS_A_METHOD = """   def session(self) -> Session:
      \"\"\"The session this client was built with, which the caller still owns.\"\"\"

      return self._impl.session"""

WITH_BEHAVIOR_SIGNATURE = """   def with_behavior(self, behavior: Behavior) -> SyncClient:"""

WITH_BEHAVIOR_GROWS_A_PARAMETER = (
   "   def with_behavior(\n"
   "      self, behavior: Behavior, *, user_agent: str | None = None\n"
   "   ) -> SyncClient:"
)

WITH_BEHAVIOR_ANNOTATED_ASYNC = """   def with_behavior(self, behavior: Behavior) -> AsyncClient:"""

WITH_BEHAVIOR_RETURNS_A_BLOCKING_CLIENT = """      scoped._closed = False

      return scoped
"""

WITH_BEHAVIOR_RETURNS_THE_ASYNC_CLIENT = """      scoped._closed = False

      return scoped_impl  # type: ignore[return-value]
"""

SCOPING_GATE = (
   f"{PARITY}::test_a_scoping_method_takes_the_same_parameters_and_returns_its_own_surface"
)

MUTATIONS: list[dict[str, object]] = [
   {
      "gate": f"{PARITY}::test_a_blocking_capability_forwards_every_argument_on_the_loop_thread",
      "defect": "a facade accepts a cursor and never passes it on",
      "edits": [(CLIENT, FORWARDS_THE_CURSOR, DROPS_THE_CURSOR)],
   },
   {
      "gate": f"{PARITY}::test_a_blocking_capability_forwards_every_argument_on_the_loop_thread",
      "defect": "a facade passes two arguments of the same type to each other's parameters",
      "edits": [(CLIENT, FORWARDS_THE_CURSOR, SWAPS_THE_CURSORS)],
   },
   {
      "gate": f"{PARITY}::test_a_blocking_capability_forwards_every_argument_on_the_loop_thread",
      "defect": "a facade runs its coroutine on a private loop rather than the shared thread",
      "edits": [(CLIENT, FEED_ON_THE_LOOP_THREAD, FEED_ON_A_LOOP_OF_ITS_OWN)],
   },
   {
      "gate": (
         f"{PARITY}::test_a_blocking_capability_raises_the_async_exception_under_its_own_name"
      ),
      "defect": "a facade method copied from its neighbour keeps the neighbour's seam label",
      "edits": [(CLIENT, PROFILE_BY_ID_NAMES_ITSELF, PROFILE_BY_ID_COPIED_FROM_PROFILE)],
   },
   {
      "gate": f"{PARITY}::test_a_capability_takes_the_same_parameters_and_returns_the_same_type",
      "defect": "one surface grows a parameter the other does not accept",
      "edits": [(CLIENT, FEED_TAKES_A_CURSOR, FEED_TAKES_A_CURSOR_AND_A_LIMIT)],
   },
   {
      "gate": f"{PARITY}::test_a_capability_takes_the_same_parameters_and_returns_the_same_type",
      "defect": "one surface returns a different type for the same capability",
      "edits": [(CLIENT, PROFILE_RETURNS_A_PROFILE, PROFILE_RETURNS_ANYTHING)],
   },
   {
      "gate": f"{PARITY}::test_a_blocking_capability_is_not_a_coroutine",
      "defect": "a facade method is declared async and hands a sync caller a coroutine",
      "edits": [(CLIENT, FEED_IS_BLOCKING, FEED_IS_A_COROUTINE)],
   },
   {
      "gate": f"{PARITY}::test_a_shared_name_is_the_same_kind_of_member_on_both_surfaces",
      "defect": "a property on one surface is a method on the other",
      "edits": [(CLIENT, SESSION_IS_A_PROPERTY, SESSION_IS_A_METHOD)],
   },
   {
      "gate": f"{PARITY}::test_both_surfaces_expose_the_same_public_names",
      "defect": "a capability lands on the async surface with no facade method, snapshot updated",
      "edits": [
         (AIO, ASYNC_SURFACE_ENDS_WITH_FEED, ASYNC_SURFACE_GROWS_A_CAPABILITY),
         (SNAPSHOT, SNAPSHOT_WITHOUT_SAVED_POSTS, SNAPSHOT_WITH_SAVED_POSTS),
      ],
   },
   {
      "gate": SCOPING_GATE,
      "defect": "the blocking scoping method grows a parameter its async twin does not take",
      "edits": [(CLIENT, WITH_BEHAVIOR_SIGNATURE, WITH_BEHAVIOR_GROWS_A_PARAMETER)],
   },
   {
      "gate": SCOPING_GATE,
      "defect": "the blocking scoping method is annotated as returning the async client",
      "edits": [(CLIENT, WITH_BEHAVIOR_SIGNATURE, WITH_BEHAVIOR_ANNOTATED_ASYNC)],
   },
   {
      "gate": SCOPING_GATE,
      "defect": "the blocking scoping method hands its caller the async client it wraps",
      "edits": [
         (CLIENT, WITH_BEHAVIOR_RETURNS_A_BLOCKING_CLIENT, WITH_BEHAVIOR_RETURNS_THE_ASYNC_CLIENT)
      ],
   },
   {
      "gate": f"{PARITY}::test_discovery_finds_every_capability_the_snapshot_lists",
      "defect": "the discovery rule finds nothing, so every parametrised gate runs zero cases",
      "edits": [(PARITY, DISCOVERY_READS_COROUTINES, DISCOVERY_FINDS_NOTHING)],
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

         if find not in current:
            raise SystemExit(f"mutation anchor not found in {relative} for {gate}")

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

   every_gate_fired = all(
      entry["red_under_mutation"] and entry["green_after_restore"] for entry in results
   )

   LOG_DIR.mkdir(parents=True, exist_ok=True)
   stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
   log_path = LOG_DIR / f"mutation-parity-{stamp}.json"
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
