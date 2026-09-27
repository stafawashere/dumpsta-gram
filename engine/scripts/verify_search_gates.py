"""Break E2 batch 8, search, watch each gate go red, restore.

Same harness and same rule as ``verify_discovery_gates.py``: one mutation per entry below, only
the gate that should catch it is run, every anchor must be found exactly once, and every file is
restored from an in-memory copy in a ``finally`` so an interrupted run cannot leave a mutation
behind.

The mutations cover the recent searches' slots, order and payloads, the slots never seen filled
and a broken union, the typeahead's accounts, the hashtag header's id and name, the three
requests, the query and tag refusals, the one query each read sends and the unobserved searches
left unregistered, both namespaces, the commands, the canary's search steps, and the namespace
parity gates for the new methods.

Run from ``engine/`` with ``uv run python scripts/verify_search_gates.py``. Writes its result to
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

PARSE = "dumpstagram/_private/web/parse/search.py"
REQUESTS = "dumpstagram/_private/web/requests/search.py"
DOCUMENTS = "dumpstagram/_private/web/documents/search.py"
MODELS = "dumpstagram/models/search.py"
NAMESPACE = "dumpstagram/namespaces/search.py"
RENDER = "dumpstagram/_cli/render/search.py"
COMMANDS = "dumpstagram/_cli/commands/search.py"
CANARY = "dumpstagram/_private/web/canary.py"
GATES = "tests/test_search.py"
DOCTOR_GATES = "tests/test_doctor.py"
PARITY_GATES = "tests/test_facade_parity.py"


def gate(name: str) -> str:
   return f"{GATES}::{name}"


def parity(name: str, qualified: str) -> str:
   return f"{PARITY_GATES}::{name}[{qualified}]"


RECENT = gate("test_the_recent_searches_map_every_entry_from_its_filled_slot_in_order")
UNREAD = gate("test_an_unread_slot_is_its_kind_alone_and_a_broken_union_raises")
TYPEAHEAD = gate("test_the_typeahead_maps_every_account_in_order_from_its_own_keys")
HASHTAG = gate("test_the_hashtag_header_is_the_answers_id_and_the_tag_asked_for")
REQUESTS_SENT = gate("test_the_three_reads_send_what_the_replays_sent")
REFUSALS = gate("test_an_empty_query_or_a_tag_with_a_hash_is_refused_before_anything_is_sent")
ONE_QUERY = gate("test_each_search_read_sends_its_one_query_and_no_unobserved_search_is_registered")
BLOCKING = gate("test_the_blocking_search_reads_answer_as_their_async_twins")
DUMPSTA = gate("test_dumpsta_recent_searches_search_and_hashtag_print_everything_read")
DUMPSTA_REFUSES = gate("test_dumpsta_hashtag_refuses_a_hash_and_search_refuses_a_blank_query")
SEARCH_STEPS = (
   f"{DOCTOR_GATES}::test_the_search_steps_read_the_viewers_own_username_and_the_verified_tag"
)
REACHES_CORE = "test_a_namespace_method_reaches_the_core_capability_the_table_names"


def mutation(gate: str, defect: str, relative: str, find: str, replace: str) -> dict[str, object]:
   return {"gate": gate, "defect": defect, "edits": [(relative, find, replace)]}


MUTATIONS: list[dict[str, object]] = [
   mutation(
      RECENT,
      "the first entry is dropped",
      PARSE,
      "      for index, entry in enumerate(entries)\n",
      "      for index, entry in enumerate(entries[1:])\n",
   ),
   mutation(
      RECENT,
      "an account entry carries no account",
      PARSE,
      "return RecentSearch(kind=kind, account=parse_profile_summary(",
      "return RecentSearch(kind=kind, account=None and (",
   ),
   mutation(
      RECENT,
      "a keyword is altered on its way into the model",
      PARSE,
      "      return RecentSearch(kind=kind, keyword=keyword)\n",
      "      return RecentSearch(kind=kind, keyword=keyword.upper())\n",
   ),
   mutation(
      RECENT,
      "the account kind is named after the model rather than the slot",
      MODELS,
      '   ACCOUNT = "user"\n',
      '   ACCOUNT = "account"\n',
   ),
   mutation(
      UNREAD,
      "a hashtag or place entry is refused rather than carried by its kind",
      PARSE,
      "   return RecentSearch(kind=kind)\n\n\ndef parse_recent_searches",
      "   raise SchemaChanged(path, path=path)\n\n\ndef parse_recent_searches",
   ),
   mutation(
      UNREAD,
      "an entry filling two slots is read by its first",
      PARSE,
      "   if len(filled) != 1:\n",
      "   if not filled:\n",
   ),
   mutation(
      UNREAD,
      "a slot this version does not know is read as a place",
      PARSE,
      "   except ValueError as failure:\n      raise SchemaChanged(\n",
      "   except ValueError:\n"
      "      return RecentSearch(kind=RecentSearchKind.PLACE)\n"
      "      raise SchemaChanged(\n",
   ),
   mutation(
      TYPEAHEAD,
      "the first account is dropped",
      PARSE,
      "for index, user in enumerate(users)",
      "for index, user in enumerate(users[1:])",
   ),
   mutation(
      TYPEAHEAD,
      "the accounts come back in reverse",
      PARSE,
      '   users = _list_of(root, "users", root_path)\n',
      '   users = _list_of(root, "users", root_path)[::-1]\n',
   ),
   mutation(
      HASHTAG,
      "the name is not the tag asked for",
      PARSE,
      "header_path), name=tag)",
      "header_path), name=tag.upper())",
   ),
   mutation(
      HASHTAG,
      "a header without an id is accepted",
      PARSE,
      'id=_required_string(header, "id", header_path)',
      'id=str(header.get("id"))',
   ),
   mutation(
      REQUESTS_SENT,
      "the recent searches carry the explore page as referer",
      REQUESTS,
      '      RECENT_SEARCHES,\n      {},\n      referer=f"{ORIGIN}/",',
      '      RECENT_SEARCHES,\n      {},\n      referer=f"{ORIGIN}/explore/",',
   ),
   mutation(
      REQUESTS_SENT,
      "the typeahead says it has no query",
      REQUESTS,
      '{"hasQuery": True, "query": query}',
      '{"hasQuery": False, "query": query}',
   ),
   mutation(
      REQUESTS_SENT,
      "the tag is sent with its hash",
      REQUESTS,
      '{"tag_name": tag}',
      '{"tag_name": f"#{tag}"}',
   ),
   mutation(
      REQUESTS_SENT,
      "the tag is written into the referer unescaped",
      REQUESTS,
      "{quote(tag, safe='')}",
      "{tag}",
   ),
   mutation(
      REQUESTS_SENT,
      "the hashtag header is sent as the typeahead",
      REQUESTS,
      '      HASHTAG_HEADER,\n      {"tag_name": tag},',
      '      NON_PERSONALISED_TYPEAHEAD,\n      {"tag_name": tag},',
   ),
   mutation(
      REFUSALS,
      "a blank query is sent",
      REQUESTS,
      "   has_text = bool(query.strip())\n",
      "   has_text = True\n",
   ),
   mutation(
      REFUSALS,
      "a tag is not checked",
      REQUESTS,
      "   is_a_tag = _TAG.fullmatch(tag) is not None\n",
      "   is_a_tag = True\n",
   ),
   mutation(
      REFUSALS,
      "a leading hash is let through",
      REQUESTS,
      '_TAG = re.compile(r"\\w+")',
      '_TAG = re.compile(r"#?\\w+")',
   ),
   mutation(
      ONE_QUERY,
      "the recent searches are sent under the personalised typeahead's name",
      DOCUMENTS,
      'friendly_name="PolarisSearchNullStateQuery"',
      'friendly_name="PolarisSearchBoxContainerQuery"',
   ),
   mutation(
      BLOCKING,
      "the blocking accounts read asks for a hashtag",
      NAMESPACE,
      "         self._client._impl.search.accounts(query),\n",
      "         self._client._impl.search.hashtag(query),\n",
   ),
   mutation(
      DUMPSTA,
      "a keyword's text is left out of the text form",
      RENDER,
      '      return f"keyword  {entry.keyword}"\n',
      '      return "keyword"\n',
   ),
   mutation(
      DUMPSTA,
      "a keyword is left out of the JSON form",
      RENDER,
      '"keyword": entry.keyword}',
      '"keyword": None}',
   ),
   mutation(
      DUMPSTA,
      "the first account is left out of the JSON form",
      RENDER,
      '"accounts": [describe_profile_summary(account) for account in accounts],',
      '"accounts": [describe_profile_summary(account) for account in accounts[1:]],',
   ),
   mutation(
      DUMPSTA,
      "the command searches for something other than the query",
      COMMANDS,
      "client.search.accounts(arguments.query)",
      'client.search.accounts(arguments.query.strip() + " ")',
   ),
   mutation(
      DUMPSTA,
      "the hashtag's id is left out of the text form",
      RENDER,
      'f"#{hashtag.name}  id {hashtag.id}"',
      'f"#{hashtag.name}"',
   ),
   mutation(
      DUMPSTA_REFUSES,
      "the command takes a tag with its hash",
      COMMANDS,
      "   is_a_tag = _TAG.fullmatch(value) is not None\n",
      "   is_a_tag = True\n",
   ),
   mutation(
      DUMPSTA_REFUSES,
      "the command takes a blank query",
      COMMANDS,
      "   has_text = bool(value.strip())\n",
      "   has_text = True\n",
   ),
   mutation(
      SEARCH_STEPS,
      "the typeahead is replayed on the viewer's id rather than its username",
      CANARY,
      "build_non_personalised_typeahead_request(\n         session, _required(arguments.username),",
      "build_non_personalised_typeahead_request(\n         session, arguments.viewer_id,",
   ),
   mutation(
      SEARCH_STEPS,
      "the hashtag header is replayed on another tag",
      CANARY,
      'CANARY_HASHTAG = "instagram"\n',
      'CANARY_HASHTAG = "instagram_"\n',
   ),
   mutation(
      parity(REACHES_CORE, "search.recent"),
      "recent reaches the hashtag header's core function",
      NAMESPACE,
      "         read_recent_searches(\n",
      "         read_hashtag_header(\n",
   ),
   mutation(
      parity(REACHES_CORE, "search.hashtag"),
      "hashtag reaches the recent searches' core function",
      NAMESPACE,
      "         read_hashtag_header(\n",
      "         read_recent_searches(\n",
   ),
   mutation(
      parity(REACHES_CORE, "search.accounts"),
      "accounts reaches the recent searches' core function",
      NAMESPACE,
      "         read_non_personalised_typeahead(\n",
      "         read_recent_searches(\n",
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
   log_path = LOG_DIR / f"mutation-search-{stamp}.json"
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
