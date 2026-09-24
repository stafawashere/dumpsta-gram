"""Break the comment page read, comment and delete_comment, watch each gate go red, restore.

Same harness and same rule as ``verify_likes_gates.py``: one mutation per line below, only the
gate that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

The rows are the Step 16 table in ``engine/docs/build-plan.md``, its parity row held as each
request's shape because the browser burst is unrecorded under ruling 23, its documentation row
held by a docstring gate, and the gates this step added beside them.

Run from ``engine/`` with ``uv run python scripts/verify_comments_gates.py``. Writes its result
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


COMMANDS_MEDIA = "dumpstagram/_cli/commands/media.py"
PARSE_MEDIA = "dumpstagram/_private/web/parse/media.py"
REQUESTS_MEDIA = "dumpstagram/_private/web/requests/media.py"
READ = "dumpstagram/_core/comments.py"
WRITES = "dumpstagram/_core/writes/comments.py"
FACADE = "dumpstagram/aio.py"
CLI = "dumpstagram/_cli/main.py"
GATES = "tests/test_comments.py"

SEND_COMMENT = '   payload = await send_write(sender, session, WriteRequest(request, "comment"))\n'
SEND_DELETE = (
   '   payload = await send_write(sender, session, WriteRequest(request, "delete_comment"))\n'
)
WRITING_IMPORT = "from dumpstagram._core.writing import send_write\n"
CLASSIFY_IMPORT = WRITING_IMPORT + "from dumpstagram._private.web.classify import classify\n"
PAGE_TERMINATOR = (
   '   has_next_page = _required_flag(page_info, "has_next_page", page_info_path)\n'
   '   end_cursor = _optional_string(page_info, "end_cursor", page_info_path)\n\n'
   "   return Page(items=comments,"
)


def gate(name: str) -> str:
   return f"{GATES}::{name}"


MUTATIONS: list[dict[str, object]] = [
   {
      "gate": gate("test_a_short_page_that_says_more_exist_is_not_the_end"),
      "defect": "the page is taken as the last one when it comes back short",
      "edits": [
         (
            PARSE_MEDIA,
            PAGE_TERMINATOR,
            PAGE_TERMINATOR.replace(
               "page_info_path)\n   end_cursor",
               "page_info_path) and len(edges) >= 10\n   end_cursor",
            ),
         )
      ],
   },
   {
      "gate": gate("test_a_page_node_maps_into_a_comment_field_by_field"),
      "defect": "the like count is read from the reply count",
      "edits": [
         (
            PARSE_MEDIA,
            'like_count=_required_integer(node, "comment_like_count", path)',
            'like_count=_required_integer(node, "child_comment_count", path)',
         )
      ],
   },
   {
      "gate": gate("test_a_page_node_maps_into_a_comment_field_by_field"),
      "defect": "the viewer's like on a comment defaults to false",
      "edits": [
         (
            PARSE_MEDIA,
            'has_liked=_required_flag(node, "has_liked_comment", path)',
            "has_liked=False",
         )
      ],
   },
   {
      "gate": gate("test_the_created_comment_maps_field_by_field_from_the_recorded_answer"),
      "defect": "the author is read from fbid_v2, another identifier",
      "edits": [
         (
            PARSE_MEDIA,
            'id=_required_string(user, "pk", user_path)',
            'id=_required_string(user, "fbid_v2", user_path)',
         )
      ],
   },
   {
      "gate": gate("test_the_created_comment_maps_field_by_field_from_the_recorded_answer"),
      "defect": "created_at is read as milliseconds",
      "edits": [
         (
            PARSE_MEDIA,
            'path=f"{path}.created_at")\n\n   return datetime.fromtimestamp(raw, tz=UTC)',
            'path=f"{path}.created_at")\n\n   return datetime.fromtimestamp(raw / 1000, tz=UTC)',
         )
      ],
   },
   {
      "gate": gate("test_the_created_comment_maps_field_by_field_from_the_recorded_answer"),
      "defect": "the created comment is given a like count its answer does not carry",
      "edits": [
         (
            PARSE_MEDIA,
            "      author=_comment_author(node, path),\n   )\n",
            "      author=_comment_author(node, path),\n      like_count=0,\n   )\n",
         )
      ],
   },
   {
      "gate": gate("test_the_page_read_sends_the_request_the_engine_replayed"),
      "defect": "the page read drops the sort order the replays carried",
      "edits": [(REQUESTS_MEDIA, '         "sort_order": "popular",\n', "")],
   },
   {
      "gate": gate("test_the_page_read_sends_the_request_the_engine_replayed"),
      "defect": "the cursor is not passed on",
      "edits": [(REQUESTS_MEDIA, '         "after": after,\n', '         "after": None,\n')],
   },
   {
      "gate": gate("test_the_comment_sends_the_request_the_engine_replayed"),
      "defect": "the comment names the post by the id form",
      "edits": [
         (
            REQUESTS_MEDIA,
            '{"comment_text": text, "media_id": post_pk}',
            '{"comment_text": text, "media_id": f"{post_pk}_0"}',
         )
      ],
   },
   {
      "gate": gate("test_the_comment_sends_the_request_the_engine_replayed"),
      "defect": "the comment is wrapped in input as the like mutations are",
      "edits": [
         (
            REQUESTS_MEDIA,
            '{"connections": [], "data": {"comment_text": text, "media_id": post_pk}}',
            '{"input": {"comment_text": text, "media_id": post_pk}}',
         )
      ],
   },
   {
      "gate": gate("test_the_comment_sends_the_request_the_engine_replayed"),
      "defect": "a request nothing recorded goes out beside the comment",
      "edits": [
         (
            WRITES,
            "   if not session.fb_dtsg:\n"
            "      await bootstrap(sender, session, user_agent=user_agent)\n\n"
            "   request = build_create_comment_request(",
            "   if True:\n"
            "      await bootstrap(sender, session, user_agent=user_agent)\n\n"
            "   request = build_create_comment_request(",
         )
      ],
   },
   {
      "gate": gate("test_the_delete_sends_the_post_and_the_comment_together"),
      "defect": "the delete drops the post identifier",
      "edits": [
         (
            REQUESTS_MEDIA,
            '            "comment_id": comment_id,\n            "media_id": post_pk,\n',
            '            "comment_id": comment_id,\n',
         )
      ],
   },
   {
      "gate": gate("test_the_delete_sends_the_post_and_the_comment_together"),
      "defect": "the delete sends the post pk as the comment id",
      "edits": [
         (
            REQUESTS_MEDIA,
            '            "comment_id": comment_id,\n',
            '            "comment_id": post_pk,\n',
         )
      ],
   },
   {
      "gate": gate("test_a_delete_answered_with_a_null_root_is_not_a_delete"),
      "defect": "a null root field is taken as a delete",
      "edits": [(PARSE_MEDIA, "   return isinstance(root, dict)\n", "   return True\n")],
   },
   {
      "gate": gate("test_the_id_form_is_refused_before_anything_is_sent"),
      "defect": "the writes pass the id form through to the request",
      "edits": [(WRITES, "   if not is_a_media_pk(post_pk):\n", "   if False:\n")],
   },
   {
      "gate": gate("test_the_id_form_is_refused_before_anything_is_sent"),
      "defect": "the page read passes the id form through to the request",
      "edits": [(READ, "   if not is_a_media_pk(post_pk):\n", "   if False:\n")],
   },
   {
      "gate": gate("test_both_writes_depart_only_through_the_write_slot"),
      "defect": "the comment is sent with sender.send rather than send_write",
      "edits": [
         (WRITES, WRITING_IMPORT, CLASSIFY_IMPORT),
         (WRITES, SEND_COMMENT, "   payload = classify(await sender.send(request))\n"),
      ],
   },
   {
      "gate": gate("test_both_writes_depart_only_through_the_write_slot"),
      "defect": "the delete is sent with sender.send rather than send_write",
      "edits": [
         (WRITES, WRITING_IMPORT, CLASSIFY_IMPORT),
         (WRITES, SEND_DELETE, "   payload = classify(await sender.send(request))\n"),
      ],
   },
   {
      "gate": gate("test_an_error_envelope_on_a_comment_raises_and_departs_once"),
      "defect": "the comment is sent again after an error envelope",
      "edits": [
         (
            WRITES,
            SEND_COMMENT,
            "   try:\n   " + SEND_COMMENT + "   except UpstreamRejected:\n   " + SEND_COMMENT,
         )
      ],
   },
   {
      "gate": gate("test_the_comment_docstring_names_the_reconciling_read"),
      "defect": "the comment docstring stops naming the comment read",
      "edits": [
         (
            FACADE,
            "attempt began, and only then decide.",
            "attempt began.",
         ),
         (FACADE, "comments with\n      :meth:`comments` and look", "comments and look"),
      ],
   },
   {
      "gate": gate("test_the_cli_reads_the_named_page_and_reports_the_servers_terminator"),
      "defect": "the CLI drops the cursor",
      "edits": [
         (
            COMMANDS_MEDIA,
            "client.comments(arguments.pk, after=arguments.after)",
            "client.comments(arguments.pk)",
         )
      ],
   },
   {
      "gate": gate("test_the_cli_writes_the_named_text_to_the_named_post"),
      "defect": "the CLI comments on the post with the pk as its text",
      "edits": [
         (
            COMMANDS_MEDIA,
            "client.comment(arguments.pk, arguments.text)",
            "client.comment(arguments.pk, arguments.pk)",
         )
      ],
   },
   {
      "gate": gate("test_the_cli_deletes_the_named_comment_on_the_named_post"),
      "defect": "the CLI swaps the post and the comment",
      "edits": [
         (
            COMMANDS_MEDIA,
            "client.delete_comment(arguments.pk, arguments.comment_id)",
            "client.delete_comment(arguments.comment_id, arguments.pk)",
         )
      ],
   },
   {
      "gate": gate("test_the_cli_refuses_a_comment_id_that_is_not_digits_before_opening_a_client"),
      "defect": "the CLI accepts any string as a comment id",
      "edits": [(COMMANDS_MEDIA, "type=comment_id, ", "")],
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
   log_path = LOG_DIR / f"mutation-comments-{stamp}.json"
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
