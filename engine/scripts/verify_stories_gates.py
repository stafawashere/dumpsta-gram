"""Break E2 batch 5, stories, watch each gate go red, restore.

Same harness and same rule as ``verify_post_depth_gates.py``: one mutation per entry below, only
the gate that should catch it is run, every anchor must be found exactly once, and every file is
restored from an in-memory copy in a ``finally`` so an interrupted run cannot leave a mutation
behind.

The mutations cover the tray's mapper, the reel and highlight mapper and its items, an empty
answer and a doubled one, the three requests and their refusals, the W68 gate that no seen
mutation is sent or registered, the commands, the canary's new step and the namespace parity
gates for the new methods.

Run from ``engine/`` with ``uv run python scripts/verify_stories_gates.py``. Writes its result to
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

PARSE = "dumpstagram/_private/web/parse/stories.py"
REQUESTS = "dumpstagram/_private/web/requests/stories.py"
DOCUMENTS = "dumpstagram/_private/web/documents/stories.py"
CATALOG = "dumpstagram/_private/web/documents/catalog.py"
CANARY = "dumpstagram/_private/web/canary.py"
CORE = "dumpstagram/_core/stories.py"
NAMESPACE = "dumpstagram/namespaces/stories.py"
COMMANDS = "dumpstagram/_cli/commands/stories.py"
RENDER = "dumpstagram/_cli/render/stories.py"
GATES = "tests/test_stories.py"
DOCTOR_GATES = "tests/test_doctor.py"
PARITY_GATES = "tests/test_facade_parity.py"


def gate(name: str) -> str:
   return f"{GATES}::{name}"


def parity(name: str, qualified: str) -> str:
   return f"{PARITY_GATES}::{name}[{qualified}]"


TRAY_MAP = gate("test_the_tray_maps_every_row_in_order_with_its_owner_and_its_times")
HIGHLIGHT_MAP = gate("test_a_highlight_maps_every_item_from_its_own_keys")
PHOTO = gate("test_a_photo_item_carries_no_video_and_a_null_audio_flag_reads_as_unknown")
EMPTY = gate("test_no_live_story_is_none_and_a_highlight_with_no_reel_is_not_found")
DOUBLED = gate("test_more_than_one_reel_for_one_id_is_a_schema_change")
VIDEO_TYPE = gate("test_a_story_video_without_its_type_is_a_schema_change")
REQUESTS_GATE = gate("test_the_three_reads_send_the_variables_replayed_live")
REFUSALS = gate("test_a_username_and_a_bare_highlight_number_are_refused_before_anything_is_sent")
NO_SEEN = gate("test_no_stories_method_sends_a_seen_mutation_and_the_registry_holds_none")
DUMPSTA_PRINTS = gate("test_dumpsta_stories_tray_story_and_highlight_print_every_row_and_item")
DUMPSTA_REFUSES = gate("test_dumpsta_story_refuses_a_username_and_highlight_a_bare_number")
CANARY_REEL = (
   f"{DOCTOR_GATES}::"
   "test_the_story_reel_is_replayed_on_the_viewers_first_highlight_and_skipped_without_one"
)
REACHES_CORE = "test_a_namespace_method_reaches_the_core_capability_the_table_names"

MUTATIONS: list[dict[str, object]] = [
   {
      "gate": TRAY_MAP,
      "defect": "the tray drops its first row",
      "edits": [
         (
            PARSE,
            "for index, row in enumerate(rows))",
            "for index, row in enumerate(rows) if index > 0)",
         )
      ],
   },
   {
      "gate": TRAY_MAP,
      "defect": "a tray row never seen reads as seen at the epoch",
      "edits": [
         (
            PARSE,
            "seen_at=None if never_seen else datetime.fromtimestamp(seen, tz=UTC),",
            "seen_at=datetime.fromtimestamp(seen, tz=UTC),",
         )
      ],
   },
   {
      "gate": TRAY_MAP,
      "defect": "a tray row's latest item time is read from its expiry",
      "edits": [
         (
            PARSE,
            'latest_item_at=_time(row, "latest_reel_media", path),',
            'latest_item_at=_time(row, "expiring_at", path),',
         )
      ],
   },
   {
      "gate": TRAY_MAP,
      "defect": "the close friends flag is read from muted",
      "edits": [
         (
            PARSE,
            'has_close_friends_items=_required_flag(row, "has_besties_media", path),',
            'has_close_friends_items=_required_flag(row, "muted", path),',
         )
      ],
   },
   {
      "gate": TRAY_MAP,
      "defect": "the tray owner's high resolution picture is dropped",
      "edits": [
         (
            PARSE,
            "hd_picture = _hd_profile_pic_url(owner, owner_path) if carries_hd_picture else None",
            "hd_picture = None",
         )
      ],
   },
   {
      "gate": TRAY_MAP,
      "defect": "the tray owner's username is read from its picture",
      "edits": [
         (
            PARSE,
            'username=_required_string(owner, "username", owner_path),',
            'username=_required_string(owner, "profile_pic_url", owner_path),',
         )
      ],
   },
   {
      "gate": HIGHLIGHT_MAP,
      "defect": "an item's owner is read from the item's own pk",
      "edits": [
         (
            PARSE,
            'owner_id=_required_string(owner, "pk", f"{path}.user"),',
            'owner_id=_required_string(item, "pk", path),',
         )
      ],
   },
   {
      "gate": HIGHLIGHT_MAP,
      "defect": "an item's time taken is read from its expiry",
      "edits": [
         (
            PARSE,
            'taken_at=_time(item, "taken_at", path),',
            'taken_at=_time(item, "expiring_at", path),',
         )
      ],
   },
   {
      "gate": HIGHLIGHT_MAP,
      "defect": "a mention's username is read from its full name",
      "edits": [
         (
            PARSE,
            'username=_required_string(mention, "username", mention_path),',
            'username=_required_string(mention, "full_name", mention_path),',
         )
      ],
   },
   {
      "gate": HIGHLIGHT_MAP,
      "defect": "a track's title is read from its artist",
      "edits": [
         (
            PARSE,
            'title=_required_string(asset, "title", asset_path),',
            'title=_required_string(asset, "display_artist", asset_path),',
         )
      ],
   },
   {
      "gate": HIGHLIGHT_MAP,
      "defect": "the highlight's title is dropped",
      "edits": [
         (
            PARSE,
            'title = _required_string(reel, "title", path) if carries_title else None',
            "title = None",
         )
      ],
   },
   {
      "gate": HIGHLIGHT_MAP,
      "defect": "the highlight's cover is dropped",
      "edits": [
         (
            PARSE,
            '   return _required_string(cover, "url", f"{path}.cover_media.cropped_image_version")',
            "   return None",
         )
      ],
   },
   {
      "gate": HIGHLIGHT_MAP,
      "defect": "the close friends audience is dropped",
      "edits": [
         (
            PARSE,
            'audience=_optional_string(item, "audience", path),',
            "audience=None,",
         )
      ],
   },
   {
      "gate": HIGHLIGHT_MAP,
      "defect": "a video's first rendition is dropped",
      "edits": [
         (
            PARSE,
            'versions = _objects_or_none(item, "video_versions", path)',
            'versions = _objects_or_none(item, "video_versions", path)[1:]',
         )
      ],
   },
   {
      "gate": HIGHLIGHT_MAP,
      "defect": "the reel owner's privacy flag is dropped",
      "edits": [
         (
            PARSE,
            'is_private = _optional_flag(owner, "is_private", owner_path)'
            " if carries_private else None",
            "is_private = None",
         )
      ],
   },
   {
      "gate": HIGHLIGHT_MAP,
      "defect": "the reel drops its last item",
      "edits": [
         (
            PARSE,
            '   items = _list_of(reel, "items", path)\n',
            '   items = _list_of(reel, "items", path)[:-1]\n',
         )
      ],
   },
   {
      "gate": PHOTO,
      "defect": "a null audio flag reads as False",
      "edits": [
         (
            PARSE,
            'has_audio=_optional_flag(item, "has_audio", path),',
            'has_audio=_optional_flag(item, "has_audio", path) or False,',
         )
      ],
   },
   {
      "gate": PHOTO,
      "defect": "a photo is given a zero duration",
      "edits": [
         (
            PARSE,
            "   if raw is None:\n      return None\n\n   is_a_number",
            "   if raw is None:\n      return 0.0\n\n   is_a_number",
         )
      ],
   },
   {
      "gate": EMPTY,
      "defect": "a highlight with no reel returns None",
      "edits": [
         (
            PARSE,
            '      raise NotFound("the upstream answered no reel for that highlight")',
            "      return None  # type: ignore[return-value]",
         )
      ],
   },
   {
      "gate": EMPTY,
      "defect": "an empty answer is read as a reel",
      "edits": [
         (
            PARSE,
            "   return reels[0] if reels else None",
            "   return reels[0] if reels else {}",
         )
      ],
   },
   {
      "gate": DOUBLED,
      "defect": "a second reel for one id is dropped silently",
      "edits": [
         (
            PARSE,
            "answers_more_than_one = len(reels) > 1",
            "answers_more_than_one = len(reels) > 2",
         )
      ],
   },
   {
      "gate": VIDEO_TYPE,
      "defect": "a rendition's type is filled in when absent",
      "edits": [
         (
            PARSE,
            'version_type=_required_integer(entry, "type", f"{path}.video_versions[{index}]"),',
            'version_type=entry.get("type", 101),',
         )
      ],
   },
   {
      "gate": REQUESTS_GATE,
      "defect": "the reel query is posted to the other path",
      "edits": [(DOCUMENTS, "   url=GRAPHQL_QUERY_URL,\n", "")],
   },
   {
      "gate": REQUESTS_GATE,
      "defect": "a highlight is read without the highlight flag",
      "edits": [
         (
            REQUESTS,
            '{"reel_ids_arr": [highlight_id], "is_highlight": True, COMMUNITY_NOTE_PROVIDER: True}',
            '{"reel_ids_arr": [highlight_id], COMMUNITY_NOTE_PROVIDER: True}',
         )
      ],
   },
   {
      "gate": REQUESTS_GATE,
      "defect": "an account's reel is read with the highlight flag",
      "edits": [
         (
            REQUESTS,
            '{"reel_ids_arr": [user_id], COMMUNITY_NOTE_PROVIDER: True}',
            '{"reel_ids_arr": [user_id], "is_highlight": True, COMMUNITY_NOTE_PROVIDER: True}',
         )
      ],
   },
   {
      "gate": REQUESTS_GATE,
      "defect": "the tray asks for suggested accounts it does not show",
      "edits": [(REQUESTS, '"max_number_to_display": 0,', '"max_number_to_display": 5,')],
   },
   {
      "gate": REQUESTS_GATE,
      "defect": "the tray is sent with another referer",
      "edits": [
         (
            REQUESTS,
            '      STORIES_TRAY_VARIABLES,\n      referer=f"{ORIGIN}/",',
            '      STORIES_TRAY_VARIABLES,\n      referer=f"{ORIGIN}/stories/",',
         )
      ],
   },
   {
      "gate": REFUSALS,
      "defect": "a highlight id reaches the request unchecked",
      "edits": [(CORE, "   refuse_what_is_not_a_highlight_id(highlight_id)\n\n", "")],
   },
   {
      "gate": REFUSALS,
      "defect": "a bare highlight number is accepted",
      "edits": [
         (
            REQUESTS,
            '_HIGHLIGHT_ID = re.compile(r"highlight:[0-9]+")',
            '_HIGHLIGHT_ID = re.compile(r"(highlight:)?[0-9]+")',
         )
      ],
   },
   {
      "gate": REFUSALS,
      "defect": "a username reaches the reel request unchecked",
      "edits": [(CORE, "   refuse_what_is_not_a_user_id(user_id)\n\n", "")],
   },
   {
      "gate": NO_SEEN,
      "defect": "the reel read sends a second request beside its query",
      "edits": [
         (
            CORE,
            "      request = build_story_reel_request(session, user_id, user_agent=user_agent)\n"
            "      response = await sender.send(request)",
            "      request = build_story_reel_request(session, user_id, user_agent=user_agent)\n"
            "      await sender.send(request)\n"
            "      response = await sender.send(request)",
         )
      ],
   },
   {
      "gate": NO_SEEN,
      "defect": "a seen mutation is registered beside the reads",
      "edits": [
         (
            DOCUMENTS,
            '__all__ = ["STORY_REEL"]\n',
            '__all__ = ["STORY_REEL", "STORY_SEEN"]\n\n'
            "STORY_SEEN = PersistedQuery(\n"
            '   doc_id="1",\n'
            '   friendly_name="PolarisStoriesV3SeenMutation",\n'
            '   finding_id="mark-a-story-seen",\n'
            ")\n",
         ),
         (
            CATALOG,
            "from dumpstagram._private.web.documents.stories import STORY_REEL\n",
            "from dumpstagram._private.web.documents.stories import STORY_REEL, STORY_SEEN\n",
         ),
         (CATALOG, "   UNFOLLOW_USER,\n)", "   UNFOLLOW_USER,\n   STORY_SEEN,\n)"),
      ],
   },
   {
      "gate": DUMPSTA_PRINTS,
      "defect": "the tray JSON drops its first row",
      "edits": [
         (
            RENDER,
            '"reels": [_describe_tray_reel(reel) for reel in tray]',
            '"reels": [_describe_tray_reel(reel) for reel in tray[1:]]',
         )
      ],
   },
   {
      "gate": DUMPSTA_PRINTS,
      "defect": "an account with no live story prints an empty reel",
      "edits": [
         (
            RENDER,
            'return {"reel": None, "item_count": 0}',
            'return {"reel": {}, "item_count": 0}',
         )
      ],
   },
   {
      "gate": DUMPSTA_PRINTS,
      "defect": "the text form miscounts the items",
      "edits": [
         (
            RENDER,
            'lines.append(f"items: {len(reel.items)}")',
            'lines.append(f"items: {len(reel.items) - 1}")',
         )
      ],
   },
   {
      "gate": DUMPSTA_PRINTS,
      "defect": "the highlight command reads another id",
      "edits": [
         (
            COMMANDS,
            "highlight = client.stories.highlight(arguments.highlight_id)",
            "highlight = client.stories.highlight(arguments.highlight_id + '0')",
         )
      ],
   },
   {
      "gate": DUMPSTA_REFUSES,
      "defect": "story takes a username",
      "edits": [
         (
            COMMANDS,
            '"user_id", metavar="USER_ID", type=account_id,',
            '"user_id", metavar="USER_ID", type=str,',
         )
      ],
   },
   {
      "gate": DUMPSTA_REFUSES,
      "defect": "highlight takes a bare number",
      "edits": [(COMMANDS, "      type=highlight_id,\n", "")],
   },
   {
      "gate": CANARY_REEL,
      "defect": "the canary reads a highlight it did not learn",
      "edits": [
         (
            CANARY,
            "      arguments.highlight_id = tray.highlights[0].id",
            '      arguments.highlight_id = "highlight:1"',
         )
      ],
   },
   {
      "gate": CANARY_REEL,
      "defect": "the canary's reel step is keyed on nothing learned",
      "edits": [
         (
            CANARY,
            '      query=STORY_REEL,\n      requires="highlight_id",',
            "      query=STORY_REEL,\n      requires=None,",
         )
      ],
   },
   {
      "gate": parity(REACHES_CORE, "stories.reel"),
      "defect": "reel reaches the highlight read",
      "edits": [
         (
            NAMESPACE,
            "         read_story_reel(\n            client._sender,",
            "         read_highlight(\n            client._sender,",
         )
      ],
   },
   {
      "gate": parity(REACHES_CORE, "stories.highlight"),
      "defect": "highlight reaches the reel read",
      "edits": [
         (
            NAMESPACE,
            "         read_highlight(\n            client._sender,",
            "         read_story_reel(\n            client._sender,",
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
   log_path = LOG_DIR / f"mutation-stories-{stamp}.json"
   log_path.write_text(
      json.dumps({"every_gate_fired": every_gate_fired, "gates": results}, indent=2) + "\n",
      encoding="utf-8",
   )

   for entry in results:
      fired = entry["red_under_mutation"] and entry["green_after_restore"]
      status = "red then green" if fired else "DID NOT FIRE"
      print(f"{status}: {entry['gate'].split('::')[1]}  ({entry['defect']})")

   fired_count = sum(
      1 for entry in results if entry["red_under_mutation"] and entry["green_after_restore"]
   )
   print(f"fired {fired_count} of {len(results)}")
   print(f"log written to {log_path}")

   return 0 if every_gate_fired else 1


if __name__ == "__main__":
   raise SystemExit(main())
