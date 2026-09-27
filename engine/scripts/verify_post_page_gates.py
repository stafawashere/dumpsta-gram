"""Break E2 batch 11d, the blocked accounts list and the post page load, watch each gate go red,
restore.

Same harness and same rule as ``verify_own_account_more_gates.py``: one mutation per entry below,
only the gate that should catch it is run, every anchor must be found exactly once, and every file
is restored from an in-memory copy in a ``finally`` so an interrupted run cannot leave a mutation
behind.

The mutations cover the blocked rows' mapping and flags, the screen line kept as text, both Bloks
fetches, each way a screen or list laid out otherwise must raise, the action built from the
screen's ids in one read, the post page's burst, its referer and device id, the post read out of
the document, each part of the page read from its own preload, the cookie sync tail after a load
and never after a failed one, the default route and its departure, both namespaces, the two
commands and the namespace parity gates for the two new methods.

Run from ``engine/`` with ``uv run python scripts/verify_post_page_gates.py``. Writes its result
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

ACCOUNT_PARSE = "dumpstagram/_private/web/parse/account.py"
ACCOUNT_REQUESTS = "dumpstagram/_private/web/requests/account.py"
ACCOUNT_CORE = "dumpstagram/_core/account.py"
ACCOUNT_MODELS = "dumpstagram/models/account.py"
ACCOUNT_NAMESPACE = "dumpstagram/namespaces/account.py"
ACCOUNT_RENDER = "dumpstagram/_cli/render/account.py"
POSTS_CORE = "dumpstagram/_core/posts.py"
PAGE_LOAD = "dumpstagram/_private/web/requests/page_load.py"
MEDIA_NAMESPACE = "dumpstagram/namespaces/media.py"
BEHAVIOR = "dumpstagram/behavior.py"
POST_DEPTH_RENDER = "dumpstagram/_cli/render/post_depth.py"
GATES = "tests/test_post_page.py"
PARITY_GATES = "tests/test_facade_parity.py"


def gate(name: str) -> str:
   return f"{GATES}::{name}"


def layout(change: str) -> str:
   return gate(f"test_a_blocked_list_laid_out_otherwise_raises_rather_than_guessing[{change}]")


def parity(name: str, qualified: str) -> str:
   return f"{PARITY_GATES}::{name}[{qualified}]"


ROWS = gate("test_the_blocked_accounts_are_the_reloaders_rows_in_order_with_both_flags")
SCREEN_LINE = gate("test_the_screen_line_of_an_automatic_row_is_kept_as_text_and_not_as_a_name")
FETCHES = gate("test_the_blocked_fetches_are_the_settings_pages_two_fetches")
ONE_ACTION = gate("test_the_blocked_read_is_the_screen_then_its_reloader_and_never_an_unblock")
BURST = gate("test_a_post_page_load_sends_the_recorded_burst_in_its_groups")
REFERER = gate("test_every_companion_names_the_post_page_and_the_documents_device_id")
POST_FROM_DOCUMENT = gate("test_by_code_on_the_page_reads_the_post_out_of_the_document")
PAGE_PARTS = gate("test_the_page_reads_each_part_out_of_its_own_preload")
MISSING = gate("test_a_page_missing_a_preload_raises_and_schedules_no_tail")
TAIL = gate("test_a_page_load_schedules_the_cookie_sync_tail_for_the_post_page")
DEFAULT_ROUTE = gate(
   "test_by_code_loads_the_page_by_default_and_the_departure_sends_the_query_alone"
)
ASYNC_NAMESPACE = gate(
   "test_the_async_namespace_page_and_blocked_send_their_reads_and_nothing_else"
)
BLOCKING_NAMESPACE = gate("test_the_blocking_namespace_page_and_blocked_answer_as_their_twins")
DUMPSTA_BLOCKED = gate("test_dumpsta_blocked_prints_every_account_in_order_with_its_flag")
DUMPSTA_POST_PAGE = gate("test_dumpsta_post_page_prints_the_post_its_comments_and_the_grid")
REACHES_CORE = "test_a_namespace_method_reaches_the_core_capability_the_table_names"

MUTATIONS: list[dict[str, object]] = [
   {
      "gate": ROWS,
      "defect": "the secondary text is read from the username",
      "edits": [
         (
            ACCOUNT_PARSE,
            'secondary_text=_row_string(fields, "secondary_text", path),',
            'secondary_text=_row_string(fields, "username", path),',
         )
      ],
   },
   {
      "gate": ROWS,
      "defect": "the automatic flag is inverted",
      "edits": [
         (
            ACCOUNT_PARSE,
            'is_auto_blocked=_row_flag(fields, "is_auto_blocked", path),',
            'is_auto_blocked=not _row_flag(fields, "is_auto_blocked", path),',
         )
      ],
   },
   {
      "gate": ROWS,
      "defect": "the verified badge is read from the automatic flag",
      "edits": [
         (
            ACCOUNT_PARSE,
            'is_verified=_row_flag(fields, "is_verified", path),\n      profile_pic_url',
            'is_verified=_row_flag(fields, "is_auto_blocked", path),\n      profile_pic_url',
         )
      ],
   },
   {
      "gate": ROWS,
      "defect": "the rows come back in reverse",
      "edits": [
         (
            ACCOUNT_PARSE,
            '_blocked_account(row, f"{list_path}[{index}]") for index, row in enumerate(rows.argu'
            "ments)",
            '_blocked_account(row, f"{list_path}[{index}]") for index, row in enumerate(rows.argu'
            "ments[::-1])",
         )
      ],
   },
   {
      "gate": SCREEN_LINE,
      "defect": "the model grows a full name",
      "edits": [
         (
            ACCOUNT_MODELS,
            "   profile_pic_url: str\n   is_auto_blocked: bool\n",
            '   profile_pic_url: str\n   is_auto_blocked: bool\n   full_name: str = ""\n',
         )
      ],
   },
   {
      "gate": FETCHES,
      "defect": "the screen sends params other than an empty object",
      "edits": [
         (
            ACCOUNT_REQUESTS,
            '      params="{}",\n      route=_BLOCKED_ACCOUNTS_ROUTE,',
            '      params="[]",\n      route=_BLOCKED_ACCOUNTS_ROUTE,',
         )
      ],
   },
   {
      "gate": FETCHES,
      "defect": "the action's two ids are swapped",
      "edits": [
         (
            ACCOUNT_REQUESTS,
            '"container_id_of_list": list_id,\n         "container_id_of_rows": rows_id,',
            '"container_id_of_list": rows_id,\n         "container_id_of_rows": list_id,',
         )
      ],
   },
   {
      "gate": FETCHES,
      "defect": "the reloader is fetched as an app",
      "edits": [(ACCOUNT_REQUESTS, '      kind="action",', '      kind="app",')],
   },
   {
      "gate": FETCHES,
      "defect": "both fetches name another route",
      "edits": [
         (
            ACCOUNT_REQUESTS,
            '_BLOCKED_ACCOUNTS_ROUTE = "comet.igweb.PolarisBlockedAccountsSettingsRoute"',
            '_BLOCKED_ACCOUNTS_ROUTE = "comet.igweb.PolarisSettingsRoute"',
         )
      ],
   },
   {
      "gate": FETCHES,
      "defect": "both fetches claim the page that answered the error route",
      "edits": [
         (
            ACCOUNT_REQUESTS,
            'BLOCKED_ACCOUNTS_PAGE = f"{ORIGIN}/accounts/blocked_accounts/"',
            'BLOCKED_ACCOUNTS_PAGE = f"{ORIGIN}/accounts/blocked/"',
         )
      ],
   },
   {
      "gate": layout("a screen that names no reloader"),
      "defect": "a screen naming no reloader is not refused before it is read",
      "edits": [(ACCOUNT_PARSE, "   if len(found) != 1:\n", "   if len(found) > 1:\n")],
   },
   {
      "gate": layout("a screen that names it twice"),
      "defect": "the first of two reloader calls is taken",
      "edits": [(ACCOUNT_PARSE, "   if len(found) != 1:\n", "   if not found:\n")],
   },
   {
      "gate": layout("two data entries"),
      "defect": "a list answer with two data entries is not refused before it is read",
      "edits": [
         (
            ACCOUNT_PARSE,
            "is_the_layout_read = len(variables) == 1 and len(embedded) == 1",
            "is_the_layout_read = len(variables) >= 1 and len(embedded) == 1",
         )
      ],
   },
   {
      "gate": layout("no embedded payload"),
      "defect": "a list answer with no embedded payload is accepted",
      "edits": [
         (
            ACCOUNT_PARSE,
            "is_the_layout_read = len(variables) == 1 and len(embedded) == 1",
            "is_the_layout_read = len(variables) == 1",
         )
      ],
   },
   {
      "gate": layout("another container replaced"),
      "defect": "an answer for another container is accepted",
      "edits": [
         (ACCOUNT_PARSE, "   if replaced != containers.list_id:\n", "   if replaced is None:\n")
      ],
   },
   {
      "gate": layout("the keys in another order"),
      "defect": "a row whose keys come in another order is read by position",
      "edits": [
         (
            ACCOUNT_PARSE,
            "is_the_row_read = keys is not None and keys.arguments == _BLOCKED_ROW_KEYS",
            "is_the_row_read = keys is not None",
         ),
         (
            ACCOUNT_PARSE,
            '   fields = _row_fields(row, path)\n   user_id = _row_string(fields, "user_id", path)',
            "   fields = dict(zip(_BLOCKED_ROW_KEYS, _row_fields(row, path).values(), strict=True))"
            '\n   user_id = _row_string(fields, "user_id", path)',
         ),
      ],
   },
   {
      "gate": layout("an id that is not a number"),
      "defect": "an id of letters is accepted",
      "edits": [(ACCOUNT_PARSE, "   if not user_id.isdigit():\n", "   if not user_id:\n")],
   },
   {
      "gate": layout("a flag that is not a constant"),
      "defect": "a flag that is not a constant reads as false",
      "edits": [
         (
            ACCOUNT_PARSE,
            '   if flag not in ("true", "false"):\n      raise _bloks_schema_changed(f"carries no {'
            'key} the engine can read", path)\n',
            "",
         )
      ],
   },
   {
      "gate": ONE_ACTION,
      "defect": "the core swaps the screen's two ids",
      "edits": [
         (
            ACCOUNT_CORE,
            "            list_id=containers.list_id,\n            rows_id=containers.rows_id,",
            "            list_id=containers.rows_id,\n            rows_id=containers.list_id,",
         )
      ],
   },
   {
      "gate": ONE_ACTION,
      "defect": "the reloader is sent twice",
      "edits": [
         (
            ACCOUNT_CORE,
            "         answer = await action.send(reloader_request)\n",
            "         await action.send(reloader_request)\n"
            "         answer = await action.send(reloader_request)\n",
         )
      ],
   },
   {
      "gate": BURST,
      "defect": "the stories tray is left out",
      "edits": [(PAGE_LOAD, "      [stories_tray],\n", "")],
   },
   {
      "gate": BURST,
      "defect": "the page sends the profile load's second quick promotion call",
      "edits": [
         (PAGE_LOAD, "      [login_promotion],\n", "      [login_promotion, login_promotion],\n")
      ],
   },
   {
      "gate": BURST,
      "defect": "the jewel pair goes before the stories tray",
      "edits": [
         (
            PAGE_LOAD,
            "      [stories_tray],\n      _jewel_group(session, device_id, referer, user_agent),\n",
            "      _jewel_group(session, device_id, referer, user_agent),\n      [stories_tray],\n",
         )
      ],
   },
   {
      "gate": REFERER,
      "defect": "the companions claim the site root",
      "edits": [
         (PAGE_LOAD, "   referer = post_url(code)\n", '   referer = "https://www.instagram.com/"\n')
      ],
   },
   {
      "gate": REFERER,
      "defect": "the document's device id is not read",
      "edits": [
         (
            POSTS_CORE,
            "               device_id=read_iris_device_id(document.text),",
            "               device_id=None,",
         )
      ],
   },
   {
      "gate": POST_FROM_DOCUMENT,
      "defect": "by_code on the page reads every part of it",
      "edits": [(POSTS_CORE, "         read=_post_out_of,", "         read=_page_out_of,")],
   },
   {
      "gate": PAGE_PARTS,
      "defect": "the comments are read from the grid's preload",
      "edits": [
         (
            POSTS_CORE,
            "   comments = classify_preloaded(read_preloaded_result(html, POST_COMMENTS_PRELOA"
            "DER))",
            "   comments = classify_preloaded(read_preloaded_result(html, POST_ROOT_PRELOADER))",
         )
      ],
   },
   {
      "gate": PAGE_PARTS,
      "defect": "the grid is trimmed of its first post",
      "edits": [
         (
            POSTS_CORE,
            "      author_grid=parse_more_from_author(author_grid),",
            "      author_grid=parse_more_from_author(author_grid)[1:],",
         )
      ],
   },
   {
      "gate": MISSING,
      "defect": "the tail is scheduled before the document is read",
      "edits": [
         (
            POSTS_CORE,
            "      result = read(document.text)\n\n      if cookie_sync is not None:\n"
            "         cookie_sync.start(session, page_url, loaded_at=loaded_at, user_agent=user_ag"
            "ent)\n",
            "      if cookie_sync is not None:\n         cookie_sync.start(session, page_url, lo"
            "aded_at=loaded_at, user_agent=user_agent)\n\n      result = read(document.text)\n",
         )
      ],
   },
   {
      "gate": TAIL,
      "defect": "no tail is scheduled after a load",
      "edits": [
         (
            POSTS_CORE,
            "      if cookie_sync is not None:\n         cookie_sync.start(session, page_url,",
            "      if cookie_sync is None:\n         cookie_sync.start(session, page_url,",
         )
      ],
   },
   {
      "gate": DEFAULT_ROUTE,
      "defect": "the namespace drops the post route",
      "edits": [(MEDIA_NAMESPACE, "            route=behavior.post_route,\n", "")],
   },
   {
      "gate": DEFAULT_ROUTE,
      "defect": "the default is the departure",
      "edits": [
         (
            BEHAVIOR,
            "   post_route: PostRoute = PostRoute.PAGE\n",
            "   post_route: PostRoute = PostRoute.QUERY\n",
         )
      ],
   },
   {
      "gate": ASYNC_NAMESPACE,
      "defect": "page sends its companions whatever the behavior says",
      "edits": [
         (
            MEDIA_NAMESPACE,
            "            companions=client._behavior.page_load_companions,",
            "            companions=True,",
         )
      ],
   },
   {
      "gate": ASYNC_NAMESPACE,
      "defect": "blocked reaches the close friends read",
      "edits": [
         (ACCOUNT_NAMESPACE, "         read_blocked_accounts(\n", "         read_close_friends(\n")
      ],
   },
   {
      "gate": BLOCKING_NAMESPACE,
      "defect": "the blocking page runs by_code",
      "edits": [
         (
            MEDIA_NAMESPACE,
            "         self._client._impl.media.page(code),",
            "         self._client._impl.media.by_code(code),",
         )
      ],
   },
   {
      "gate": DUMPSTA_BLOCKED,
      "defect": "the text form drops the automatic marker",
      "edits": [
         (
            ACCOUNT_RENDER,
            '      marker = "  auto" if entry.is_auto_blocked else ""',
            '      marker = ""',
         )
      ],
   },
   {
      "gate": DUMPSTA_BLOCKED,
      "defect": "the JSON inverts the automatic flag",
      "edits": [
         (
            ACCOUNT_RENDER,
            '            "is_auto_blocked": entry.is_auto_blocked,',
            '            "is_auto_blocked": not entry.is_auto_blocked,',
         )
      ],
   },
   {
      "gate": DUMPSTA_POST_PAGE,
      "defect": "the JSON leaves out the author's grid",
      "edits": [
         (
            POST_DEPTH_RENDER,
            '"author_grid": [describe_post_thumbnail(thumbnail) for thumbnail in page.author_gri'
            "d],",
            '"author_grid": [],',
         )
      ],
   },
   {
      "gate": parity(REACHES_CORE, "media.page"),
      "defect": "page reaches the post read",
      "edits": [
         (
            MEDIA_NAMESPACE,
            "         read_post_page(\n            client._sender,",
            "         read_post(\n            client._sender,",
         )
      ],
   },
   {
      "gate": parity(REACHES_CORE, "account.blocked"),
      "defect": "blocked reaches the close friends read",
      "edits": [
         (ACCOUNT_NAMESPACE, "         read_blocked_accounts(\n", "         read_close_friends(\n")
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
   log_path = LOG_DIR / f"mutation-post-page-{stamp}.json"
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
