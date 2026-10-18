"""Break who sent a message, who reacted, what a message is and what it carries, and the mark
read, and watch each gate go red, then restore.

Same harness and same rule as ``verify_likes_gates.py``: one mutation per row, only the gate
that should catch it is run, every anchor must be found exactly once, and every file is restored
from an in-memory copy in a ``finally``.

The rows are release phase 2's items 1 to 3, gated in ``tests/test_message_identity_and_media.py``
and ``tests/test_mark_read.py``.

Run from ``engine/`` with ``uv run python scripts/verify_messages_gates.py``. Writes its result to
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

CORE_DIRECT = "dumpstagram/_core/direct.py"
POLLER = "dumpstagram/_core/realtime/poller.py"
PARSE_DIRECT = "dumpstagram/_private/web/parse/direct.py"
MODELS = "dumpstagram/models/messages.py"
GATES = "tests/test_message_identity_and_media.py"
MARK_GATES = "tests/test_mark_read.py"
MARK_READ = "dumpstagram/_core/writes/mark_read.py"
REQUESTS_DIRECT = "dumpstagram/_private/web/requests/direct.py"
NAMESPACE = "dumpstagram/namespaces/direct.py"
PENDING = "dumpstagram/pending.py"
PACER = "dumpstagram/_core/pacer.py"
WRITES_DIRECT = "dumpstagram/_core/writes/direct.py"
PENDING_GATES = "tests/test_pending.py"
WRITING_IMPORT = "from dumpstagram._core.writing import send_write\n"
SEND_TEXT = (
   '   payload = await send_write(sender, session, WriteRequest(request, "send_message"))\n'
)
SEND_MARK = (
   '   payload = await send_write(sender, session, WriteRequest(mark, "mark_thread_read"))\n'
)


def mark_gate(name: str) -> str:
   return gate(name, MARK_GATES)


def pending_gate(name: str) -> str:
   return gate(name, PENDING_GATES)


def gate(name: str, gates: str = GATES) -> str:
   return f"{gates}::{name}"


MUTATIONS: list[dict[str, object]] = [
   {
      "gate": gate("test_a_thread_read_tells_the_mapper_who_the_viewer_is"),
      "defect": "the thread open maps without the viewer",
      "edits": [
         (
            CORE_DIRECT,
            "parse_thread_detail(payload, viewer_igid=session.ds_user_id)",
            "parse_thread_detail(payload)",
         )
      ],
   },
   {
      "gate": gate("test_an_older_page_tells_the_mapper_who_the_viewer_is"),
      "defect": "an older page maps without the viewer",
      "edits": [
         (
            CORE_DIRECT,
            "parse_thread_message_page(classify(response), viewer_igid=session.ds_user_id)",
            "parse_thread_message_page(classify(response))",
         )
      ],
   },
   {
      "gate": gate("test_a_polled_message_says_whether_the_viewer_sent_it"),
      "defect": "the listener's read back maps without the viewer",
      "edits": [
         (
            POLLER,
            "parse_thread_message_page(payload, viewer_igid=self._session.ds_user_id)",
            "parse_thread_message_page(payload)",
         )
      ],
   },
   {
      "gate": gate("test_without_the_viewer_nothing_is_claimed"),
      "defect": "an unknown viewer defaults to not the viewer",
      "edits": [
         (
            PARSE_DIRECT,
            "   if igid is None or viewer_igid is None:\n      return None\n",
            "   if igid is None or viewer_igid is None:\n      return False\n",
         )
      ],
   },
   {
      "gate": gate("test_the_viewers_message_and_anothers_are_told_apart_by_igid"),
      "defect": "the message is matched on its fbid",
      "edits": [
         (
            PARSE_DIRECT,
            "is_from_viewer=_is_viewer(sender.igid, viewer_igid),",
            "is_from_viewer=_is_viewer(sender.fbid, viewer_igid),",
         )
      ],
   },
   {
      "gate": gate("test_each_reaction_takes_the_igid_its_own_sender_fbid_names"),
      "defect": "reactions are paired with msg_reactions by position",
      "edits": [
         (
            PARSE_DIRECT,
            "      sender_igid = igids.get(sender_fbid)\n",
            "      sender_igid = list(igids.values())[index] if index < len(igids) else None\n",
         )
      ],
   },
   {
      "gate": gate("test_a_photo_carries_its_full_picture_preview_and_size"),
      "defect": "the photo list is read from the wrong key",
      "edits": [
         (PARSE_DIRECT, '   MessageKind.IMAGE: "attachments",', '   MessageKind.IMAGE: "images",')
      ],
   },
   {
      "gate": gate("test_a_photo_carries_its_full_picture_preview_and_size"),
      "defect": "the preview is taken for the photo",
      "edits": [
         (
            PARSE_DIRECT,
            '      url=_required_string(item, "attachment_cdn_url", path),\n'
            '      preview_url=_optional_string(item, "preview_cdn_url", path),',
            '      url=_required_string(item, "preview_cdn_url", path),\n'
            '      preview_url=_optional_string(item, "preview_cdn_url", path),',
         )
      ],
   },
   {
      "gate": gate("test_an_unknown_content_type_is_returned_as_other_with_the_rest_of_the_page"),
      "defect": "an unknown content type fails the page",
      "edits": [
         (
            PARSE_DIRECT,
            "   return _KNOWN_KINDS.get(typename, MessageKind.OTHER)",
            "   return _KNOWN_KINDS[typename]",
         )
      ],
   },
   {
      "gate": gate("test_an_unknown_attachment_in_a_media_list_is_a_schema_change"),
      "defect": "an unknown attachment is mapped as a photo",
      "edits": [
         (
            PARSE_DIRECT,
            "   kind = _ATTACHMENT_KINDS.get(typename)\n",
            "   kind = _ATTACHMENT_KINDS.get(typename, MessageMediaKind.IMAGE)\n",
         )
      ],
   },
   {
      "gate": gate("test_a_shared_reel_carries_its_preview_picture"),
      "defect": "a share's preview picture is dropped",
      "edits": [
         (PARSE_DIRECT, "   if image is None:\n      return ()", "   if True:\n      return ()")
      ],
   },
   {
      "gate": gate("test_a_voice_clip_carries_its_address_and_length"),
      "defect": "a voice clip loses its length",
      "edits": [
         (
            PARSE_DIRECT,
            '         duration_ms=_required_integer(item, "playable_duration_ms", path),\n',
            "",
         )
      ],
   },
   {
      "gate": gate("test_an_animated_image_carries_its_webp"),
      "defect": "an animated image carries its mp4 under url",
      "edits": [(PARSE_DIRECT, '"attachment_webp_url"', '"attachment_mp4_url"')],
   },
   {
      "gate": gate("test_every_oracle_message_has_a_named_kind_in_the_counts_recorded"),
      "defect": "a kind's type name drifts",
      "edits": [
         (
            MODELS,
            'VIEW_ONCE_VIDEO = "SlideMessageRavenVideoContent"',
            'VIEW_ONCE_VIDEO = "SlideMessageRavenVideo"',
         )
      ],
   },
   {
      "gate": gate("test_a_node_without_content_is_a_schema_change"),
      "defect": "a node without content is read as text",
      "edits": [
         (
            PARSE_DIRECT,
            '   content = _required(node, "content", path)\n',
            '   content = node.get("content") or {"__typename": "SlideMessageText"}\n',
         )
      ],
   },
   {
      "gate": mark_gate("test_the_setting_off_reads_an_unread_thread_without_marking"),
      "defect": "the read marks whatever the setting says",
      "edits": [(CORE_DIRECT, "         if mark_read:\n", "         if True:\n")],
   },
   {
      "gate": mark_gate("test_an_unread_thread_open_is_marked_read_at_its_newest_message"),
      "defect": "the namespace does not pass the setting down",
      "edits": [(NAMESPACE, "mark_read=client._behavior.mark_threads_read,", "mark_read=False,")],
   },
   {
      "gate": mark_gate("test_the_sync_surface_marks_as_the_async_one_does"),
      "defect": "the namespace does not pass the setting down, seen from the sync surface",
      "edits": [(NAMESPACE, "mark_read=client._behavior.mark_threads_read,", "mark_read=False,")],
   },
   {
      "gate": mark_gate("test_a_thread_already_read_sends_nothing_more"),
      "defect": "a thread already read is marked again",
      "edits": [
         (
            MARK_READ,
            "   if not state.is_unread or newest_id is None or newest_ms is None:\n",
            "   if newest_id is None or newest_ms is None:\n",
         )
      ],
   },
   {
      "gate": mark_gate("test_an_unread_thread_open_is_marked_read_at_its_newest_message"),
      "defect": "the mark names the first message on the page",
      "edits": [
         (
            PARSE_DIRECT,
            "      if newest_ms is None or sent_ms > newest_ms:\n",
            "      if newest_ms is None:\n",
         )
      ],
   },
   {
      "gate": mark_gate("test_an_unread_thread_open_is_marked_read_at_its_newest_message"),
      "defect": "the validation sends the time as a number",
      "edits": [
         (
            REQUESTS_DIRECT,
            '"message_timestamp_ms": str(message_timestamp_ms)',
            '"message_timestamp_ms": message_timestamp_ms',
         )
      ],
   },
   {
      "gate": mark_gate("test_a_thread_marked_unread_by_hand_is_marked_read"),
      "defect": "the marked unread flag is ignored",
      "edits": [
         (
            PARSE_DIRECT,
            "   return is_marked_unread or not has_read_to_the_end\n",
            "   return not has_read_to_the_end\n",
         )
      ],
   },
   {
      "gate": mark_gate("test_an_older_page_never_marks"),
      "defect": "an older page is read as a thread open",
      "edits": [
         (
            CORE_DIRECT,
            "   is_newest_page = after is None and newer_than_message_id is None\n",
            "   is_newest_page = True\n",
         )
      ],
   },
   {
      "gate": mark_gate("test_the_scrolling_route_for_the_newest_page_never_marks"),
      "defect": "the scrolling route opens the thread",
      "edits": [
         (
            CORE_DIRECT,
            "   opens_the_thread = is_newest_page and first_page is ThreadFirstPage.DETAIL\n",
            "   opens_the_thread = is_newest_page\n",
         )
      ],
   },
   {
      "gate": mark_gate("test_the_mark_is_a_write_and_the_budget_refuses_it"),
      "defect": "the mark is sent around the write path",
      "edits": [
         (
            MARK_READ,
            SEND_MARK,
            "   payload = classify(await sender.send(mark))\n",
         )
      ],
   },
   {
      "gate": mark_gate("test_the_mark_departs_once_through_the_write_slot"),
      "defect": "the mark is sent around the write slot",
      "edits": [
         (
            MARK_READ,
            SEND_MARK,
            "   payload = classify(await sender.send(mark))\n",
         )
      ],
   },
   {
      "gate": mark_gate("test_a_mark_answered_without_a_receipt_raises_and_sends_nothing_after_it"),
      "defect": "an answer without a receipt is taken as marked",
      "edits": [(MARK_READ, "   if not parse_mark_read_answer(payload):\n", "   if False:\n")],
   },
   {
      "gate": mark_gate("test_both_requests_carry_the_variables_the_browser_sent_in_its_order"),
      "defect": "the mark's data keys are reordered",
      "edits": [
         (
            REQUESTS_DIRECT,
            '"data": {"item_id": "", "message_id": message_id},',
            '"data": {"message_id": message_id, "item_id": ""},',
         )
      ],
   },
   {
      "gate": pending_gate("test_submit_returns_before_the_call_finishes"),
      "defect": "submit waits for the call to finish",
      "edits": [
         (
            PENDING,
            "   return PendingCall._of(client._loop.start(target(*args, **kwargs)), operation)",
            "   started = client._loop.start(target(*args, **kwargs))\n"
            "   started.exception()\n"
            "   return PendingCall._of(started, operation)",
         )
      ],
   },
   {
      "gate": pending_gate(
         "test_concurrent_calls_on_one_client_each_get_their_own_answer_one_at_a_time"
      ),
      "defect": "the pacer stops holding the account across a read's wait and send",
      "edits": [
         (
            PACER,
            "      async with self._lock:\n         await self._wait_until_allowed(",
            "      if True:\n         await self._wait_until_allowed(",
         )
      ],
   },
   {
      "gate": pending_gate("test_a_failure_arrives_as_itself_with_one_seam_note"),
      "defect": "the seam note is added on every look at the result",
      "edits": [
         (
            PENDING,
            '         if note not in getattr(failure, "__notes__", ()):\n',
            "         if True:\n",
         )
      ],
   },
   {
      "gate": pending_gate("test_a_failure_arrives_as_itself_with_one_seam_note"),
      "defect": "the seam note is dropped",
      "edits": [(PENDING, "            failure.add_note(note)\n", "            pass\n")],
   },
   {
      "gate": pending_gate("test_a_cancelled_call_raises_operation_cancelled"),
      "defect": "a cancelled call raises the bare CancelledError",
      "edits": [
         (
            PENDING,
            "(asyncio.CancelledError, concurrent.futures.CancelledError) as cancelled:",
            "asyncio.CancelledError as cancelled:",
         )
      ],
   },
   {
      "gate": pending_gate("test_a_timeout_leaves_the_call_running"),
      "defect": "a timeout cancels the call",
      "edits": [
         (
            PENDING,
            "      except TimeoutError:\n         raise\n",
            "      except TimeoutError:\n         self._future.cancel()\n         raise\n",
         )
      ],
   },
   {
      "gate": pending_gate("test_a_submitted_write_still_takes_the_write_path"),
      "defect": "the send departs around the write path",
      "edits": [
         (
            WRITES_DIRECT,
            WRITING_IMPORT,
            WRITING_IMPORT + "from dumpstagram._private.web.classify import classify\n",
         ),
         (WRITES_DIRECT, SEND_TEXT, "   payload = classify(await sender.send(request))\n"),
      ],
   },
   {
      "gate": pending_gate("test_a_private_name_is_refused_before_anything_starts"),
      "defect": "a private name can be submitted",
      "edits": [
         (
            PENDING,
            '      is_private = not segment or segment.startswith("_")\n',
            "      is_private = not segment\n",
         )
      ],
   },
   {
      "gate": pending_gate("test_an_unknown_name_is_refused"),
      "defect": "an unknown name escapes as AttributeError",
      "edits": [(PENDING, "      except AttributeError:\n", "      except KeyError:\n")],
   },
   {
      "gate": pending_gate("test_what_does_not_answer_once_is_refused_before_anything_starts"),
      "defect": "anything callable is started",
      "edits": [(PENDING, "   if not answers_once:\n", "   if False:\n")],
   },
   {
      "gate": pending_gate("test_the_listener_cannot_be_submitted"),
      "defect": "the listener is started",
      "edits": [(PENDING, "   if not answers_once:\n", "   if False:\n")],
   },
   {
      "gate": pending_gate("test_a_pending_call_is_not_built_directly"),
      "defect": "a PendingCall can be built by hand",
      "edits": [
         (
            PENDING,
            '      raise TypeError(\n         "a PendingCall comes from',
            '      return None\n      raise TypeError(\n         "a PendingCall comes from',
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


def preflight() -> None:
   """Refuse to start when any anchor is not found exactly once, before a single gate runs, so
   a stale anchor costs seconds rather than the run up to it."""

   for mutation in MUTATIONS:
      edits = mutation["edits"]
      assert isinstance(edits, list)

      for relative, find, _ in edits:
         occurrences = (ENGINE / relative).read_text(encoding="utf-8").count(find)

         if occurrences != 1:
            raise SystemExit(
               f"mutation anchor found {occurrences} times in {relative} for "
               f"{mutation['gate']}, expected exactly once"
            )


def main() -> int:
   preflight()
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
   log_path = LOG_DIR / f"mutation-messages-{stamp}.json"
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
