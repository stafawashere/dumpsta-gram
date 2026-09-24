"""Break send_message, unsend_message and the reconciling read, watch each gate go red, restore.

Same harness and same rule as ``verify_follows_gates.py``: one mutation per line below, only the
gate that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

The rows are the Step 18 table in ``engine/docs/build-plan.md``: the client identifier fresh per
call, the reconciling read matching it, the send through ``send_write`` and the created message
mapped from a recorded answer. Beside them are the single-request parity gate on the fourteen
variables the browser's composer sent, the identifier's construction, the unsend and the id it
takes, and the CLI commands.

Run from ``engine/`` with ``uv run python scripts/verify_direct_send_gates.py``. Writes its result
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


COMMANDS_DIRECT = "dumpstagram/_cli/commands/direct.py"
PARSE_DIRECT = "dumpstagram/_private/web/parse/direct.py"
REQUESTS_DIRECT = "dumpstagram/_private/web/requests/direct.py"
DIRECT_WRITES = "dumpstagram/_core/writes/direct.py"
DIRECT_READS = "dumpstagram/_core/direct.py"
CLI = "dumpstagram/_cli/main.py"
RENDER_DIRECT = "dumpstagram/_cli/render/direct.py"
GATES = "tests/test_direct_send.py"

SEND = '   payload = await send_write(sender, session, WriteRequest(request, "send_message"))\n'
UNSEND = '   payload = await send_write(sender, session, WriteRequest(request, "unsend_message"))\n'
WRITING_IMPORT = "from dumpstagram._core.writing import send_write\n"
CLASSIFY_IMPORT = WRITING_IMPORT + "from dumpstagram._private.web.classify import classify\n"
DIRECT_SEND_REFERER = (
   "      DIRECT_TEXT_SEND,\n      variables,\n      referer=thread_url(thread_fbid),\n"
)
UNSEND_REFERER = (
   '      {"message_id": message_id, "send_data": {"thread_id": thread_id}},\n'
   "      referer=thread_url(thread_fbid),\n"
)


def gate(name: str) -> str:
   return f"{GATES}::{name}"


MUTATIONS: list[dict[str, object]] = [
   {
      "gate": gate("test_the_identifier_is_built_as_the_browser_builds_it"),
      "defect": "the random bits go above the clock instead of below it",
      "edits": [
         (
            REQUESTS_DIRECT,
            "(now_ms << _OFFLINE_THREADING_RANDOM_BITS) | (random_bits & random_mask)\n",
            "((random_bits & random_mask) << 41) | now_ms\n",
         )
      ],
   },
   {
      "gate": gate("test_the_identifier_keeps_only_22_random_bits"),
      "defect": "the whole random number is written in, over the clock bits",
      "edits": [
         (
            REQUESTS_DIRECT,
            "| (random_bits & random_mask)\n",
            "| random_bits\n",
         )
      ],
   },
   {
      "gate": gate("test_the_identifier_is_cut_to_63_bits"),
      "defect": "the identifier is not cut to 63 bits",
      "edits": [
         (
            REQUESTS_DIRECT,
            "   return str(combined & ((1 << _OFFLINE_THREADING_ID_BITS) - 1))\n",
            "   return str(combined)\n",
         )
      ],
   },
   {
      "gate": gate("test_each_send_carries_a_fresh_identifier_and_returns_it"),
      "defect": "one identifier is reused across calls",
      "edits": [
         (
            DIRECT_WRITES,
            "   threading_id = offline_threading_id(clock_ms(), random_bits())\n",
            "   threading_id = offline_threading_id(0, 0)\n",
         )
      ],
   },
   {
      "gate": gate("test_each_send_carries_a_fresh_identifier_and_returns_it"),
      "defect": "the returned identifier is a new one rather than the one sent",
      "edits": [
         (
            DIRECT_WRITES,
            "   return parse_direct_text_send_answer(payload, thread_fbid, threading_id)\n",
            "   return parse_direct_text_send_answer(\n"
            "      payload, thread_fbid, offline_threading_id(clock_ms(), random_bits())\n"
            "   )\n",
         )
      ],
   },
   {
      "gate": gate("test_a_send_is_the_one_request_the_browser_sent"),
      "defect": "the thread is left unnamed, the shape of a send without a thread",
      "edits": [
         (
            REQUESTS_DIRECT,
            '      "ig_thread_igid": thread_fbid,\n',
            '      "ig_thread_igid": None,\n',
         )
      ],
   },
   {
      "gate": gate("test_a_send_is_the_one_request_the_browser_sent"),
      "defect": "send_attribution is not the composer's",
      "edits": [
         (
            REQUESTS_DIRECT,
            '      "send_attribution": SEND_ATTRIBUTION,\n',
            '      "send_attribution": None,\n',
         )
      ],
   },
   {
      "gate": gate("test_a_send_is_the_one_request_the_browser_sent"),
      "defect": "sampled, which the composer sends as null, is left out",
      "edits": [(REQUESTS_DIRECT, '      "sampled": None,\n', "")],
   },
   {
      "gate": gate("test_a_send_is_the_one_request_the_browser_sent"),
      "defect": "the text goes out bare, not wrapped as sensitive_string_value",
      "edits": [
         (
            REQUESTS_DIRECT,
            '      "text": {"sensitive_string_value": text},\n',
            '      "text": text,\n',
         )
      ],
   },
   {
      "gate": gate("test_a_send_is_the_one_request_the_browser_sent"),
      "defect": "two variables go out in another order than the composer's",
      "edits": [
         (
            REQUESTS_DIRECT,
            '      "mentions": [],\n      "mentioned_user_ids": [],\n',
            '      "mentioned_user_ids": [],\n      "mentions": [],\n',
         )
      ],
   },
   {
      "gate": gate("test_a_send_is_the_one_request_the_browser_sent"),
      "defect": "the send carries the home page as referer",
      "edits": [
         (
            REQUESTS_DIRECT,
            DIRECT_SEND_REFERER,
            '      DIRECT_TEXT_SEND,\n      variables,\n      referer=f"{ORIGIN}/",\n',
         )
      ],
   },
   {
      "gate": gate("test_the_answer_maps_into_a_sent_message"),
      "defect": "sent_at is taken from the local clock",
      "edits": [
         (
            PARSE_DIRECT,
            "      sent_at=_sent_at(root, root_path),\n",
            "      sent_at=datetime.now(tz=UTC),\n",
         )
      ],
   },
   {
      "gate": gate("test_an_answer_whose_id_is_not_its_message_id_is_a_schema_change"),
      "defect": "an id that differs from the message_id is accepted",
      "edits": [
         (PARSE_DIRECT, "   ids_disagree = echoed_id != message_id\n", "   ids_disagree = False\n")
      ],
   },
   {
      "gate": gate("test_a_send_that_cannot_be_right_is_refused_before_anything_is_sent"),
      "defect": "any thread id is accepted",
      "edits": [
         (
            DIRECT_WRITES,
            "   if not is_a_thread_fbid(thread_fbid):\n",
            "   if not thread_fbid:\n",
         )
      ],
   },
   {
      "gate": gate("test_a_send_that_cannot_be_right_is_refused_before_anything_is_sent"),
      "defect": "empty text is sent",
      "edits": [(DIRECT_WRITES, "   if not text:\n", "   if text is None:\n")],
   },
   {
      "gate": gate("test_the_send_departs_only_through_the_write_slot"),
      "defect": "the send is made with sender.send, around the write slot",
      "edits": [
         (DIRECT_WRITES, WRITING_IMPORT, CLASSIFY_IMPORT),
         (DIRECT_WRITES, SEND, "   payload = classify(await sender.send(request))\n"),
      ],
   },
   {
      "gate": gate("test_an_error_envelope_on_a_send_raises_and_departs_once"),
      "defect": "a send answered with an error is sent again",
      "edits": [
         (
            DIRECT_WRITES,
            SEND,
            "   try:\n   " + SEND + "   except UpstreamRejected:\n   " + SEND,
         )
      ],
   },
   {
      "gate": gate("test_the_read_carries_the_identifier_a_send_generated"),
      "defect": "the read leaves offline_threading_id unmapped",
      "edits": [
         (
            PARSE_DIRECT,
            "      offline_threading_id=_offline_threading_id(node, path),\n",
            "      offline_threading_id=None,\n",
         )
      ],
   },
   {
      "gate": gate("test_a_node_without_the_identifier_reads_as_none"),
      "defect": "a node without the key is refused",
      "edits": [
         (PARSE_DIRECT, '   if "offline_threading_id" not in node:\n      return None\n\n', "")
      ],
   },
   {
      "gate": gate("test_the_reconciling_read_matches_the_identifier_and_not_the_text"),
      "defect": "the reconciling read matches on text only",
      "edits": [
         (
            DIRECT_READS,
            "      is_the_sent_message = message.offline_threading_id == offline_threading_id\n",
            "      is_the_sent_message = message.text is not None\n",
         )
      ],
   },
   {
      "gate": gate("test_an_unsend_opens_the_thread_and_names_it_by_its_thread_id"),
      "defect": "the unsend names the thread by its fbid",
      "edits": [
         (
            DIRECT_WRITES,
            "      session, thread_fbid, thread_id, message_id, user_agent=user_agent\n",
            "      session, thread_fbid, thread_fbid, message_id, user_agent=user_agent\n",
         )
      ],
   },
   {
      "gate": gate("test_an_unsend_opens_the_thread_and_names_it_by_its_thread_id"),
      "defect": "the unsend skips the thread open and uses the fbid it has",
      "edits": [
         (
            DIRECT_WRITES,
            "thread_id = await read_thread_id(sender, session, thread_fbid, user_agent=user_agent)",
            "thread_id = thread_fbid",
         )
      ],
   },
   {
      "gate": gate("test_an_unsend_opens_the_thread_and_names_it_by_its_thread_id"),
      "defect": "the unsend carries the home page as referer",
      "edits": [
         (
            REQUESTS_DIRECT,
            UNSEND_REFERER,
            '      {"message_id": message_id, "send_data": {"thread_id": thread_id}},\n'
            '      referer=f"{ORIGIN}/",\n',
         )
      ],
   },
   {
      "gate": gate("test_an_unsend_answered_false_did_not_apply"),
      "defect": "an unsend answered false is reported done",
      "edits": [(DIRECT_WRITES, "   if not applied:\n", "   if applied is None:\n")],
   },
   {
      "gate": gate("test_an_unsend_answer_that_is_not_a_boolean_is_a_schema_change"),
      "defect": "a changed answer is read as truthy",
      "edits": [(PARSE_DIRECT, "   if not isinstance(answer, bool):\n", "   if answer is None:\n")],
   },
   {
      "gate": gate("test_the_unsend_departs_only_through_the_write_slot"),
      "defect": "the unsend is made with sender.send, around the write slot",
      "edits": [
         (DIRECT_WRITES, WRITING_IMPORT, CLASSIFY_IMPORT),
         (DIRECT_WRITES, UNSEND, "   payload = classify(await sender.send(request))\n"),
      ],
   },
   {
      "gate": gate("test_a_thread_open_without_a_thread_id_sends_no_unsend"),
      "defect": "a missing thread_id becomes an empty one and the unsend goes",
      "edits": [
         (
            PARSE_DIRECT,
            '_required_string(thread, "thread_id", ".".join(THREAD_DETAIL_THREAD_PATH))',
            'str(thread.get("thread_id", ""))',
         )
      ],
   },
   {
      "gate": gate("test_an_unsend_of_something_that_is_not_a_message_id_sends_nothing"),
      "defect": "any string is accepted as a message id",
      "edits": [
         (
            DIRECT_WRITES,
            "   is_a_message_id = message_id.startswith(MESSAGE_ID_PREFIX)\n",
            "   is_a_message_id = bool(message_id)\n",
         )
      ],
   },
   {
      "gate": gate("test_the_cli_sends_the_text_into_the_named_thread"),
      "defect": "the CLI crosses the thread and the text",
      "edits": [
         (
            COMMANDS_DIRECT,
            "         sent = client.send_message(arguments.thread_fbid, arguments.text)\n",
            "         sent = client.send_message(arguments.text, arguments.thread_fbid)\n",
         )
      ],
   },
   {
      "gate": gate("test_the_cli_sends_the_text_into_the_named_thread"),
      "defect": "the CLI output drops the identifier",
      "edits": [(RENDER_DIRECT, '      "offline_threading_id": sent.offline_threading_id,\n', "")],
   },
   {
      "gate": gate("test_the_cli_unsends_the_named_message"),
      "defect": "the CLI crosses the thread and the message id",
      "edits": [
         (
            COMMANDS_DIRECT,
            "         client.unsend_message(arguments.thread_fbid, arguments.message_id)\n",
            "         client.unsend_message(arguments.message_id, arguments.thread_fbid)\n",
         )
      ],
   },
   {
      "gate": gate("test_the_cli_refuses_a_wrong_id_before_opening_a_client"),
      "defect": "the CLI takes any message id",
      "edits": [
         (
            COMMANDS_DIRECT,
            '"message_id", metavar="MESSAGE_ID", type=message_id, help=',
            '"message_id", metavar="MESSAGE_ID", help=',
         )
      ],
   },
   {
      "gate": gate("test_the_cli_refuses_a_wrong_id_before_opening_a_client"),
      "defect": "the CLI takes any thread id for a send",
      "edits": [
         (
            COMMANDS_DIRECT,
            '   send.add_argument("thread_fbid", metavar="FBID", type=thread_fbid, help=',
            '   send.add_argument("thread_fbid", metavar="FBID", help=',
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
   log_path = LOG_DIR / f"mutation-direct-send-{stamp}.json"
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
