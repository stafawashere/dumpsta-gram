"""Break E2 batch 11e, the explore grid's later pages, an audio's page, the mutual followers and
the audio id a post names, watch each gate go red, restore.

Same harness and same rule as ``verify_discovery_search_gates.py``: one mutation per entry below,
only the gate that should catch it is run, every anchor must be found exactly once, and every
file is restored from an in-memory copy in a ``finally`` so an interrupted run cannot leave a
mutation behind.

The mutations cover the later explore page's mapper and its cursor, the next page request and
both explore walks, the audio page's mapper, request, refusal and both audio walks, the audio id
on a post, the mutual followers mapper, request, statuses and setting, the three commands, and
the namespace parity gates.

Run from ``engine/`` with ``uv run python scripts/verify_last_reads_gates.py``. Writes its result
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

DISCOVERY_PARSE = "dumpstagram/_private/web/parse/discovery.py"
MEDIA_PARSE = "dumpstagram/_private/web/parse/media.py"
PROFILES_PARSE = "dumpstagram/_private/web/parse/profiles.py"
DISCOVERY_REQUESTS = "dumpstagram/_private/web/requests/discovery.py"
PROFILES_REQUESTS = "dumpstagram/_private/web/requests/profiles.py"
DISCOVERY_CORE = "dumpstagram/_core/discovery.py"
PROFILES_CORE = "dumpstagram/_core/profiles.py"
FEEDS = "dumpstagram/namespaces/feeds.py"
PROFILES = "dumpstagram/namespaces/profiles.py"
DISCOVERY_COMMANDS = "dumpstagram/_cli/commands/discovery.py"
MEDIA_RENDER = "dumpstagram/_cli/render/media.py"
PROFILES_RENDER = "dumpstagram/_cli/render/profiles.py"
GATES = "tests/test_last_reads.py"
PARITY_GATES = "tests/test_facade_parity.py"


def gate(name: str) -> str:
   return f"{GATES}::{name}"


def parity(name: str, qualified: str) -> str:
   return f"{PARITY_GATES}::{name}[{qualified}]"


LATER_MAP = gate("test_a_later_explore_page_maps_every_tile_of_its_single_list_sections")
ENTRY_SHAPE = gate("test_a_later_page_entry_of_another_shape_raises")
EXPLORE_CURSOR = gate(
   "test_the_explore_cursor_is_the_root_max_id_and_not_the_counter_or_a_tiles_cluster"
)
EXPLORE_NEXT = gate(
   "test_a_later_explore_page_is_the_first_pages_get_with_max_id_in_the_browsers_order"
)
EXPLORE_WALK = gate("test_the_explore_walk_follows_the_root_max_id_and_ends_on_more_available")
BLOCKING_EXPLORE_WALK = gate("test_the_blocking_explore_walk_answers_as_its_async_twin")
NO_CURSOR = gate("test_an_explore_page_that_says_more_with_no_cursor_stops_the_walk_loudly")
SONG_MAP = gate("test_a_songs_audio_page_maps_the_track_the_count_and_every_reel")
LATER_AUDIO = gate(
   "test_a_later_songs_page_has_no_track_and_the_original_sounds_last_page_no_cursor"
)
AUDIO_BOTH = gate("test_an_audio_page_filling_both_track_slots_raises")
AUDIO_REQUEST = gate("test_the_audio_page_is_the_pages_form_post_with_its_own_header_set")
AUDIO_REFUSED = gate("test_an_audio_id_that_is_not_digits_is_refused_before_anything_is_sent")
AUDIO_WALK = gate("test_the_audio_walk_spends_the_empty_read_and_ends_on_the_upstreams_flag")
BLOCKING_AUDIO = gate("test_the_blocking_audio_reads_answer_as_their_async_twins")
REEL_AUDIO_ID = gate("test_a_reels_feed_reel_names_its_audio_page_though_its_audio_is_none")
THIN_PLACE = gate(
   "test_a_reel_tagged_at_a_place_sent_without_coordinates_names_the_place_and_no_location"
)
THIN_REFUSED = gate("test_a_thin_place_outside_the_reels_feed_is_still_refused")
POST_BOTH = gate("test_a_post_filling_both_audio_slots_raises_rather_than_naming_either")
MUTUAL_MAP = gate(
   "test_mutual_followers_map_every_account_from_its_string_id_with_the_answers_own_end"
)
MUTUAL_REQUEST = gate(
   "test_mutual_followers_are_the_lists_get_then_its_accounts_statuses_in_one_action"
)
MUTUAL_SETTING = gate(
   "test_mutual_followers_under_the_setting_and_the_default_and_a_username_refused"
)
BLOCKING_MUTUAL = gate("test_the_blocking_mutual_followers_leave_the_statuses_out_when_told")
DUMPSTA_EXPLORE = gate(
   "test_dumpsta_explore_reads_pages_on_the_root_cursor_until_the_grids_own_end"
)
DUMPSTA_AUDIO = gate("test_dumpsta_audio_reads_the_track_and_its_reels_until_the_pages_own_end")
DUMPSTA_MUTUAL = gate("test_dumpsta_mutual_followers_prints_every_account_its_status_and_the_flag")
REFUSE_NAME = gate("test_the_new_commands_refuse_a_name")
NOT_MUTATED = gate("test_a_copied_fixture_is_not_mutated_by_a_read")
FORWARDS = "test_a_blocking_namespace_method_forwards_every_argument_on_the_loop_thread"
REACHES = "test_a_namespace_method_reaches_the_core_capability_the_table_names"


def mutation(gate: str, defect: str, path: str, find: str, replace: str) -> dict[str, object]:
   return {"gate": gate, "defect": defect, "edits": [(path, find, replace)]}


MUTATIONS: list[dict[str, object]] = [
   mutation(
      LATER_MAP,
      "a later page's single list section is refused",
      DISCOVERY_PARSE,
      "   is_a_dynamic_grid = set(content) == _DYNAMIC_GRID_CONTENT_KEYS\n",
      "   is_a_dynamic_grid = False\n",
   ),
   mutation(
      LATER_MAP,
      "a large tile's reel is read as a fill tile",
      DISCOVERY_PARSE,
      "      featured.extend(\n",
      "      posts.extend(\n",
   ),
   mutation(
      LATER_MAP,
      "the fill tiles are dropped",
      DISCOVERY_PARSE,
      "         posts.append(_media_of(entry, entry_path))\n",
      "         _media_of(entry, entry_path)\n",
   ),
   mutation(
      ENTRY_SHAPE,
      "an entry of another shape falls through to the large tile reader",
      DISCOVERY_PARSE,
      '      if keys != {"clips"}:\n',
      "      if keys is None:\n",
   ),
   mutation(
      EXPLORE_CURSOR,
      "the cursor is read from the page counter",
      DISCOVERY_PARSE,
      "      end_cursor=_cursor_if_carried(payload, _EXPLORE),\n",
      '      end_cursor=payload.get("next_max_id"),\n',
   ),
   mutation(
      EXPLORE_NEXT,
      "the cursor is appended after the five parameters",
      DISCOVERY_REQUESTS,
      '      params = dict(sorted({**params, "max_id": after}.items()))\n',
      '      params = {**params, "max_id": after}\n',
   ),
   mutation(
      EXPLORE_NEXT,
      "the cursor never reaches the request",
      DISCOVERY_CORE,
      "session, web_session_id=new_web_session_id(), after=after, user_agent=user_agent",
      "session, web_session_id=new_web_session_id(), after=None, user_agent=user_agent",
   ),
   mutation(
      EXPLORE_WALK,
      "the walk reads the first page again",
      FEEDS,
      "         lambda cursor: self.explore_posts(after=cursor), limit=limit, after=after\n",
      "         lambda cursor: self.explore_posts(after=None), limit=limit, after=after\n",
   ),
   mutation(
      EXPLORE_WALK,
      "the walk ends on an empty page rather than the flag",
      DISCOVERY_CORE,
      "   return Page(items=grid.posts, has_next_page=grid.more_available, "
      "end_cursor=grid.end_cursor)\n",
      "   return Page(items=grid.posts, has_next_page=not grid.posts, "
      "end_cursor=grid.end_cursor)\n",
   ),
   mutation(
      BLOCKING_EXPLORE_WALK,
      "the blocking walk drops its cursor",
      FEEDS,
      "            client._impl.feeds.explore_posts(after=cursor),\n",
      "            client._impl.feeds.explore_posts(after=None),\n",
   ),
   mutation(
      NO_CURSOR,
      "a page with no cursor is read as the last one",
      DISCOVERY_CORE,
      "   return Page(items=grid.posts, has_next_page=grid.more_available, "
      "end_cursor=grid.end_cursor)\n",
      "   has_next_page = grid.more_available and grid.end_cursor is not None\n\n"
      "   return Page(items=grid.posts, has_next_page=has_next_page, "
      "end_cursor=grid.end_cursor)\n",
   ),
   mutation(
      SONG_MAP,
      "a song is read as no track",
      DISCOVERY_PARSE,
      '   if has_music:\n      return _music(music, f"{path}.music_info")\n',
      "   if has_music:\n      return None\n",
   ),
   mutation(
      SONG_MAP,
      "the count is read from the photos",
      DISCOVERY_PARSE,
      '      clips_count=_required_integer(counts, "clips_count", f"{_AUDIO_PAGE}.media_count"),\n',
      '      clips_count=_required_integer(counts, "photos_count", '
      'f"{_AUDIO_PAGE}.media_count"),\n',
   ),
   mutation(
      SONG_MAP,
      "the audio page's collaborator rows are read",
      DISCOVERY_PARSE,
      'if key != "coauthor_producers"\n',
      "if True\n",
   ),
   mutation(
      SONG_MAP,
      "the audio page's reels are read from the item rather than its media",
      DISCOVERY_PARSE,
      '   return parse_post(_audio_clip_node(media), f"{path}.media", null_is_unseen=True)\n',
      '   return parse_post(_audio_clip_node(item), f"{path}.media", null_is_unseen=True)\n',
   ),
   mutation(
      LATER_AUDIO,
      "a last page's absent cursor becomes an empty one",
      DISCOVERY_PARSE,
      '      end_cursor=_cursor_if_carried(paging, f"{_AUDIO_PAGE}.paging_info"),\n',
      '      end_cursor=paging.get("max_id") or "",\n',
   ),
   mutation(
      LATER_AUDIO,
      "an audio page always says more exist",
      DISCOVERY_PARSE,
      '      more_available=_required_flag(paging, "more_available", '
      'f"{_AUDIO_PAGE}.paging_info"),\n',
      "      more_available=True,\n",
   ),
   mutation(
      AUDIO_BOTH,
      "a page naming both kinds of track is read as the song",
      DISCOVERY_PARSE,
      '   if has_music and has_original:\n      raise SchemaChanged(f"{path} filled both',
      '   if False:\n      raise SchemaChanged(f"{path} filled both',
   ),
   mutation(
      AUDIO_REQUEST,
      "the first page leaves max_id out",
      DISCOVERY_REQUESTS,
      '      "max_id": after or "",\n',
      '      **({"max_id": after} if after else {}),\n',
   ),
   mutation(
      AUDIO_REQUEST,
      "the second id is left empty",
      DISCOVERY_REQUESTS,
      '      "original_sound_audio_asset_id": audio_id,\n',
      '      "original_sound_audio_asset_id": "",\n',
   ),
   mutation(
      AUDIO_REQUEST,
      "the audio page sends a csrf header the page did not",
      DISCOVERY_REQUESTS,
      '      "x-ig-d": "www",\n      "x-ig-max-touch-points": "0",\n',
      '      "x-ig-d": "www",\n      "x-ig-max-touch-points": "0",\n'
      '      "x-csrftoken": session.csrftoken,\n',
   ),
   mutation(
      AUDIO_REQUEST,
      "the referer is the reels tab",
      DISCOVERY_REQUESTS,
      '   return f"{ORIGIN}/reels/audio/{audio_id}/"\n',
      '   return f"{ORIGIN}/reels/"\n',
   ),
   mutation(
      AUDIO_REFUSED,
      "a title reaches the form",
      DISCOVERY_CORE,
      "   refuse_what_is_not_an_audio_id(audio_id)\n",
      "",
   ),
   mutation(
      AUDIO_WALK,
      "the walk stops on a short page",
      DISCOVERY_CORE,
      "   return Page(items=page.clips, has_next_page=page.more_available, "
      "end_cursor=page.end_cursor)\n",
      "   return Page(items=page.clips, has_next_page=len(page.clips) >= 12, "
      "end_cursor=page.end_cursor)\n",
   ),
   mutation(
      AUDIO_WALK,
      "the walk asks for the next page on no cursor",
      FEEDS,
      "         lambda cursor: self.audio_clips(audio_id, after=cursor), "
      "limit=limit, after=after\n",
      "         lambda cursor: self.audio_clips(audio_id, after=None), limit=limit, after=after\n",
   ),
   mutation(
      BLOCKING_AUDIO,
      "the blocking walk drops its cursor",
      FEEDS,
      "            client._impl.feeds.audio_clips(audio_id, after=cursor),\n",
      "            client._impl.feeds.audio_clips(audio_id, after=None),\n",
   ),
   mutation(
      REEL_AUDIO_ID,
      "a reel's audio id is taken from its modelled audio",
      DISCOVERY_PARSE,
      "      audio_id=audio_page_id(media, media_path),\n",
      "",
   ),
   mutation(
      REEL_AUDIO_ID,
      "a song's audio id is read from the asset id",
      MEDIA_PARSE,
      '      return _required_string(asset, "audio_cluster_id", '
      'f"{music_path}.music_asset_info")\n',
      '      return _required_string(asset, "title", f"{music_path}.music_asset_info")\n',
   ),
   mutation(
      POST_BOTH,
      "a post naming both kinds of track is read as the song",
      MEDIA_PARSE,
      "   if has_music and has_original:\n      raise SchemaChanged(\n"
      '         f"{metadata_path} filled both music_info and original_sound_info", '
      "path=metadata_path\n      )\n\n   if has_music:\n      music_path",
      "   if False:\n      raise SchemaChanged(\n"
      '         f"{metadata_path} filled both music_info and original_sound_info", '
      "path=metadata_path\n      )\n\n   if has_music:\n      music_path",
   ),
   mutation(
      MUTUAL_MAP,
      "a filled next_max_id is read as the end",
      PROFILES_PARSE,
      '   end_cursor = _mutual_cursor(payload.get("next_max_id"))\n',
      "   end_cursor = None\n",
   ),
   mutation(
      MUTUAL_MAP,
      "a cursor of an unknown type is accepted",
      PROFILES_PARSE,
      '   if not isinstance(raw, str):\n      path = f"{_MUTUAL_FOLLOWERS}.next_max_id"\n',
      '   if False:\n      path = f"{_MUTUAL_FOLLOWERS}.next_max_id"\n',
   ),
   mutation(
      MUTUAL_REQUEST,
      "the list asks for another page size",
      PROFILES_REQUESTS,
      '      params={"page_size": str(MUTUAL_PAGE_SIZE)},\n',
      '      params={"page_size": str(MUTUAL_PAGE_SIZE), "count": "12"},\n',
   ),
   mutation(
      MUTUAL_REQUEST,
      "the statuses are never asked for",
      PROFILES_CORE,
      "      after=None,\n      with_statuses=with_statuses,\n",
      "      after=None,\n      with_statuses=False,\n",
   ),
   mutation(
      MUTUAL_REQUEST,
      "the answer always says more exist",
      PROFILES_CORE,
      "   return MutualFollowers(accounts=page.items, has_more=page.has_next_page)\n",
      "   return MutualFollowers(accounts=page.items, has_more=True)\n",
   ),
   mutation(
      MUTUAL_SETTING,
      "the default behavior leaves the statuses out",
      PROFILES,
      "            with_statuses=client._behavior.follow_list_statuses,\n"
      "            user_agent=client._user_agent,\n         )\n      )\n\n"
      "   async def reels(",
      "            with_statuses=False,\n"
      "            user_agent=client._user_agent,\n         )\n      )\n\n"
      "   async def reels(",
   ),
   mutation(
      BLOCKING_MUTUAL,
      "the blocking method reads the followers",
      PROFILES,
      "         self._client._impl.profiles.mutual_followers(user_id),\n",
      "         self._client._impl.profiles.followers(user_id),\n",
   ),
   mutation(
      DUMPSTA_EXPLORE,
      "the command reads the first page again",
      DISCOVERY_COMMANDS,
      "      cursor = grid.end_cursor\n",
      "      cursor = None\n",
   ),
   mutation(
      DUMPSTA_EXPLORE,
      "the post form leaves the audio id out",
      MEDIA_RENDER,
      '      "audio_id": post.audio_id,\n',
      "",
   ),
   mutation(
      DUMPSTA_AUDIO,
      "the command reads past the last page",
      DISCOVERY_COMMANDS,
      "      if not audio_page.more_available:\n",
      "      if False:\n",
   ),
   mutation(
      DUMPSTA_MUTUAL,
      "the flag that the list goes on is always true",
      PROFILES_RENDER,
      '      "more_available": mutual.has_more,\n',
      '      "more_available": True,\n',
   ),
   mutation(
      REFUSE_NAME,
      "the audio command takes a title",
      DISCOVERY_COMMANDS,
      'metavar="AUDIO_ID", type=audio_id,',
      'metavar="AUDIO_ID", type=str,',
   ),
   mutation(
      NOT_MUTATED,
      "the audio page's reel author is edited in the caller's answer",
      DISCOVERY_PARSE,
      '   if isinstance(author, dict):\n      node["user"] = {"hd_profile_pic_url_info": None, '
      "**author}\n\n   return node\n\n\ndef _audio_clip(",
      '   if isinstance(author, dict):\n      author["hd_profile_pic_url_info"] = None\n\n'
      "   return node\n\n\ndef _audio_clip(",
   ),
   mutation(
      THIN_PLACE,
      "a reel's place without coordinates is refused",
      DISCOVERY_PARSE,
      '   if is_a_place_without_coordinates:\n      node["location"] = None\n',
      '   if False:\n      node["location"] = None\n',
   ),
   mutation(
      THIN_PLACE,
      "a reel's place is dropped with its missing coordinates",
      DISCOVERY_PARSE,
      "      tagged_place=tagged_place(media, media_path),\n",
      "",
   ),
   mutation(
      THIN_PLACE,
      "a post with coordinates does not name its place",
      MEDIA_PARSE,
      "      tagged_place=tagged_place(node, path),\n",
      "",
   ),
   mutation(
      THIN_REFUSED,
      "every read accepts a place without coordinates",
      MEDIA_PARSE,
      "   return Location(\n      id=_place_id(raw, location_path),",
      '   if "lat" not in raw or "lng" not in raw:\n      return None\n\n'
      "   return Location(\n      id=_place_id(raw, location_path),",
   ),
   mutation(
      DUMPSTA_EXPLORE,
      "the post form leaves the tagged place out",
      MEDIA_RENDER,
      '      "tagged_place": _describe_tagged_place(post.tagged_place),\n',
      "",
   ),
   mutation(
      parity(FORWARDS, "feeds.audio"),
      "the blocking audio drops its cursor",
      FEEDS,
      "         self._client._impl.feeds.audio(audio_id, after=after),\n",
      "         self._client._impl.feeds.audio(audio_id, after=None),\n",
   ),
   mutation(
      parity(FORWARDS, "feeds.explore"),
      "the blocking explore drops its cursor",
      FEEDS,
      "         self._client._impl.feeds.explore(after=after),\n",
      "         self._client._impl.feeds.explore(),\n",
   ),
   mutation(
      parity(REACHES, "profiles.mutual_followers"),
      "the mutual followers method reaches the following read",
      PROFILES,
      "         read_mutual_followers(\n",
      "         read_following_page(\n",
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
   log_path = LOG_DIR / f"mutation-last-reads-{stamp}.json"
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
