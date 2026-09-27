"""Break E2 batch 11c, the viewer's saved posts, saved collections and close friends list, watch
each gate go red, restore.

Same harness and same rule as ``verify_account_gates.py``: one mutation per entry below, only the
gate that should catch it is run, every anchor must be found exactly once, and every file is
restored from an in-memory copy in a ``finally`` so an interrupted run cannot leave a mutation
behind.

The mutations cover the saved posts' mapping, the advertisement's absent fields, the more flag and
the refusal, the saved posts request and its spent bootstrap, the collections' kinds, counts,
covers and more flag, the saved tab's variables, the close friends list's choice by selected
state, its rows, each way a tree laid out otherwise must raise, the Bloks reader, the close
friends fetch and its refusals, the single fetch, both namespaces, the three commands, the
doctor's saved tab step and the namespace parity gates for the new methods.

Run from ``engine/`` with ``uv run python scripts/verify_own_account_more_gates.py``. Writes its
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

PARSE = "dumpstagram/_private/web/parse/account.py"
BLOKS = "dumpstagram/_private/web/parse/bloks.py"
REQUESTS = "dumpstagram/_private/web/requests/account.py"
CORE = "dumpstagram/_core/account.py"
NAMESPACE = "dumpstagram/namespaces/account.py"
RENDER = "dumpstagram/_cli/render/account.py"
CANARY = "dumpstagram/_private/web/canary.py"
GATES = "tests/test_own_account_more.py"
PARITY_GATES = "tests/test_facade_parity.py"
DOCTOR_GATES = "tests/test_doctor.py"


def gate(name: str) -> str:
   return f"{GATES}::{name}"


def layout(change: str) -> str:
   return gate(
      f"test_a_close_friends_tree_laid_out_otherwise_raises_rather_than_guessing[{change}]"
   )


def parity(name: str, qualified: str) -> str:
   return f"{PARITY_GATES}::{name}[{qualified}]"


SAVED_ITEMS = gate("test_every_saved_post_maps_in_order_with_no_comment_count_invented")
ADVERTISEMENT = gate("test_what_the_saved_advertisement_lacks_is_none_and_not_a_default")
SAVED_MORE = gate(
   "test_the_saved_posts_more_flag_is_more_available_and_a_refusal_is_not_an_empty_page"
)
SAVED_GET = gate("test_the_saved_posts_read_is_a_bare_get_with_the_follow_lists_headers")
SAVED_NO_BOOTSTRAP = gate("test_the_saved_posts_read_is_one_get_and_spends_no_bootstrap")
COLLECTIONS = gate("test_each_collection_maps_its_kind_count_and_covers")
OTHER_KIND = gate("test_a_collection_of_an_unread_type_is_other_and_the_more_flag_is_has_next_page")
TAB_VARIABLES = gate("test_the_saved_tab_read_sends_the_browsers_variables")
CLOSE_FRIENDS = gate("test_the_close_friends_are_the_list_whose_rows_start_selected")
BY_STRUCTURE = gate(
   "test_the_lists_are_found_by_structure_so_the_selected_state_decides_and_ids_do_not"
)
READER = gate("test_the_bloks_reader_keeps_strings_whole_and_refuses_what_is_not_its_grammar")
FETCH = gate("test_the_close_friends_fetch_is_the_settings_pages_app_fetch")
FETCH_REFUSED = gate("test_the_close_friends_fetch_is_refused_without_a_token_or_a_bloks_version")
ONE_FETCH = gate("test_the_close_friends_read_is_one_fetch_and_never_the_count_updater")
ASYNC_NAMESPACE = gate("test_the_async_namespace_sends_each_read_once_and_nothing_else")
BLOCKING_NAMESPACE = gate("test_the_blocking_namespace_sends_each_read_once_and_nothing_else")
DUMPSTA_SAVED = gate("test_dumpsta_saved_prints_every_post_and_whether_more_exist")
DUMPSTA_COLLECTIONS = gate(
   "test_dumpsta_collections_prints_each_collection_with_its_kind_and_count"
)
DUMPSTA_CLOSE_FRIENDS = gate("test_dumpsta_close_friends_prints_every_account_in_order")
DOCTOR_SAVED_TAB = (
   f"{DOCTOR_GATES}::test_the_saved_tab_step_of_batch_11c_replays_the_browsers_variables"
)
REACHES_CORE = "test_a_namespace_method_reaches_the_core_capability_the_table_names"

MUTATIONS: list[dict[str, object]] = [
   {
      "gate": SAVED_ITEMS,
      "defect": "a saved post's pk is read from its id",
      "edits": [
         (
            PARSE,
            'pk=_required_string(node, "pk", media_path),',
            'pk=_required_string(node, "id", media_path),',
         )
      ],
   },
   {
      "gate": SAVED_ITEMS,
      "defect": "the saved posts come back in reverse",
      "edits": [
         (
            PARSE,
            'posts = tuple(_saved_post(item, f"{_SAVED}.items[{index}]") for index, item in enumer'
            "ate(items))",
            'posts = tuple(_saved_post(item, f"{_SAVED}.items[{index}]") for index, item in enumer'
            "ate(items))[::-1]",
         )
      ],
   },
   {
      "gate": SAVED_ITEMS,
      "defect": "every saved post reads as liked",
      "edits": [
         (PARSE, 'has_liked=_required_flag(node, "has_liked", media_path),', "has_liked=True,")
      ],
   },
   {
      "gate": ADVERTISEMENT,
      "defect": "an absent counts flag reads as False",
      "edits": [
         (
            PARSE,
            "   if key not in node:\n      return None\n",
            "   if key not in node:\n      return False\n",
         )
      ],
   },
   {
      "gate": ADVERTISEMENT,
      "defect": "the REST keys left out are not read as null",
      "edits": [
         (
            PARSE,
            'node = _absent_as_null(_required(entry, "media", path))',
            'node = _required(entry, "media", path)',
         )
      ],
   },
   {
      "gate": SAVED_MORE,
      "defect": "the more flag is read from auto_load_more_enabled",
      "edits": [
         (
            PARSE,
            '_required_flag(payload, "more_available", _SAVED)',
            '_required_flag(payload, "auto_load_more_enabled", _SAVED)',
         )
      ],
   },
   {
      "gate": SAVED_MORE,
      "defect": "the saved posts' REST status is not read",
      "edits": [(PARSE, '   _raise_unless_ok(payload, "saved posts")\n', "")],
   },
   {
      "gate": SAVED_GET,
      "defect": "the saved posts carry the inbox as referer",
      "edits": [
         (
            REQUESTS,
            "      headers=_rest_read_headers(session, web_session_id, user_agent),",
            "      headers=_account_read_headers(session, web_session_id, user_agent),",
         )
      ],
   },
   {
      "gate": SAVED_GET,
      "defect": "the saved posts GET carries a page size",
      "edits": [
         (
            REQUESTS,
            "      headers=_rest_read_headers(session, web_session_id, user_agent),\n      params="
            "{},",
            "      headers=_rest_read_headers(session, web_session_id, user_agent),\n      params="
            '{"count": "12"},',
         )
      ],
   },
   {
      "gate": SAVED_NO_BOOTSTRAP,
      "defect": "the saved posts read spends a bootstrap",
      "edits": [
         (
            CORE,
            "   async def attempt() -> SavedPosts:\n",
            "   async def attempt() -> SavedPosts:\n      await bootstrap(sender, session, user_ag"
            "ent=user_agent)\n",
         )
      ],
   },
   {
      "gate": COLLECTIONS,
      "defect": "a collection's kind is read from its id",
      "edits": [
         (
            PARSE,
            'typename = _required_string(node, "__typename", path)',
            'typename = _required_string(node, "collection_id", path)',
         )
      ],
   },
   {
      "gate": COLLECTIONS,
      "defect": "the audio collection's null count reads as 0",
      "edits": [
         (
            PARSE,
            'media_count=_optional_integer(node, "collection_media_count", node_path),',
            'media_count=_optional_integer(node, "collection_media_count", node_path) or 0,',
         )
      ],
   },
   {
      "gate": COLLECTIONS,
      "defect": "the audio covers are dropped",
      "edits": [
         (
            PARSE,
            'audio_covers = _covers_of(node, "cover_audio_list", node_path)',
            "audio_covers: list[Any] = []",
         )
      ],
   },
   {
      "gate": COLLECTIONS,
      "defect": "a cover keeps only its first rendition",
      "edits": [
         (
            PARSE,
            "      for index, candidate in enumerate(candidates)",
            "      for index, candidate in enumerate(candidates[:1])",
         )
      ],
   },
   {
      "gate": OTHER_KIND,
      "defect": "a collection of an unread type is refused",
      "edits": [
         (PARSE, "return known.get(typename, SavedCollectionKind.OTHER)", "return known[typename]")
      ],
   },
   {
      "gate": OTHER_KIND,
      "defect": "the collections' more flag is a constant",
      "edits": [
         (
            PARSE,
            'has_more=_required_flag(page_info, "has_next_page", f"{connection_path}.page_info"),',
            "has_more=False,",
         )
      ],
   },
   {
      "gate": TAB_VARIABLES,
      "defect": "the collection types go in another order",
      "edits": [
         (
            REQUESTS,
            'SAVED_COLLECTION_TYPES = ("ALL_MEDIA_AUTO_COLLECTION", "MEDIA", "AUDIO_AUTO_COLLECTIO'
            'N")',
            'SAVED_COLLECTION_TYPES = ("MEDIA", "ALL_MEDIA_AUTO_COLLECTION", "AUDIO_AUTO_COLLECTIO'
            'N")',
         )
      ],
   },
   {
      "gate": TAB_VARIABLES,
      "defect": "the saved tab asks for another page size",
      "edits": [(REQUESTS, "SAVED_COLLECTIONS_PAGE_SIZE = 12", "SAVED_COLLECTIONS_PAGE_SIZE = 24")],
   },
   {
      "gate": CLOSE_FRIENDS,
      "defect": "the list whose rows start unselected is returned",
      "edits": [(PARSE, "      if starts_selected:\n", "      if not starts_selected:\n")],
   },
   {
      "gate": CLOSE_FRIENDS,
      "defect": "the full name is read from the username",
      "edits": [
         (
            PARSE,
            'full_name=_row_string(fields, "name", path),',
            'full_name=_row_string(fields, "username", path),',
         )
      ],
   },
   {
      "gate": CLOSE_FRIENDS,
      "defect": "the verified badge is inverted",
      "edits": [(PARSE, 'is_verified=verified == "true",', 'is_verified=verified == "false",')],
   },
   {
      "gate": BY_STRUCTURE,
      "defect": "the first list mapped is taken whatever state its rows start in",
      "edits": [(PARSE, "      if starts_selected:\n", "      if list_count == 1:\n")],
   },
   {
      "gate": layout("both lists selected"),
      "defect": "two selected lists are accepted",
      "edits": [
         (
            PARSE,
            "is_one_selected_list_of_two = list_count == 2 and len(selected_lists) == 1",
            "is_one_selected_list_of_two = list_count == 2 and len(selected_lists) >= 1",
         )
      ],
   },
   {
      "gate": layout("neither list selected"),
      "defect": "a tree with no selected list is not refused before it is read",
      "edits": [
         (
            PARSE,
            "is_one_selected_list_of_two = list_count == 2 and len(selected_lists) == 1",
            "is_one_selected_list_of_two = list_count == 2",
         )
      ],
   },
   {
      "gate": layout("a selected state that is not a constant"),
      "defect": "a selected state that is not a constant reads as selected",
      "edits": [
         (
            PARSE,
            '   if flag not in ("true", "false"):\n      raise _bloks_schema_changed("is not a con'
            'stant boolean", path)\n\n   return flag == "true"',
            '   return flag != "false"',
         )
      ],
   },
   {
      "gate": layout("a row without its username"),
      "defect": "a row whose keys and values do not pair is read",
      "edits": [
         (
            PARSE,
            "is_well_formed = len(names) == len(keys.arguments) == len(values.arguments)",
            "is_well_formed = True",
         )
      ],
   },
   {
      "gate": layout("an id that is not a number"),
      "defect": "an id of letters is accepted",
      "edits": [
         (
            PARSE,
            "is_a_real_id = user_id is not None and user_id.isdigit()",
            "is_a_real_id = user_id is not None",
         )
      ],
   },
   {
      "gate": layout("a list that is not an array"),
      "defect": "a list that is not an array is read as rows",
      "edits": [
         (
            PARSE,
            '   if rows is None:\n      raise _bloks_schema_changed("is not an array of rows", lis'
            "t_path)\n",
            "",
         )
      ],
   },
   {
      "gate": READER,
      "defect": "an unclosed script is read as far as it goes",
      "edits": [
         (BLOKS, "   return stack[0][0]", "   return (stack[0] or stack[-1])[0]"),
         (BLOKS, "   if not is_one_complete_value:\n      raise _unexpected(path, position)\n", ""),
      ],
   },
   {
      "gate": READER,
      "defect": "a parenthesis or a comma ends a string",
      "edits": [
         (BLOKS, """r'|(?P<string>"(?:[^"\\\\]|\\\\.)*")""", """r'|(?P<string>"[^"(),]*")""")
      ],
   },
   {
      "gate": READER,
      "defect": "a string's escapes are left undecoded",
      "edits": [(BLOKS, "      value = json.loads(literal)", "      value = literal[1:-1]")],
   },
   {
      "gate": FETCH,
      "defect": "the fetch names no Bloks version",
      "edits": [(REQUESTS, ', "__bkv": bloks_version})', "})")],
   },
   {
      "gate": FETCH,
      "defect": "the fetch sends params other than an empty object",
      "edits": [(REQUESTS, '      "params": "{}",', '      "params": "[]",')],
   },
   {
      "gate": FETCH,
      "defect": "the fetch carries a csrf header the page's did not",
      "edits": [
         (
            REQUESTS,
            '      "referer": CLOSE_FRIENDS_PAGE,\n',
            '      "referer": CLOSE_FRIENDS_PAGE,\n      "x-csrftoken": session.csrftoken,\n',
         )
      ],
   },
   {
      "gate": FETCH,
      "defect": "the fetch names another route",
      "edits": [
         (
            REQUESTS,
            '      "__crn": _CLOSE_FRIENDS_ROUTE,',
            '      "__crn": "comet.igweb.PolarisSettingsRoute",',
         )
      ],
   },
   {
      "gate": FETCH_REFUSED,
      "defect": "the fetch is built without a Bloks version",
      "edits": [
         (
            REQUESTS,
            "   if not bloks_version:\n",
            "   if bloks_version is None and bloks_version:\n",
         )
      ],
   },
   {
      "gate": ONE_FETCH,
      "defect": "the fetch is sent twice, as the page sends it",
      "edits": [
         (
            CORE,
            "      response = await sender.send(request)\n\n      return parse_close_friends(",
            "      await sender.send(request)\n      response = await sender.send(request)\n\n    "
            "  return parse_close_friends(",
         )
      ],
   },
   {
      "gate": ASYNC_NAMESPACE,
      "defect": "close_friends reaches the saved tab's core function",
      "edits": [
         (NAMESPACE, "         read_close_friends(\n", "         read_saved_collections(\n")
      ],
   },
   {
      "gate": BLOCKING_NAMESPACE,
      "defect": "the blocking saved runs the collections read",
      "edits": [
         (
            NAMESPACE,
            "         self._client._impl.account.saved(),",
            "         self._client._impl.account.collections(),",
         )
      ],
   },
   {
      "gate": DUMPSTA_SAVED,
      "defect": "the saved JSON inverts the more flag",
      "edits": [
         (
            RENDER,
            '"post_count": len(saved.posts),\n      "more_available": saved.has_more,',
            '"post_count": len(saved.posts),\n      "more_available": not saved.has_more,',
         )
      ],
   },
   {
      "gate": DUMPSTA_SAVED,
      "defect": "the saved text form leaves out the first post",
      "edits": [(RENDER, "   for post in saved.posts:\n", "   for post in saved.posts[1:]:\n")],
   },
   {
      "gate": DUMPSTA_COLLECTIONS,
      "defect": "the collections JSON names the collection instead of its kind",
      "edits": [
         (
            RENDER,
            '            "kind": collection.kind.name.lower(),',
            '            "kind": collection.name,',
         )
      ],
   },
   {
      "gate": DUMPSTA_CLOSE_FRIENDS,
      "defect": "the close friends text form leaves out the first account",
      "edits": [
         (
            RENDER,
            'f"{account.id}  {account.username}  {account.full_name}".rstrip() for account in acco'
            "unts\n",
            'f"{account.id}  {account.username}  {account.full_name}".rstrip() for account in acco'
            "unts[1:]\n",
         )
      ],
   },
   {
      "gate": DOCTOR_SAVED_TAB,
      "defect": "the canary reads the saved tab with the saved posts' mapper",
      "edits": [
         (
            CANARY,
            "      read=_mapped_by(parse_saved_collections),",
            "      read=_mapped_by(parse_saved_posts),",
         ),
         (
            CANARY,
            "from dumpstagram._private.web.parse.account import parse_saved_collections\n",
            "from dumpstagram._private.web.parse.account import parse_saved_collections, parse_sav"
            "ed_posts\n",
         ),
      ],
   },
   {
      "gate": parity(REACHES_CORE, "account.saved"),
      "defect": "saved reaches the collections' core function",
      "edits": [(NAMESPACE, "         read_saved_posts(\n", "         read_saved_collections(\n")],
   },
   {
      "gate": parity(REACHES_CORE, "account.collections"),
      "defect": "collections reaches the saved posts' core function",
      "edits": [
         (
            NAMESPACE,
            "         read_saved_collections(\n            client._sender,",
            "         read_saved_posts(\n            client._sender,",
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
   log_path = LOG_DIR / f"mutation-own-account-more-{stamp}.json"
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
