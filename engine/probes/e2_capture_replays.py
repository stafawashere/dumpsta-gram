"""Read only. Not run yet. Twenty-seven requests for every stage, and up to seven more, conditional.

E2 batch 11, the engine replays of what the capture night of ``run-2026-09-27-131354`` recorded
in the browser. Each hypothesis read is replayed twice. ``--stage`` picks the stages to run, and
may be given more than once, so a night can spend part of the batch. With no ``--stage`` every
stage runs. Every run first spends the bootstrap, and the profile, saved and post stages share
one read of the owner's profile by id for the username their referers and the grid need.

   shared
      1  the inbox document, for fresh tokens (the bootstrap)
      1  the owner's profile by id, a verified read, when profile, saved or post runs
   profile, 8 and up to 2 conditional, 10 alone
      2  the owner's reels tab, PolarisProfileReelsTabContentQuery, twice
      2  the owner's tagged tab, PolarisProfileTaggedTabContentQuery, twice
      2  the owner's following, GET /api/v1/friendships/<id>/following/ with count 12, twice
      2  its next page with max_id the first page's numeric next_max_id, twice
   search, 4 and up to 2 conditional, 5 alone
      2  the personalised typeahead, PolarisSearchBoxRefetchableQuery, twice
      2  the keyword results grid, PolarisKeywordSearchExplorePageRelayQuery, twice
   reels, 4 and up to 2 conditional, 5 alone
      2  the reels tab's first page, PolarisClipsTabDesktopContainerQuery, twice
      2  its next page, PolarisClipsTabDesktopPaginationQuery, twice
   saved, 4 and up to 1 conditional, 6 alone
      2  the saved tab's collections, PolarisProfileSavedTabContentQuery, twice
      2  the saved all-posts view, GET /api/v1/feed/saved/posts/, twice
   close-friends, 2, 3 alone
      2  the close friends list, the Bloks app fetch of its settings screen, twice
   post, 3, 5 alone
      1  the owner's posts grid first page, the verified PolarisProfilePostsQuery, for a code
      2  the post page document, twice, checked for the five queries it preloads

Conditional: each GraphQL hypothesis read's first replay is sent once more on the other path
when every root is null, seven at most. A next page is sent only when its first page answered
one. Alone means the stage run by itself, the bootstrap and the profile read included.

Arguments come from verified reads or from the answers before them: the username from the
owner's profile by id, the following cursor from its first page, the reels cursor and the one
entry of ``seen_reels`` from the reels first page, and the post code from the owner's grid.
The typeahead and the keyword grid each get a lowercase uuid4 made here, as the browser made
one per search session and per keyword page, and the keyword grid sends it as both of its ids.
The query text is ``IG_E2_SEARCH_QUERY`` from the root ``.env``, ``instagram`` when absent, and
is never logged. Typing a query registers no recent search, since nothing is clicked.

Not replayed:

   read-the-story-archive-grid   goes out as a comet GET carrying fb_dtsg_ag, a token the
                                 bootstrap does not harvest and whose source in the document
                                 was never observed
   read-archived-story-days      its reel_ids are the grid's archiveDay ids, so it waits on
                                 the grid
   report-a-reel-video-view      a view report, unified_cvc
   read-the-reels-ads-pool       an ads pool
   close_friend_count_updater    a Bloks action whose effect is UNRESOLVED; only the app fetch
                                 is sent

The close friends app fetch is a POST that reads: type app, params ``{}``, no action. Its form
is the comet envelope without the fields the engine has never produced, the subset the delete
post form sends, and ``__bkv`` is the Bloks version id the bootstrap reads. The post page
document's body is not kept, since it carries the page tokens; only the five preloaded results
are, beside the other answers under the skill's ``var/captures/``. Everything read is the
owner's own, offered to the owner, or a public search, and nothing is visible to anyone else.

Run it from `engine/` with one of:

   uv run python probes/e2_capture_replays.py
   uv run python probes/e2_capture_replays.py --stage profile
   uv run python probes/e2_capture_replays.py --stage search
   uv run python probes/e2_capture_replays.py --stage reels
   uv run python probes/e2_capture_replays.py --stage saved
   uv run python probes/e2_capture_replays.py --stage close-friends
   uv run python probes/e2_capture_replays.py --stage post

Every run writes an ``e2-capture-replays`` log, and ``e2_record_verifications.py`` reads only
the newest one, so record each stage's run before the next stage runs.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
import uuid
from typing import Any
from urllib.parse import quote, urlencode

from _e2_support import (
   E2Replay,
   dig,
   id_prefix,
   page_info_of,
   read_hypothesis,
   run_probe,
)
from _probe_support import load_env

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import ORIGIN
from dumpstagram._private.web.documents.profiles import PROFILE_POSTS
from dumpstagram._private.web.parse.profiles import parse_profile
from dumpstagram._private.web.preload import read_preloaded_result
from dumpstagram._private.web.requests.common import build_graphql_request, jazoest_for
from dumpstagram._private.web.requests.profiles import (
   _profile_posts_variables,
   build_profile_request,
)
from dumpstagram.errors import SchemaChanged

KIND = "e2-capture-replays"
STAGES = ("profile", "search", "reels", "saved", "close-friends", "post")
STAGE_REQUESTS = {
   "profile": 8,
   "search": 4,
   "reels": 4,
   "saved": 4,
   "close-friends": 2,
   "post": 3,
}
STAGE_CONDITIONAL = {
   "profile": 2,
   "search": 2,
   "reels": 2,
   "saved": 1,
   "close-friends": 0,
   "post": 0,
}
STAGES_NEEDING_USERNAME = {"profile", "saved", "post"}
DEFAULT_TERM = "instagram"
GRID_PAGE_SIZE = 12
FOLLOWING_PAGE = {"count": "12"}
CLOSE_FRIENDS_ROUTE = "comet.igweb.PolarisSettingsCloseFriendsRoute"
BLOKS_VERSION_PLACEHOLDER = "<bloks version hash>"
POST_PAGE_PRELOADS = (
   "usePolarisNotificationsNavItemQuery",
   "PolarisGatingTransparencyPageIsCannesStatedQuery",
   "PolarisPostCommentsContainerQuery",
   "PolarisPostRootQuery",
   "PolarisDesktopPostPageRelatedMediaGridQuery",
)


def template_of(finding_id: str) -> dict[str, Any]:
   return copy.deepcopy(read_hypothesis(finding_id).template or {})


def unfilled_paths(value: Any, path: str = "") -> list[str]:
   """Every place in ``value`` still holding a template placeholder, ``<...>``."""

   if isinstance(value, dict):
      return [
         found
         for key, inner in value.items()
         for found in unfilled_paths(inner, f"{path}.{key}" if path else key)
      ]

   is_placeholder = isinstance(value, str) and value.startswith("<") and value.endswith(">")

   return [path] if is_placeholder else []


def refuses_unfilled(replay: E2Replay, label: str, variables: dict[str, Any]) -> bool:
   unfilled = unfilled_paths(variables)

   if unfilled:
      replay.record(f"{label}_skipped", {"unfilled": unfilled})

   return bool(unfilled)


def client_uuid() -> str:
   return str(uuid.uuid4())


async def profile_stage(replay: E2Replay, username: str) -> None:
   viewer_id = replay.viewer_id
   profile_page = f"{ORIGIN}/{username}/"

   reels_variables = template_of("read-a-profile-s-reels-tab")
   reels_variables["data"]["target_user_id"] = viewer_id
   reels_variables["user_id"] = viewer_id

   for attempt in (1, 2):
      reels = await replay.graphql(
         "read-a-profile-s-reels-tab",
         reels_variables,
         referer=f"{profile_page}reels/",
         label=f"profile reels tab {attempt}",
         try_other_path_on_null=attempt == 1,
      )

      if reels is not None:
         replay.shape("profile_reels_tab", dig(reels, "data"))

   tagged_variables = template_of("read-a-profile-s-tagged-tab")
   tagged_variables["user_id"] = viewer_id

   for attempt in (1, 2):
      tagged = await replay.graphql(
         "read-a-profile-s-tagged-tab",
         tagged_variables,
         referer=f"{profile_page}reels/",
         label=f"profile tagged tab {attempt}",
         try_other_path_on_null=attempt == 1,
      )
      connection = dig(tagged, "data", "xdt_api__v1__usertags__user_id__feed_connection")
      replay.record(f"tagged_{attempt}", page_info_of(connection))

      if tagged is not None:
         replay.shape("profile_tagged_tab", connection)

   following_url = read_hypothesis("read-an-account-s-following").url.format(user_id=viewer_id)
   first_page = None

   for attempt in (1, 2):
      page = await replay.rest(
         f"following first page {attempt}",
         following_url,
         referer=profile_page,
         params=FOLLOWING_PAGE,
      )
      replay.record(f"following_first_{attempt}", describe_following(page))

      if page is not None:
         replay.shape("following_page", page)
         first_page = first_page or page

   next_max_id = (first_page or {}).get("next_max_id")
   has_more = bool((first_page or {}).get("has_more"))
   has_numeric_cursor = isinstance(next_max_id, str) and next_max_id.isdigit()
   should_read_next_page = has_more and has_numeric_cursor

   if not should_read_next_page:
      replay.record("following_next_page", "not sent, the first page offered no numeric cursor")

      return

   first_ids = {user.get("pk") for user in (first_page or {}).get("users") or []}

   for attempt in (1, 2):
      page = await replay.rest(
         f"following next page {attempt}",
         following_url,
         referer=profile_page,
         params={**FOLLOWING_PAGE, "max_id": next_max_id},
      )
      users = (page or {}).get("users") or []
      overlap = sum(1 for user in users if user.get("pk") in first_ids)
      replay.record(
         f"following_next_{attempt}",
         describe_following(page) | {"overlap_with_first_page": overlap},
      )


def describe_following(page: dict[str, Any] | None) -> dict[str, Any]:
   answer = page or {}
   users = answer.get("users") or []
   next_max_id = answer.get("next_max_id")

   return {
      "users": len(users),
      "first_user_prefix": id_prefix(users[0].get("pk")) if users else None,
      "next_max_id_is_numeric": isinstance(next_max_id, str) and next_max_id.isdigit(),
      "next_max_id_length": len(next_max_id) if isinstance(next_max_id, str) else None,
      "has_more": answer.get("has_more"),
      "big_list": answer.get("big_list"),
   }


async def search_stage(replay: E2Replay, query: str) -> None:
   for attempt in (1, 2):
      variables = template_of("search-typeahead-personalised-as-sent")
      variables["data"]["query"] = query
      variables["data"]["rank_token"] = ""
      variables["data"]["search_session_id"] = client_uuid()

      if refuses_unfilled(replay, "personalised_typeahead", variables):
         break

      typeahead = await replay.graphql(
         "search-typeahead-personalised-as-sent",
         variables,
         referer=f"{ORIGIN}/",
         label=f"personalised typeahead {attempt}",
         try_other_path_on_null=attempt == 1,
      )
      connection = dig(typeahead, "data", "xdt_api__v1__fbsearch__topsearch_connection")
      rank_token = dig(connection, "rank_token")
      replay.record(
         f"typeahead_{attempt}",
         {
            "users": len(dig(connection, "users") or []),
            "hashtags": len(dig(connection, "hashtags") or []),
            "places": len(dig(connection, "places") or []),
            "rank_token_length": len(rank_token) if isinstance(rank_token, str) else None,
         },
      )

      if typeahead is not None:
         replay.shape("personalised_typeahead", dig(typeahead, "data"))

   keyword_query = urlencode({"q": query}, quote_via=quote)
   keyword_page = f"{ORIGIN}/explore/search/keyword/?{keyword_query}"

   for attempt in (1, 2):
      page_session = client_uuid()
      variables = template_of("read-keyword-search-results")
      variables["query"] = query
      variables["search_session_id"] = page_session
      variables["serp_session_id"] = page_session

      if refuses_unfilled(replay, "keyword_results", variables):
         break

      results = await replay.graphql(
         "read-keyword-search-results",
         variables,
         referer=keyword_page,
         label=f"keyword results {attempt}",
         try_other_path_on_null=attempt == 1,
      )

      if results is not None:
         replay.shape("keyword_results", dig(results, "data"))


async def reels_stage(replay: E2Replay) -> None:
   reels_page = f"{ORIGIN}/reels/"
   first_page = None

   for attempt in (1, 2):
      page = await replay.graphql(
         "read-the-reels-tab-first-page",
         template_of("read-the-reels-tab-first-page"),
         referer=reels_page,
         label=f"reels feed first page {attempt}",
         try_other_path_on_null=attempt == 1,
      )
      connection = dig(page, "data", "xdt_api__v1__clips__home__connection_v2")
      replay.record(f"reels_first_{attempt}", page_info_of(connection))

      if page is not None:
         replay.shape("reels_feed_first_page", connection)
         first_page = first_page or connection

   cursor = dig(first_page, "page_info", "end_cursor")
   first_reel_pk = dig(first_page, "edges", 0, "node", "media", "pk")
   has_next_page = bool(dig(first_page, "page_info", "has_next_page"))
   should_read_next_page = has_next_page and isinstance(cursor, str) and first_reel_pk is not None

   if not should_read_next_page:
      replay.record("reels_next_page", "not sent, the first page offered no cursor or reel")

      return

   variables = template_of("read-the-reels-tab-next-page")
   variables["after"] = cursor
   variables["data"]["seen_reels"] = json.dumps([{"id": str(first_reel_pk)}], separators=(",", ":"))

   if refuses_unfilled(replay, "reels_next_page", variables):
      return

   for attempt in (1, 2):
      page = await replay.graphql(
         "read-the-reels-tab-next-page",
         variables,
         referer=reels_page,
         label=f"reels feed next page {attempt}",
         try_other_path_on_null=attempt == 1,
      )
      connection = dig(page, "data", "xdt_api__v1__clips__home__connection_v2")
      first_node_pk = dig(connection, "edges", 0, "node", "media", "pk")
      replay.record(
         f"reels_next_{attempt}",
         page_info_of(connection) | {"first_reel_prefix": id_prefix(first_node_pk)},
      )

      if page is not None:
         replay.shape("reels_feed_next_page", connection)


async def saved_stage(replay: E2Replay, username: str) -> None:
   saved_page = f"{ORIGIN}/{username}/saved/"

   for attempt in (1, 2):
      collections = await replay.graphql(
         "read-saved-posts",
         template_of("read-saved-posts"),
         referer=saved_page,
         label=f"saved collections tab {attempt}",
         try_other_path_on_null=attempt == 1,
      )

      if collections is not None:
         replay.shape("saved_collections_tab", dig(collections, "data"))

   all_posts_url = read_hypothesis("read-all-saved-posts").url

   for attempt in (1, 2):
      posts = await replay.rest(
         f"all saved posts {attempt}",
         all_posts_url,
         referer=f"{saved_page}all-posts/",
      )
      next_max_id = (posts or {}).get("next_max_id")
      replay.record(
         f"all_saved_posts_{attempt}",
         {
            "items": len((posts or {}).get("items") or []),
            "num_results": (posts or {}).get("num_results"),
            "more_available": (posts or {}).get("more_available"),
            "next_max_id_length": len(next_max_id) if isinstance(next_max_id, str) else None,
         },
      )

      if posts is not None:
         replay.shape("all_saved_posts", posts)


def build_close_friends_request(replay: E2Replay, url: str) -> Request:
   session = replay.session
   spin = session.spin
   revision = (spin.revision if spin is not None else None) or ""
   fb_dtsg = session.fb_dtsg or ""
   form = {
      "__d": "www",
      "__user": "0",
      "__a": "1",
      "__req": "1",
      "__hs": session.haste_session or "",
      "dpr": "2",
      "__ccg": "EXCELLENT",
      "__rev": revision,
      "__hsi": session.hsi or "",
      "__comet_req": "7",
      "fb_dtsg": fb_dtsg,
      "jazoest": jazoest_for(fb_dtsg),
      "lsd": session.lsd or "",
      "__spin_r": revision,
      "__spin_b": (spin.branch if spin is not None else None) or "",
      "__spin_t": (spin.timestamp if spin is not None else None) or "",
      "__crn": CLOSE_FRIENDS_ROUTE,
      "params": "{}",
   }
   headers = {
      "accept": "*/*",
      "accept-language": "en-US,en;q=0.9",
      "content-type": "application/x-www-form-urlencoded",
      "origin": ORIGIN,
      "referer": f"{ORIGIN}/accounts/close_friends/",
      "sec-fetch-dest": "empty",
      "sec-fetch-mode": "cors",
      "sec-fetch-site": "same-origin",
      "user-agent": replay.user_agent,
   }

   return Request(
      method="POST",
      url=url,
      headers=headers,
      content=urlencode(form).encode("ascii"),
      follow_redirects=False,
   )


async def close_friends_stage(replay: E2Replay) -> None:
   bloks_version = replay.session.bloks_version_id

   if not bloks_version:
      replay.record("close_friends_skipped", "the bootstrap carried no Bloks version id")

      return

   finding_url = read_hypothesis("read-the-close-friends-list").url
   url = finding_url.replace(BLOKS_VERSION_PLACEHOLDER, bloks_version)

   for attempt in (1, 2):
      answer = await replay.send(
         f"close friends list {attempt}", build_close_friends_request(replay, url)
      )
      bloks_payload = dig(answer, "payload", "layout", "bloks_payload")
      replay.record(
         f"close_friends_{attempt}",
         {
            "payload_keys": sorted(dig(answer, "payload") or {}),
            "bloks_payload_keys": sorted(bloks_payload or {}),
            "data_entries": len(dig(bloks_payload, "data") or []),
         },
      )


async def post_stage(replay: E2Replay, username: str) -> None:
   grid = await replay.engine_read(
      "posts grid first page",
      build_graphql_request(
         replay.session,
         PROFILE_POSTS,
         _profile_posts_variables(username, GRID_PAGE_SIZE),
         referer=f"{ORIGIN}/{username}/",
         user_agent=replay.user_agent,
      ),
   )
   code = dig(
      grid,
      "data",
      "xdt_api__v1__feed__user_timeline_graphql_connection",
      "edges",
      0,
      "node",
      "code",
   )

   if not isinstance(code, str):
      replay.record("post_page_skipped", "the owner's grid gave no post code")

      return

   for attempt in (1, 2):
      label = f"post page document {attempt}"
      html = await replay.document(label, f"{ORIGIN}/p/{code}/")

      if html is None:
         continue

      check_post_preloads(replay, label, attempt, html)


def check_post_preloads(replay: E2Replay, label: str, attempt: int, html: str) -> None:
   entry = replay.report["replays"][-1]
   found: dict[str, Any] = {}
   missing: list[str] = []

   for name in POST_PAGE_PRELOADS:
      try:
         found[name] = read_preloaded_result(html, f"adp_{name}RelayPreloader_")
      except SchemaChanged:
         missing.append(name)

   entry["root_fields"] = list(POST_PAGE_PRELOADS)
   entry["null_roots"] = missing

   if missing:
      entry["failed_with"] = "PreloadMissing"

   preloaded_roots = {
      name: sorted(dig(found[name], "data") or {}) if name in found else None
      for name in POST_PAGE_PRELOADS
   }
   replay.record(f"post_page_preloads_{attempt}", preloaded_roots)
   replay.keep_body(f"{label} preloads", found or None)

   if attempt == 1:
      for name, result in found.items():
         replay.shape(f"post_page_preload_{name}", dig(result, "data"))


def plan(stages: list[str]) -> tuple[int, int]:
   needs_username = any(stage in STAGES_NEEDING_USERNAME for stage in stages)
   planned = 1 + (1 if needs_username else 0) + sum(STAGE_REQUESTS[stage] for stage in stages)
   conditional = sum(STAGE_CONDITIONAL[stage] for stage in stages)

   return planned, conditional


def body_for(stages: list[str]) -> Any:
   async def body(replay: E2Replay) -> None:
      query = load_env().get("IG_E2_SEARCH_QUERY") or DEFAULT_TERM
      replay.record("stages", stages)
      replay.record("inputs", {"query_length": len(query)})

      await replay.bootstrap()

      username = None
      needs_username = any(stage in STAGES_NEEDING_USERNAME for stage in stages)

      if needs_username:
         profile_payload = await replay.engine_read(
            "own profile by id", build_profile_request(replay.session, replay.viewer_id)
         )
         username = parse_profile(profile_payload).username if profile_payload else None

         if username is None:
            replay.record("username_missing", "the own profile read gave no username")

      for stage in stages:
         is_blocked_on_username = stage in STAGES_NEEDING_USERNAME and username is None

         if is_blocked_on_username:
            replay.record(f"{stage}_skipped", "no username")

            continue

         if stage == "profile":
            await profile_stage(replay, username)
         elif stage == "search":
            await search_stage(replay, query)
         elif stage == "reels":
            await reels_stage(replay)
         elif stage == "saved":
            await saved_stage(replay, username)
         elif stage == "close-friends":
            await close_friends_stage(replay)
         elif stage == "post":
            await post_stage(replay, username)

   return body


def main() -> int:
   parser = argparse.ArgumentParser(description="E2 batch 11, the capture night's replays.")
   parser.add_argument("--stage", action="append", choices=STAGES)
   arguments = parser.parse_args()
   chosen = arguments.stage or list(STAGES)
   stages = [stage for stage in STAGES if stage in chosen]
   planned, conditional = plan(stages)

   return asyncio.run(run_probe(KIND, planned, conditional, body_for(stages)))


if __name__ == "__main__":
   sys.exit(main())
