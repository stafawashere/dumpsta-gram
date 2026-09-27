"""Read only. Ran 2026-09-27, all stages, 18 requests, run run-2026-09-27-183420 (W115 to W117).
Thirteen requests for every stage, and up to four more, conditional.

E2 batch 11e, the first engine replays of the four hypothesis findings the browser recorded in
run ``run-2026-09-27-182013``. Each hypothesis read is replayed twice. ``--stage`` picks the
stages to run, and may be given more than once. With no ``--stage`` every stage runs, and every
run first spends the bootstrap.

   shared
      1  the inbox document, for fresh tokens (the bootstrap)
   explore, 3, 4 alone
      1  the explore grid's first page, the library's own builder, finding
         ``read-the-explore-grid``
      2  its next page, GET ``/api/v1/discover/web/explore_grid/`` with the five first page
         parameters and ``max_id`` the first page's root ``max_id``, twice, finding
         ``read-the-explore-grid-next-page``
   audio, 5 and up to 1 conditional, 7 alone
      1  the reels feed's first page, the library's own builder, for an audio id
      2  that audio's page, form POST ``/api/v1/clips/music/`` with ``audio_cluster_id`` and
         ``original_sound_audio_asset_id`` both the audio id and ``max_id`` empty, twice,
         finding ``read-an-audio-page``
      2  its next page, the same form with ``max_id`` the first answer's
         ``payload.paging_info.max_id``, twice, finding ``read-an-audio-page-next-page``
   mutual, 4 and up to 3 conditional, 8 alone
      1  the owner's following, page one, the library's own builder, for candidates
      1  a public candidate's profile by id, the library's own builder, and up to 2 more
         candidates while none so far has more than 12 mutual followers
      2  the chosen account's mutual followers, GET
         ``/api/v1/friendships/<id>/mutual_followers/`` with ``page_size`` 12, twice, finding
         ``read-mutual-followers``
      1  when the chosen account has more than 12 and the first answer carries a
         ``next_max_id``, the same GET with ``max_id`` that value, once (INFERENCE, by analogy
         with the follow lists, never observed in a browser)

Conditional: the reels feed's next page, the library's own builder, when its first page offers
no licensed music; the second and third candidate profiles; the mutual followers next page.
Alone means the stage run by itself, the bootstrap included. A next page is sent only when the
answer before it offered its cursor.

The audio id is a licensed song's ``music_info.music_asset_info.audio_cluster_id`` where the
reels page offers one, a song ``is_trending_in_clips`` first, and otherwise a reel's
``original_sound_info.audio_asset_id``. The reels feed carries no clip count, so a large one
cannot be chosen ahead of the read; the audio page's own ``media_count`` is logged instead.
The audio POST goes out through ``_e2_support.rest`` with ``comet_route``, the header set the
page sent (``x-fb-lsd``, ``x-ig-d``, no ``x-csrftoken`` and no ``x-ig-app-id``) and the comet
envelope with ``__crn`` ``comet.igweb.PolarisClipsAudioRoute``, without the fields the engine has
never produced. The browser's first page form carried ``max_id`` empty, on both captured audio
pages, so this one does too. The page's own later form field ``qpl_active_flow_ids`` and header
``x-fb-qpl-active-flows``, seen once on the one-clip page, are not sent.

The browser followed the mutual followers GET with ``show_many`` for the accounts it returned,
a read the engine already ships; it is not sent here, since the finding under test is the list.

Nothing is changed and nothing is visible to anyone else. The log carries counts, lengths, key
names and four-character id prefixes, never a username, a title or a caption. Every answer is
kept under the skill's ``var/captures/``.

Run it from ``engine/`` with one of:

   uv run python probes/e2_last_reads_replay.py
   uv run python probes/e2_last_reads_replay.py --stage explore
   uv run python probes/e2_last_reads_replay.py --stage audio
   uv run python probes/e2_last_reads_replay.py --stage mutual

Every run writes an ``e2-last-reads-replay`` log, and ``e2_record_verifications.py`` reads only
the newest one, so record each stage's run before the next stage runs.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from _e2_support import E2Replay, dig, id_prefix, read_hypothesis, run_probe

from dumpstagram._private.web.bootstrap import ORIGIN
from dumpstagram._private.web.requests.discovery import (
   EXPLORE_REFERER,
   build_explore_grid_request,
   build_reels_feed_first_page_request,
   build_reels_feed_next_page_request,
)
from dumpstagram._private.web.requests.profiles import (
   build_following_request,
   build_profile_request,
)

KIND = "e2-last-reads-replay"
STAGES = ("explore", "audio", "mutual")
STAGE_REQUESTS = {"explore": 3, "audio": 5, "mutual": 4}
STAGE_CONDITIONAL = {"explore": 0, "audio": 1, "mutual": 3}

AUDIO_ROUTE = "comet.igweb.PolarisClipsAudioRoute"
REELS_CONNECTION = ("data", "xdt_api__v1__clips__home__connection_v2")
MUTUAL_PAGE_SIZE = "12"
MUTUAL_PAGE_LIMIT = 12
MAX_CANDIDATES = 3


def media_pks(value: Any) -> set[str]:
   """Every ``pk`` of an object held under a ``media`` key, anywhere in ``value``."""

   found: set[str] = set()

   if isinstance(value, dict):
      for key, inner in value.items():
         carries_a_media_pk = key == "media" and isinstance(inner, dict) and "pk" in inner

         if carries_a_media_pk:
            found.add(str(inner["pk"]))

         found |= media_pks(inner)
   elif isinstance(value, list):
      for inner in value:
         found |= media_pks(inner)

   return found


def length_of(value: Any) -> int | None:
   return len(value) if isinstance(value, str) else None


def describe_explore(page: dict[str, Any] | None, first_page_pks: set[str]) -> dict[str, Any]:
   answer = page or {}
   max_id = answer.get("max_id")
   pks = media_pks(answer.get("sectional_items"))

   return {
      "answered": page is not None,
      "sectional_items": len(answer.get("sectional_items") or []),
      "media": len(pks),
      "overlap_with_first_page": len(pks & first_page_pks),
      "more_available": answer.get("more_available"),
      "max_id_length": length_of(max_id),
      "max_id_equals_session_paging_token": max_id == answer.get("session_paging_token"),
      "next_max_id": answer.get("next_max_id"),
      "rank_token_length": length_of(answer.get("rank_token")),
   }


async def explore_stage(replay: E2Replay) -> None:
   first_page = await replay.send(
      "explore grid first page",
      build_explore_grid_request(
         replay.session,
         web_session_id=replay.web_session_id,
         user_agent=replay.user_agent,
      ),
   )
   first_page_pks = media_pks((first_page or {}).get("sectional_items"))
   replay.record("explore_first", describe_explore(first_page, set()))

   if first_page is not None:
      replay.shape("explore_first_page", first_page)

   max_id = (first_page or {}).get("max_id")
   has_more = bool((first_page or {}).get("more_available"))
   has_cursor = isinstance(max_id, str) and bool(max_id)
   should_read_next_page = has_more and has_cursor

   if not should_read_next_page:
      replay.record("explore_next_page", "not sent, the first page offered no root max_id")

      return

   hypothesis = read_hypothesis("read-the-explore-grid-next-page")
   params = dict(hypothesis.template or {})
   params["max_id"] = max_id

   for attempt in (1, 2):
      page = await replay.rest(
         f"explore grid next page {attempt}",
         hypothesis.url,
         referer=EXPLORE_REFERER,
         params=params,
      )
      replay.record(f"explore_next_{attempt}", describe_explore(page, first_page_pks))

      if page is not None:
         replay.shape("explore_next_page", page)


def audio_candidates(connection: Any) -> list[dict[str, Any]]:
   """One entry per reel that names an audio id, licensed music first, trending music first."""

   candidates = []

   for edge in dig(connection, "edges") or []:
      media = dig(edge, "node", "media")
      cluster_id = dig(
         media, "clips_metadata", "music_info", "music_asset_info", "audio_cluster_id"
      )
      asset_id = dig(media, "clips_metadata", "original_sound_info", "audio_asset_id")
      is_trending = dig(
         media, "clips_metadata", "music_info", "music_consumption_info", "is_trending_in_clips"
      )

      if cluster_id:
         candidates.append(
            {"audio_id": str(cluster_id), "kind": "music", "trending": is_trending is True}
         )
      elif asset_id:
         candidates.append({"audio_id": str(asset_id), "kind": "original", "trending": False})

   return sorted(candidates, key=audio_preference)


def audio_preference(candidate: dict[str, Any]) -> tuple[bool, bool]:
   return candidate["kind"] != "music", not candidate["trending"]


def reel_pks(connection: Any) -> list[str]:
   pks = [dig(edge, "node", "media", "pk") for edge in dig(connection, "edges") or []]

   return [str(pk) for pk in pks if pk is not None]


def describe_audio(answer: dict[str, Any] | None, first_page_pks: set[str]) -> dict[str, Any]:
   payload = dig(answer, "payload") or {}
   pks = media_pks(payload.get("items"))
   paging = payload.get("paging_info") or {}

   return {
      "answered": answer is not None,
      "wrapper_keys": sorted(answer.keys()) if isinstance(answer, dict) else None,
      "items": len(payload.get("items") or []),
      "overlap_with_first_page": len(pks & first_page_pks),
      "first_item_prefix": id_prefix(dig(payload, "items", 0, "media", "pk")),
      "more_available": paging.get("more_available"),
      "max_id_length": length_of(paging.get("max_id")),
      "media_count": payload.get("media_count"),
      "is_music_page_restricted": payload.get("is_music_page_restricted"),
      "available_tabs": len(payload.get("available_tabs") or []),
      "carries_spotify_track_metadata": "spotify_track_metadata" in payload,
   }


async def audio_stage(replay: E2Replay) -> None:
   first_reels = await replay.engine_read(
      "reels feed first page",
      build_reels_feed_first_page_request(replay.session, user_agent=replay.user_agent),
   )
   connection = dig(first_reels, *REELS_CONNECTION)
   candidates = audio_candidates(connection)
   offers_music = any(candidate["kind"] == "music" for candidate in candidates)
   cursor = dig(connection, "page_info", "end_cursor")
   has_next_reels = bool(dig(connection, "page_info", "has_next_page"))
   should_read_more_reels = not offers_music and has_next_reels and isinstance(cursor, str)

   if should_read_more_reels:
      more_reels = await replay.engine_read(
         "reels feed next page",
         build_reels_feed_next_page_request(
            replay.session,
            cursor=cursor,
            seen_reel_pks=reel_pks(connection),
            user_agent=replay.user_agent,
         ),
      )
      more_candidates = audio_candidates(dig(more_reels, *REELS_CONNECTION))
      candidates = sorted(more_candidates + candidates, key=audio_preference)

   replay.record(
      "audio_candidates",
      {
         "music": sum(1 for candidate in candidates if candidate["kind"] == "music"),
         "original": sum(1 for candidate in candidates if candidate["kind"] == "original"),
         "trending_music": sum(1 for candidate in candidates if candidate["trending"]),
      },
   )

   if not candidates:
      replay.record("audio_page", "not sent, no reel named an audio id")

      return

   chosen = candidates[0]
   audio_id = chosen["audio_id"]
   replay.record(
      "audio_chosen",
      {"kind": chosen["kind"], "trending": chosen["trending"], "prefix": id_prefix(audio_id)},
   )

   hypothesis = read_hypothesis("read-an-audio-page")
   referer = f"{ORIGIN}/reels/audio/{audio_id}/"
   form = {"audio_cluster_id": audio_id, "max_id": "", "original_sound_audio_asset_id": audio_id}
   first_page = None

   for attempt in (1, 2):
      answer = await replay.rest(
         f"audio page {attempt}",
         hypothesis.url,
         referer=referer,
         form=form,
         comet_route=AUDIO_ROUTE,
      )
      replay.record(f"audio_first_{attempt}", describe_audio(answer, set()))

      if answer is not None:
         replay.shape("audio_page", dig(answer, "payload"))
         first_page = first_page or answer

   first_payload = dig(first_page, "payload") or {}
   next_max_id = dig(first_payload, "paging_info", "max_id")
   has_more = bool(dig(first_payload, "paging_info", "more_available"))
   has_cursor = isinstance(next_max_id, str) and bool(next_max_id)
   should_read_next_page = has_more and has_cursor

   if not should_read_next_page:
      replay.record("audio_next_page", "not sent, the first page offered no more_available cursor")

      return

   first_page_pks = media_pks(first_payload.get("items"))
   next_form = {**form, "max_id": next_max_id}

   for attempt in (1, 2):
      answer = await replay.rest(
         f"audio page next page {attempt}",
         hypothesis.url,
         referer=referer,
         form=next_form,
         comet_route=AUDIO_ROUTE,
      )
      replay.record(f"audio_next_{attempt}", describe_audio(answer, first_page_pks))

      if answer is not None:
         replay.shape("audio_next_page", dig(answer, "payload"))


def describe_mutual(page: dict[str, Any] | None) -> dict[str, Any]:
   answer = page or {}
   users = answer.get("users") or []
   next_max_id = answer.get("next_max_id")

   return {
      "answered": page is not None,
      "users": len(users),
      "first_user_prefix": id_prefix(users[0].get("pk")) if users else None,
      "big_list": answer.get("big_list"),
      "page_size": answer.get("page_size"),
      "next_max_id_type": type(next_max_id).__name__,
      "next_max_id_length": len(str(next_max_id)) if next_max_id is not None else None,
      "status": answer.get("status"),
   }


async def mutual_stage(replay: E2Replay) -> None:
   following = await replay.send(
      "following first page",
      build_following_request(
         replay.session,
         replay.viewer_id,
         web_session_id=replay.web_session_id,
         user_agent=replay.user_agent,
      ),
   )
   rows = (following or {}).get("users") or []
   public_rows = [
      row
      for row in rows
      if row.get("is_private") is False and row.get("pk") and row.get("username")
   ]
   replay.record("following_rows", {"rows": len(rows), "public": len(public_rows)})

   best: dict[str, Any] | None = None
   read_counts = []

   for row in public_rows[:MAX_CANDIDATES]:
      account_id = str(row["pk"])
      payload = await replay.engine_read(
         f"candidate profile {len(read_counts) + 1}",
         build_profile_request(
            replay.session,
            account_id,
            username_for_referer=row["username"],
            user_agent=replay.user_agent,
         ),
      )
      count = dig(payload, "data", "user", "mutual_followers_count")
      read_counts.append(count if isinstance(count, int) else None)
      has_mutuals = isinstance(count, int) and count > 0
      beats_best = has_mutuals and (best is None or count > best["count"])

      if beats_best:
         best = {"id": account_id, "username": row["username"], "count": count}

      has_more_than_a_page = best is not None and best["count"] > MUTUAL_PAGE_LIMIT

      if has_more_than_a_page:
         break

   replay.record("candidate_mutual_counts", read_counts)

   if best is None:
      replay.record("mutual_followers", "not sent, no candidate had a mutual follower")

      return

   replay.record("mutual_chosen", {"prefix": id_prefix(best["id"]), "count": best["count"]})

   hypothesis = read_hypothesis("read-mutual-followers")
   url = hypothesis.url.format(user_id=best["id"])
   referer = f"{ORIGIN}/{best['username']}/"
   first_page = None

   for attempt in (1, 2):
      page = await replay.rest(
         f"mutual followers page {attempt}",
         url,
         referer=referer,
         params={"page_size": MUTUAL_PAGE_SIZE},
      )
      replay.record(f"mutual_first_{attempt}", describe_mutual(page))

      if page is not None:
         replay.shape("mutual_followers_page", page)
         first_page = first_page or page

   next_max_id = (first_page or {}).get("next_max_id")
   has_more_than_a_page = best["count"] > MUTUAL_PAGE_LIMIT
   has_cursor = next_max_id is not None and str(next_max_id) != ""
   should_try_next_page = has_more_than_a_page and has_cursor

   if not should_try_next_page:
      replay.record(
         "mutual_next_page",
         "not sent, the account has 12 or fewer or the first page carried no next_max_id",
      )

      return

   first_ids = {user.get("pk") for user in (first_page or {}).get("users") or []}
   page = await replay.rest(
      "mutual next page by next_max_id, inference",
      url,
      referer=referer,
      params={"page_size": MUTUAL_PAGE_SIZE, "max_id": str(next_max_id)},
   )
   users = (page or {}).get("users") or []
   overlap = sum(1 for user in users if user.get("pk") in first_ids)
   replay.record("mutual_next", describe_mutual(page) | {"overlap_with_first_page": overlap})


def plan(stages: list[str]) -> tuple[int, int]:
   planned = 1 + sum(STAGE_REQUESTS[stage] for stage in stages)
   conditional = sum(STAGE_CONDITIONAL[stage] for stage in stages)

   return planned, conditional


def body_for(stages: list[str]) -> Any:
   async def body(replay: E2Replay) -> None:
      replay.record("stages", stages)

      await replay.bootstrap()

      for stage in stages:
         if stage == "explore":
            await explore_stage(replay)
         elif stage == "audio":
            await audio_stage(replay)
         elif stage == "mutual":
            await mutual_stage(replay)

   return body


def main() -> int:
   parser = argparse.ArgumentParser(description="E2 batch 11e, the last four reads' replays.")
   parser.add_argument("--stage", action="append", choices=STAGES)
   arguments = parser.parse_args()
   chosen = arguments.stage or list(STAGES)
   stages = [stage for stage in STAGES if stage in chosen]
   planned, conditional = plan(stages)

   return asyncio.run(run_probe(KIND, planned, conditional, body_for(stages)))


if __name__ == "__main__":
   sys.exit(main())
