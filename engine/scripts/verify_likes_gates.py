"""Break the single post read, like and unlike, watch each of their gates go red, restore.

Same harness and same rule as ``verify_notes_gates.py``: one mutation per line below, only the
gate that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

The rows are the Step 15 table in ``engine/docs/build-plan.md``, its parity row held as the one
request's shape because the browser burst is unrecorded under ruling 23, and the gates this
step added beside them.

Run from ``engine/`` with ``uv run python scripts/verify_likes_gates.py``. Writes its result to
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


PARSE = "dumpstagram/_private/web/parse.py"
REQUESTS = "dumpstagram/_private/web/requests.py"
LIKES = "dumpstagram/_core/writes/likes.py"
CLI = "dumpstagram/_cli/main.py"
GATES = "tests/test_likes.py"

SEND_LIKE = '   payload = await send_write(sender, session, WriteRequest(request, "like"))\n'
SEND_UNLIKE = '   payload = await send_write(sender, session, WriteRequest(request, "unlike"))\n'
WRITING_IMPORT = "from dumpstagram._core.writing import send_write\n"
CLASSIFY_IMPORT = WRITING_IMPORT + "from dumpstagram._private.web.classify import classify\n"


def gate(name: str) -> str:
   return f"{GATES}::{name}"


MUTATIONS: list[dict[str, object]] = [
   {
      "gate": gate("test_each_write_sends_the_request_the_engine_replayed"),
      "defect": "the write names the post by the id form instead of the pk",
      "edits": [
         (
            REQUESTS,
            '"media_id": post_pk,\n         "tracking_token": None,',
            '"media_id": f"{post_pk}_0",\n         "tracking_token": None,',
         )
      ],
   },
   {
      "gate": gate("test_each_write_sends_the_request_the_engine_replayed"),
      "defect": "unlike is pointed at the like document",
      "edits": [
         (
            REQUESTS,
            "      UNLIKE_MEDIA,\n      _like_variables",
            "      LIKE_MEDIA,\n      _like_variables",
         )
      ],
   },
   {
      "gate": gate("test_each_write_sends_the_request_the_engine_replayed"),
      "defect": "the write carries a variable no observed send carried",
      "edits": [
         (
            REQUESTS,
            '         "tracking_token": None,\n      }',
            '         "tracking_token": None,\n         "actor_id": "0",\n      }',
         )
      ],
   },
   {
      "gate": gate("test_each_write_sends_the_request_the_engine_replayed"),
      "defect": "a request nothing recorded goes out beside the like",
      "edits": [
         (
            LIKES,
            "   if not session.fb_dtsg:\n"
            "      await bootstrap(sender, session, user_agent=user_agent)\n\n"
            "   request = build_like_request(",
            "   if True:\n"
            "      await bootstrap(sender, session, user_agent=user_agent)\n\n"
            "   request = build_like_request(",
         )
      ],
   },
   {
      "gate": gate("test_the_id_form_is_refused_before_anything_is_sent"),
      "defect": "the id form is passed through to the request",
      "edits": [(LIKES, "   if not is_a_media_pk(post_pk):\n", "   if False:\n")],
   },
   {
      "gate": gate("test_the_post_read_maps_has_liked_and_like_count_from_the_item"),
      "defect": "has_liked on the single post read defaults to false",
      "edits": [
         (
            PARSE,
            'has_liked=_required_flag(node, "has_liked", path),\n      caption=',
            "has_liked=False,\n      caption=",
         )
      ],
   },
   {
      "gate": gate("test_the_post_read_maps_has_liked_and_like_count_from_the_item"),
      "defect": "like_count on the single post read is taken from comment_count",
      "edits": [
         (
            PARSE,
            'like_count=_required_integer(node, "like_count", path),\n'
            '      comment_count=_required_integer(node, "comment_count", path),\n'
            '      has_liked=_required_flag(node, "has_liked", path),\n      caption=',
            'like_count=_required_integer(node, "comment_count", path),\n'
            '      comment_count=_required_integer(node, "comment_count", path),\n'
            '      has_liked=_required_flag(node, "has_liked", path),\n      caption=',
         )
      ],
   },
   {
      "gate": gate("test_a_post_read_without_exactly_one_item_is_a_schema_change"),
      "defect": "any list of items is accepted and the first one taken",
      "edits": [
         (
            PARSE,
            "is_exactly_one_item = isinstance(items, list) and len(items) == 1",
            "is_exactly_one_item = isinstance(items, list)",
         )
      ],
   },
   {
      "gate": gate("test_the_post_read_sends_the_request_the_engine_replayed"),
      "defect": "the post read drops a provider variable the replays carried",
      "edits": [
         (
            REQUESTS,
            '         "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": False,\n',
            "",
         )
      ],
   },
   {
      "gate": gate("test_both_writes_depart_only_through_the_write_slot"),
      "defect": "the like is sent with sender.send rather than send_write",
      "edits": [
         (LIKES, WRITING_IMPORT, CLASSIFY_IMPORT),
         (LIKES, SEND_LIKE, "   payload = classify(await sender.send(request))\n"),
      ],
   },
   {
      "gate": gate("test_both_writes_depart_only_through_the_write_slot"),
      "defect": "the unlike is sent with sender.send rather than send_write",
      "edits": [
         (LIKES, WRITING_IMPORT, CLASSIFY_IMPORT),
         (LIKES, SEND_UNLIKE, "   payload = classify(await sender.send(request))\n"),
      ],
   },
   {
      "gate": gate("test_an_error_envelope_on_a_like_raises_and_departs_once"),
      "defect": "the like is sent again after an error envelope",
      "edits": [
         (
            LIKES,
            SEND_LIKE,
            "   try:\n   " + SEND_LIKE + "   except UpstreamRejected:\n   " + SEND_LIKE,
         )
      ],
   },
   {
      "gate": gate("test_an_answer_naming_the_other_state_is_not_taken_as_applied"),
      "defect": "an answer naming the other state is ignored",
      "edits": [(LIKES, "   if has_liked is not wanted:\n", "   if False:\n")],
   },
   {
      "gate": gate("test_the_cli_sends_the_named_post_to_the_named_write"),
      "defect": "the CLI crosses like and unlike",
      "edits": [
         (
            CLI,
            "      if is_like:\n         client.like(arguments.pk)",
            "      if not is_like:\n         client.like(arguments.pk)",
         )
      ],
   },
   {
      "gate": gate("test_the_cli_refuses_the_id_form_before_opening_a_client"),
      "defect": "the CLI accepts any string as a pk",
      "edits": [
         (
            CLI,
            'write.add_argument("pk", metavar="PK", type=media_pk, ',
            'write.add_argument("pk", metavar="PK", ',
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
   log_path = LOG_DIR / f"mutation-likes-{stamp}.json"
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
