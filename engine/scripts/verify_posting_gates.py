"""Break posting, watch each of its gates go red, restore. E1 item 9.

Same harness and same rule as ``verify_likes_gates.py``: one mutation per row below, only the
gate that should catch it is run, every anchor must be found exactly once, and every file is
restored from an in-memory copy in a ``finally`` so an interrupted run cannot leave a mutation
behind.

The rows are the gates Step 19 asks for, on the request shapes recorded in
``tests/fixtures/posting/``: the upload and the two publishes, the orphaned upload, a publish
never retried, the delete and the read that confirms it, parity on both facades, and the CLI.

Run from ``engine/`` with ``uv run python scripts/verify_posting_gates.py``. Writes its result to
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

POSTS = "dumpstagram/_core/writes/posts.py"
IMAGES = "dumpstagram/_core/images.py"
REQUESTS = "dumpstagram/_private/web/requests/posting.py"
PARSE = "dumpstagram/_private/web/parse/posting.py"
AIO = "dumpstagram/aio.py"
NAMESPACE = "dumpstagram/namespaces/media.py"
COMMANDS = "dumpstagram/_cli/commands/posting.py"
CLI = "dumpstagram/_cli/main.py"
GATES = "tests/test_posting.py"
PARITY = "tests/test_facade_parity.py"

UPLOAD_SEND = (
   "         payload = await send_write("
   'upload_sender, session, WriteRequest(request, "upload_photo"))\n'
)
PUBLISH_SEND = "      payload = await send_write(sender, session, write)\n"


def gate(name: str) -> str:
   return f"{GATES}::{name}"


def parity(name: str, method: str) -> str:
   return f"{PARITY}::{name}[media.{method}]"


MUTATIONS: list[dict[str, object]] = [
   {
      "gate": gate("test_the_upload_is_shaped_as_the_browser_sent_it"),
      "defect": "the upload goes to the www host",
      "edits": [
         (
            REQUESTS,
            '_UPLOAD_URL = "https://i.instagram.com/rupload_igphoto/',
            '_UPLOAD_URL = "https://www.instagram.com/rupload_igphoto/',
         )
      ],
   },
   {
      "gate": gate("test_the_upload_is_shaped_as_the_browser_sent_it"),
      "defect": "the upload carries a csrf header the composer's uploader never sends",
      "edits": [
         (REQUESTS, '      "offset": "0",\n', '      "offset": "0",\n      "x-csrftoken": "x",\n')
      ],
   },
   {
      "gate": gate("test_the_upload_is_shaped_as_the_browser_sent_it"),
      "defect": "the upload claims to be same origin",
      "edits": [(REQUESTS, '"sec-fetch-site": "same-site"', '"sec-fetch-site": "same-origin"')],
   },
   {
      "gate": gate("test_the_upload_declares_the_files_own_width_and_height"),
      "defect": "the upload swaps the width and the height",
      "edits": [
         (
            REQUESTS,
            '      "upload_media_height": image.height,\n      "upload_media_width": image.width,',
            '      "upload_media_height": image.width,\n      "upload_media_width": image.height,',
         )
      ],
   },
   {
      "gate": gate("test_the_photo_publish_sends_the_verified_form"),
      "defect": "the photo publish drops a field both verified replays sent",
      "edits": [(REQUESTS, '      "clips_share_preview_to_feed": "1",\n', "")],
   },
   {
      "gate": gate("test_the_photo_publish_sends_the_verified_form"),
      "defect": "the photo publish names an upload id other than the one uploaded",
      "edits": [
         (
            POSTS,
            "build_photo_publish_request(session, upload_id, caption",
            "build_photo_publish_request(session, str(int(upload_id) + 1), caption",
         )
      ],
   },
   {
      "gate": gate("test_the_carousel_publish_sends_the_browsers_json_in_its_order"),
      "defect": "the carousel publish is form encoded",
      "edits": [
         (
            REQUESTS,
            'headers=_publish_headers(session, "application/json", user_agent),\n'
            '      content=json.dumps(body, separators=(",", ":")).encode("utf-8"),',
            'headers=_publish_headers(session, "application/x-www-form-urlencoded", user_agent),'
            '\n      content=urlencode(body).encode("utf-8"),',
         )
      ],
   },
   {
      "gate": gate("test_the_carousel_publish_sends_the_browsers_json_in_its_order"),
      "defect": "the carousel publish sends its keys out of the browser's order",
      "edits": [
         (
            REQUESTS,
            '      "archive_only": False,\n      "caption": caption,\n',
            '      "caption": caption,\n      "archive_only": False,\n',
         )
      ],
   },
   {
      "gate": gate("test_the_carousel_publish_sends_the_browsers_json_in_its_order"),
      "defect": "the carousel publish reverses the slides",
      "edits": [
         (
            REQUESTS,
            '[{"upload_id": upload_id} for upload_id in upload_ids]',
            '[{"upload_id": upload_id} for upload_id in reversed(upload_ids)]',
         )
      ],
   },
   {
      "gate": gate("test_the_delete_names_the_viewers_post_from_its_page"),
      "defect": "the delete names the post by its pk alone",
      "edits": [(POSTS, 'media_id = f"{post_pk}_{session.ds_user_id}"', "media_id = post_pk")],
   },
   {
      "gate": gate("test_the_delete_names_the_viewers_post_from_its_page"),
      "defect": "the delete is sent from the home page",
      "edits": [(REQUESTS, '"referer": post_url(code),', '"referer": f"{ORIGIN}/",')],
   },
   {
      "gate": gate("test_the_delete_names_the_viewers_post_from_its_page"),
      "defect": "the delete carries a csrf header the page's request did not",
      "edits": [
         (
            REQUESTS,
            '      "x-ig-d": "www",\n',
            '      "x-ig-d": "www",\n      "x-csrftoken": session.csrftoken,\n',
         )
      ],
   },
   {
      "gate": gate(
         "test_a_publish_that_fails_after_the_upload_names_the_orphan_and_sends_nothing_more"
      ),
      "defect": "a failed publish says nothing about the upload it orphaned",
      "edits": [
         (
            POSTS,
            "   except Exception as failure:\n      failure.add_note(\n",
            "   except Exception as failure:\n      (lambda note: None)(\n",
         )
      ],
   },
   {
      "gate": gate(
         "test_a_publish_that_fails_after_the_upload_names_the_orphan_and_sends_nothing_more"
      ),
      "defect": "a refused publish is sent once more",
      "edits": [
         (
            POSTS,
            "      return parse_published_post(payload, uploaded)\n",
            "      try:\n"
            "         return parse_published_post(payload, uploaded)\n"
            "      except UpstreamRejected:\n"
            "         payload = await send_write(\n"
            "            sender, session, WriteRequest(write.request, write.operation)\n"
            "         )\n\n"
            "         return parse_published_post(payload, uploaded)\n",
         )
      ],
   },
   {
      "gate": gate("test_a_failed_second_upload_names_the_first_as_orphaned_and_publishes_nothing"),
      "defect": "a failed upload's note forgets the uploads that applied before it",
      "edits": [(POSTS, "      if applied\n", "      if False\n")],
   },
   {
      "gate": gate("test_a_publish_lost_in_flight_is_unknown_and_never_sent_again"),
      "defect": "a publish lost in flight is sent again",
      "edits": [
         (
            POSTS,
            PUBLISH_SEND,
            "      try:\n"
            "         payload = await send_write(sender, session, write)\n"
            "      except Exception:\n"
            "         payload = await send_write(\n"
            "            sender, session, WriteRequest(write.request, write.operation)\n"
            "         )\n",
         )
      ],
   },
   {
      "gate": gate("test_an_upload_counts_against_the_write_budget"),
      "defect": "the upload leaves as a read, outside send_write",
      "edits": [
         (
            POSTS,
            UPLOAD_SEND,
            "         from dumpstagram._private.web.classify import classify\n\n"
            "         payload = classify(await upload_sender.send(request))\n",
         )
      ],
   },
   {
      "gate": gate("test_an_upload_answered_for_another_id_publishes_nothing"),
      "defect": "an upload answered for another id is taken as this one",
      "edits": [
         (PARSE, "is_the_same_upload = str(answered_id) == upload_id", "is_the_same_upload = True")
      ],
   },
   {
      "gate": gate("test_a_publish_answer_without_status_ok_is_a_rejection"),
      "defect": "a status other than ok is read as a publish",
      "edits": [(PARSE, "   if status == _STATUS_OK:\n", "   if True:\n")],
   },
   {
      "gate": gate("test_the_publish_returns_the_post_the_answer_describes"),
      "defect": "the post's pk is read from the id form",
      "edits": [
         (
            PARSE,
            'pk=_required_string(media, "pk", "media"),',
            'pk=_required_string(media, "id", "media"),',
         )
      ],
   },
   {
      "gate": gate("test_a_delete_answered_without_did_delete_is_refused"),
      "defect": "a delete answered with did_delete false counts as a delete",
      "edits": [(PARSE, "   return did_delete is True\n", "   return True\n")],
   },
   {
      "gate": gate("test_the_id_form_is_refused_before_a_delete_is_sent"),
      "defect": "the id form reaches the delete request",
      "edits": [(POSTS, "   if not is_a_media_pk(post_pk):\n", "   if False:\n")],
   },
   {
      "gate": gate("test_what_is_not_a_jpeg_is_refused_before_anything_is_sent"),
      "defect": "a file that is not a JPEG is sent with made-up dimensions",
      "edits": [
         (
            IMAGES,
            '      raise ValueError("only a JPEG can be posted, '
            'and this does not start like one")\n',
            "      return JpegImage(content=content, width=1, height=1)\n",
         )
      ],
   },
   {
      "gate": gate("test_a_jpeg_is_read_from_a_path_as_from_bytes"),
      "defect": "the path form drops the file's last bytes",
      "edits": [(IMAGES, "Path(image).read_bytes()", "Path(image).read_bytes()[:-2]")],
   },
   {
      "gate": gate("test_a_carousel_of_one_is_refused_before_anything_is_sent"),
      "defect": "one image is published as a carousel",
      "edits": [(POSTS, "MIN_CAROUSEL_IMAGES = 2\n", "MIN_CAROUSEL_IMAGES = 1\n")],
   },
   {
      "gate": gate("test_the_client_uploads_through_a_pool_pinned_to_the_upload_host"),
      "defect": "the upload pool is pinned to the www host",
      "edits": [(AIO, "      allowed_host=UPLOAD_HOST,\n", "      allowed_host=INSTAGRAM_HOST,\n")],
   },
   {
      "gate": gate("test_the_client_uploads_through_a_pool_pinned_to_the_upload_host"),
      "defect": "uploads are paced apart from the account's other writes",
      "edits": [
         (
            AIO,
            "         upload_transport_for(session),\n         self._sender.pacer,\n",
            "         upload_transport_for(session),\n         Pacer(),\n",
         )
      ],
   },
   {
      "gate": gate("test_the_client_uploads_through_a_pool_pinned_to_the_upload_host"),
      "defect": "a client from with_behavior uploads on a pacer of its own",
      "edits": [
         (
            AIO,
            "      scoped._uploads = self._uploads.with_pacing("
            "pacing_for(behavior), write_policy_for(behavior))\n",
            "      scoped._uploads = PacedSender(self._uploads._sender, Pacer())\n",
         )
      ],
   },
   {
      "gate": parity(
         "test_a_namespace_method_reaches_the_core_capability_the_table_names", "publish_photo"
      ),
      "defect": "the photo publish reaches the carousel capability",
      "edits": [
         (
            NAMESPACE,
            "         publish_photo(\n            client._sender,\n",
            "         publish_carousel(\n            client._sender,\n",
         )
      ],
   },
   {
      "gate": parity(
         "test_a_blocking_namespace_method_forwards_every_argument_on_the_loop_thread",
         "delete_post",
      ),
      "defect": "the blocking delete forwards the pk as the code",
      "edits": [
         (NAMESPACE, "media.delete_post(post_pk, code),", "media.delete_post(post_pk, post_pk),")
      ],
   },
   {
      "gate": parity(
         "test_a_blocking_namespace_method_forwards_every_argument_on_the_loop_thread",
         "publish_carousel",
      ),
      "defect": "the blocking carousel publish drops the caption",
      "edits": [
         (
            NAMESPACE,
            "media.publish_carousel(images, caption=caption),",
            "media.publish_carousel(images),",
         )
      ],
   },
   {
      "gate": gate("test_the_cli_does_not_confirm_a_read_back_of_someone_elses_post"),
      "defect": "the CLI confirms a read back without checking whose post it is",
      "edits": [
         (
            COMMANDS,
            "   is_the_viewers = detail.author.id == viewer_id\n",
            "   is_the_viewers = True\n",
         )
      ],
   },
   {
      "gate": gate("test_the_cli_publishes_and_confirms_by_reading_the_post_back"),
      "defect": "the CLI reads back something other than the published code",
      "edits": [
         (
            COMMANDS,
            "      detail = client.media.by_code(published.code)\n",
            "      detail = client.media.by_code(published.pk)\n",
         )
      ],
   },
   {
      "gate": gate("test_the_cli_prints_a_published_post_even_when_the_read_after_it_fails"),
      "defect": "a failed read after a publish loses the post's code",
      "edits": [
         (
            COMMANDS,
            '      payload["read_back_error"] = type(failure).__name__\n\n'
            '      return payload, f"{text}  read back failed',
            '      raise\n\n      return payload, f"{text}  read back failed',
         )
      ],
   },
   {
      "gate": gate("test_the_cli_reports_a_deleted_post_gone_only_on_the_deleted_posts_refusal"),
      "defect": "the CLI calls a post gone on any refused read",
      "edits": [
         (
            COMMANDS,
            "is_the_deleted_post_refusal = refusal.code == DELETED_POST_READ_REFUSAL",
            "is_the_deleted_post_refusal = True",
         )
      ],
   },
   {
      "gate": gate("test_the_cli_reports_a_deleted_post_gone_only_on_the_deleted_posts_refusal"),
      "defect": "the CLI reports a delete gone without reading",
      "edits": [
         (
            COMMANDS,
            "   try:\n      client.media.by_code(code)\n",
            '   try:\n      raise UpstreamRejected("", code=DELETED_POST_READ_REFUSAL)\n',
         )
      ],
   },
   {
      "gate": gate("test_the_cli_says_a_post_that_still_reads_back_is_not_gone"),
      "defect": "a post that still reads back exits as a success",
      "edits": [(COMMANDS, 'still reads back", EXIT_STILL_READABLE', 'still reads back", EXIT_OK')],
   },
   {
      "gate": gate("test_the_cli_publishes_the_carousel_slides_in_the_order_given"),
      "defect": "the CLI reverses the slides",
      "edits": [
         (
            COMMANDS,
            "images = [Path(image) for image in arguments.images]",
            "images = [Path(image) for image in reversed(arguments.images)]",
         )
      ],
   },
   {
      "gate": gate("test_the_cli_refuses_a_carousel_of_one_before_opening_a_client"),
      "defect": "a carousel of one reaches a client",
      "edits": [(COMMANDS, "   if names_too_few_slides:\n", "   if False:\n")],
   },
   {
      "gate": gate("test_the_cli_prints_the_orphan_note_with_the_error"),
      "defect": "the CLI drops the note naming the orphaned upload",
      "edits": [(CLI, "         print(redact(note), file=errors)\n", "         pass\n")],
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
   log_path = LOG_DIR / f"mutation-posting-{stamp}.json"
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
