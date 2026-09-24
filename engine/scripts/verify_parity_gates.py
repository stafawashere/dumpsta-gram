"""Break the facades, watch each parity gate go red, restore.

Same harness and same rule as ``verify_feed_gates.py``: one mutation per gate, only the gate
that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

Two of the mutations are the drifts the parity file exists for: a capability added to
``AsyncClient``, with the snapshot updated to match, and no facade method behind it, and a
facade method that grows a parameter its async twin does not take. The gates name no
capability, so neither mutation touches anything they were written against.

Since E1 item 4 the harness also breaks the domain namespaces: an alias missing from the
blocking namespace, one with another signature or declared async, one that drops an argument or
keeps its flat twin's seam label, a blocking client handing out the async namespace, an alias
or a flat method reaching the wrong capability, and the two discovery controls.

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
DIRECT_NAMESPACE = "dumpstagram/namespaces/direct.py"
FEEDS_NAMESPACE = "dumpstagram/namespaces/feeds.py"
MEDIA_NAMESPACE = "dumpstagram/namespaces/media.py"

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

SYNC_UNLIKE_IS_PUBLIC = "   def unlike(self, post_pk: str) -> None:"

SYNC_UNLIKE_IS_GONE = "   def _unlike(self, post_pk: str) -> None:"

SYNC_MESSAGES_SIGNATURE = "   def messages(\n      self,\n      thread_fbid: str,\n"

SYNC_MESSAGES_GROWS_A_PARAMETER = (
   "   def messages(\n      self,\n      thread_fbid: str,\n      limit: int = 20,\n"
)

SYNC_HOME_IS_BLOCKING = "   def home(self, *, after: str | None = None) -> Page[FeedItem]:"

SYNC_HOME_IS_A_COROUTINE = "   async def home(self, *, after: str | None = None) -> Page[FeedItem]:"

SYNC_COMMENTS_FORWARDS_THE_CURSOR = (
   "         self._client._impl.media.comments(post_pk, after=after),"
)

SYNC_COMMENTS_DROPS_THE_CURSOR = "         self._client._impl.media.comments(post_pk),"

SYNC_SEND_NAMES_ITSELF = 'operation="SyncClient.direct.send",'

SYNC_SEND_NAMES_ITS_FLAT_TWIN = 'operation="SyncClient.send_message",'

SYNC_MEDIA_IS_ITS_OWN = "      return SyncMedia._of(self)\n"

SYNC_MEDIA_IS_THE_ASYNC_ONE = "      return self._impl.media  # type: ignore[return-value]\n"

UNLIKE_ALIAS_REACHES_UNLIKE = "         unlike_post(\n"

UNLIKE_ALIAS_REACHES_LIKE = "         like_post(\n"

FLAT_UNLIKE_ANSWERS_THROUGH_UNLIKE = "      await self.media.unlike(post_pk)\n"

FLAT_UNLIKE_ANSWERS_THROUGH_LIKE = "      await self.media.like(post_pk)\n"

FLAT_COMMENTS_FORWARDS_THE_CURSOR = "      return await self.media.comments(post_pk, after=after)\n"

FLAT_COMMENTS_DROPS_THE_CURSOR = "      return await self.media.comments(post_pk)\n"

SYNC_SET_NOTE_FORWARDS_THE_AUDIENCE = (
   "         self._client._impl.direct.set_note(text, audience=audience),"
)

SYNC_SET_NOTE_DROPS_THE_AUDIENCE = "         self._client._impl.direct.set_note(text),"

NAMESPACE_DISCOVERY_READS_THE_PACKAGE = (
   '      is_a_namespace = is_a_class and returns.__module__.startswith(f"{NAMESPACE_PACKAGE}.")'
)

NAMESPACE_DISCOVERY_FINDS_NOTHING = (
   '      is_a_namespace = is_a_class and returns.__module__.startswith("dumpstagram.nowhere.")'
)

NAMESPACE_SIGNATURE_GATE = (
   f"{PARITY}::test_a_namespace_method_takes_the_same_parameters_and_returns_the_same_type"
)

ASYNC_ALIAS_GATE = (
   f"{PARITY}::test_a_flat_method_and_its_alias_send_the_same_requests_and_answer_alike_async"
)

CORE_REACH_GATE = f"{PARITY}::test_a_namespace_method_reaches_the_core_capability_the_table_names"

UNFOLLOW_IS_IN_THE_CORE_TABLE = (
   '   "social.unfollow": "dumpstagram._core.writes.follows.unfollow_user",\n'
)

BLOCKING_ALIAS_GATE = (
   f"{PARITY}::test_a_flat_method_and_its_alias_send_the_same_requests_and_answer_alike_blocking"
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
   {
      "gate": f"{PARITY}::test_both_surfaces_carry_the_same_namespaces_with_the_same_methods",
      "defect": "an alias exists on the async namespace and is missing from the blocking one",
      "edits": [(MEDIA_NAMESPACE, SYNC_UNLIKE_IS_PUBLIC, SYNC_UNLIKE_IS_GONE)],
   },
   {
      "gate": NAMESPACE_SIGNATURE_GATE,
      "defect": "a blocking alias grows a parameter its async twin does not take",
      "edits": [(DIRECT_NAMESPACE, SYNC_MESSAGES_SIGNATURE, SYNC_MESSAGES_GROWS_A_PARAMETER)],
   },
   {
      "gate": NAMESPACE_SIGNATURE_GATE,
      "defect": "a blocking alias is declared async and hands a sync caller a coroutine",
      "edits": [(FEEDS_NAMESPACE, SYNC_HOME_IS_BLOCKING, SYNC_HOME_IS_A_COROUTINE)],
   },
   {
      "gate": (
         f"{PARITY}::test_a_blocking_namespace_method_forwards_every_argument_on_the_loop_thread"
      ),
      "defect": "a blocking alias accepts a cursor and never passes it on",
      "edits": [
         (MEDIA_NAMESPACE, SYNC_COMMENTS_FORWARDS_THE_CURSOR, SYNC_COMMENTS_DROPS_THE_CURSOR)
      ],
   },
   {
      "gate": (
         f"{PARITY}::test_a_blocking_namespace_method_raises_the_async_exception_under_its_own_name"
      ),
      "defect": "a blocking alias keeps the seam label of the flat method it was copied from",
      "edits": [(DIRECT_NAMESPACE, SYNC_SEND_NAMES_ITSELF, SYNC_SEND_NAMES_ITS_FLAT_TWIN)],
   },
   {
      "gate": f"{PARITY}::test_each_surface_hands_out_its_own_namespaces",
      "defect": "the blocking client hands its caller the async namespace it wraps",
      "edits": [(CLIENT, SYNC_MEDIA_IS_ITS_OWN, SYNC_MEDIA_IS_THE_ASYNC_ONE)],
   },
   {
      "gate": CORE_REACH_GATE,
      "defect": "an alias delegates to another capability's core function",
      "edits": [(MEDIA_NAMESPACE, UNLIKE_ALIAS_REACHES_UNLIKE, UNLIKE_ALIAS_REACHES_LIKE)],
   },
   {
      "gate": f"{PARITY}::test_every_namespace_method_names_the_core_capability_it_reaches",
      "defect": "a namespace method is left out of the core capability table",
      "edits": [(PARITY, UNFOLLOW_IS_IN_THE_CORE_TABLE, "")],
   },
   {
      "gate": ASYNC_ALIAS_GATE,
      "defect": "a flat method answers through the wrong alias",
      "edits": [(AIO, FLAT_UNLIKE_ANSWERS_THROUGH_UNLIKE, FLAT_UNLIKE_ANSWERS_THROUGH_LIKE)],
   },
   {
      "gate": ASYNC_ALIAS_GATE,
      "defect": "a flat method drops an argument on the way to its alias",
      "edits": [(AIO, FLAT_COMMENTS_FORWARDS_THE_CURSOR, FLAT_COMMENTS_DROPS_THE_CURSOR)],
   },
   {
      "gate": BLOCKING_ALIAS_GATE,
      "defect": "a blocking alias drops a keyword and the default goes out in its place",
      "edits": [
         (DIRECT_NAMESPACE, SYNC_SET_NOTE_FORWARDS_THE_AUDIENCE, SYNC_SET_NOTE_DROPS_THE_AUDIENCE)
      ],
   },
   {
      "gate": f"{PARITY}::test_namespace_discovery_finds_every_namespace_method_the_snapshot_lists",
      "defect": "namespace discovery finds nothing, so every namespace gate runs zero cases",
      "edits": [(PARITY, NAMESPACE_DISCOVERY_READS_THE_PACKAGE, NAMESPACE_DISCOVERY_FINDS_NOTHING)],
   },
   {
      "gate": f"{PARITY}::test_every_flat_capability_has_exactly_one_namespace_alias",
      "defect": "a flat capability lands with no namespace alias, snapshot updated",
      "edits": [
         (AIO, ASYNC_SURFACE_ENDS_WITH_FEED, ASYNC_SURFACE_GROWS_A_CAPABILITY),
         (SNAPSHOT, SNAPSHOT_WITHOUT_SAVED_POSTS, SNAPSHOT_WITH_SAVED_POSTS),
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
