"""Read only. Five live requests: two replays of each read the doctor saw drift, and one read
that supplies the second one's argument.

`dumpsta doctor --live` of 2026-09-24 found two reads whose bundles compile a different `doc_id`
from the stored one, while both stored ids still answered. The rule for moving a read to a new
id is two live replays of the new one, so this probe sends each drifted query twice with the
id the bundles compile, built with the capability's own request builder and read with its own
mapper, as the canary does.

The ids are read out of the doctor's JSON log given with `--doctor-log`, never typed here. The
query constant each builder reads is swapped for a copy carrying the compiled id, for this
process only.

   1. the home timeline, first page, compiled id
   2. the home timeline, the page after it by its end cursor, compiled id
   3. the viewer's own profile by `ds_user_id`, stored id, not drifted, for the username
   4. the profile posts query for that username, one post, compiled id
   5. the profile posts query for that username, twelve posts as the profile page asks, compiled id

A checkpoint or a throttle ends the run at once and nothing is retried. Recorded: statuses,
lengths, item counts, cursor lengths, whether the account id read back is the viewer's. No
username, no id of anyone else's content, no token.

Run it from `engine/` with:

   uv run python probes/doctor_drift_replay.py --doctor-log logs/doctor-live-<stamp>.json
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs

from _probe_support import SESSION_PATH, load_env, report_run

import dumpstagram._private.web.requests.feed as feed_requests
import dumpstagram._private.web.requests.profiles as profile_requests
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import HttpxTransport, Request, cookies_for
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, INSTAGRAM_HOST, ORIGIN
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.documents.feed import HOME_TIMELINE_FEED
from dumpstagram._private.web.documents.profiles import PROFILE_POSTS
from dumpstagram._private.web.parse.feed import parse_feed_page
from dumpstagram._private.web.parse.profiles import parse_profile, parse_user_id
from dumpstagram._private.web.requests.common import build_graphql_request
from dumpstagram.errors import CheckpointRequired, DumpstagramError, RateLimited
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE")
PROBE_SPACING_SECONDS = 2.85
REQUESTS_PLANNED = 5


def drifted_ids(doctor_log: Path) -> dict[str, str]:
   report = json.loads(doctor_log.read_text(encoding="utf-8"))
   compiled: dict[str, str] = {}

   for check in report["operations"]:
      is_drift = check["bundle"] == "drift"
      has_one_compiled_id = len(check["compiled_doc_ids"]) == 1

      if is_drift and has_one_compiled_id:
         compiled[check["operation"]] = check["compiled_doc_ids"][0]

   return compiled


def profile_page_posts_request(session: Session, username: str, user_agent: str) -> Request:
   return build_graphql_request(
      session,
      profile_requests.PROFILE_POSTS,
      profile_requests._profile_posts_variables(username, profile_requests.PROFILE_PAGE_POSTS),
      referer=f"{ORIGIN}/{username}/",
      user_agent=user_agent,
   )


async def run(doctor_log: Path) -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}
   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT") or DEFAULT_USER_AGENT

   compiled = drifted_ids(doctor_log)
   feed_id = compiled.get(HOME_TIMELINE_FEED.friendly_name)
   posts_id = compiled.get(PROFILE_POSTS.friendly_name)

   report: dict[str, object] = {
      "doctor_log": doctor_log.name,
      "requests_planned": REQUESTS_PLANNED,
      "feed": {"stored_doc_id": HOME_TIMELINE_FEED.doc_id, "replayed_doc_id": feed_id},
      "profile_posts": {"stored_doc_id": PROFILE_POSTS.doc_id, "replayed_doc_id": posts_id},
   }

   both_drifted = feed_id is not None and posts_id is not None

   if not both_drifted:
      report["failed_with"] = "the doctor log does not name both drifted reads"
      report["requests_spent"] = 0
      report_run("doctor-drift-replay-failed", report)

      return 2

   feed_requests.HOME_TIMELINE_FEED = dataclasses.replace(HOME_TIMELINE_FEED, doc_id=feed_id)
   profile_requests.PROFILE_POSTS = dataclasses.replace(PROFILE_POSTS, doc_id=posts_id)

   session = Session.load(session_path)
   account = HttpxTransport(
      cookies=cookies_for(session), proxy=session.proxy, allowed_host=INSTAGRAM_HOST
   )
   replays: list[dict[str, object]] = []
   spent = 0
   started_at = time.monotonic()

   async def send(label: str, request: Request) -> object:
      nonlocal spent

      if spent:
         await asyncio.sleep(PROBE_SPACING_SECONDS)

      response = await sender.send(request)
      spent += 1

      replays.append(
         {
            "label": label,
            "doc_id_sent": request_doc_id(request),
            "status": response.status_code,
            "chars": len(response.text),
         }
      )

      return classify(response)

   try:
      async with PacedSender(account, Pacer()) as sender:
         first_request = feed_requests.build_feed_page_request(session, user_agent=user_agent)
         first = parse_feed_page(await send("feed page one", first_request))
         replays[-1]["items"] = len(first.items)
         replays[-1]["has_next_page"] = first.has_next_page
         replays[-1]["end_cursor_chars"] = len(first.end_cursor or "")

         second_request = feed_requests.build_feed_page_request(
            session, after=first.end_cursor, user_agent=user_agent
         )
         second = parse_feed_page(await send("feed page two", second_request))
         replays[-1]["items"] = len(second.items)
         replays[-1]["has_next_page"] = second.has_next_page

         profile_request = profile_requests.build_profile_request(
            session, session.ds_user_id, user_agent=user_agent
         )
         profile = parse_profile(await send("own profile by id, stored id", profile_request))
         username = profile.username

         one_post_request = profile_requests.build_username_resolution_request(
            session, username, user_agent=user_agent
         )
         resolved = parse_user_id(await send("profile posts, one post", one_post_request))
         replays[-1]["account_id_is_the_viewer"] = resolved == session.ds_user_id

         page_posts_request = profile_page_posts_request(session, username, user_agent)
         resolved_again = parse_user_id(
            await send("profile posts, twelve posts", page_posts_request)
         )
         replays[-1]["account_id_is_the_viewer"] = resolved_again == session.ds_user_id
   except (CheckpointRequired, RateLimited) as stop:
      report["stopped_with"] = type(stop).__name__
      report["replays"] = replays
      report["requests_spent"] = spent
      report_run("doctor-drift-replay-stopped", report)

      return 4
   except DumpstagramError as failure:
      report["failed_with"] = type(failure).__name__
      report["failure_code"] = getattr(failure, "code", None)
      report["replays"] = replays
      report["requests_spent"] = spent
      report_run("doctor-drift-replay-failed", report)

      return 3

   report["replays"] = replays
   report["requests_spent"] = spent
   report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
   report_run("doctor-drift-replay", report)

   return 0


def request_doc_id(request: Request) -> str | None:
   form = parse_qs((request.content or b"").decode("utf-8"))
   doc_ids = form.get("doc_id") or [None]

   return doc_ids[0]


def parse_arguments() -> argparse.Namespace:
   parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
   parser.add_argument("--doctor-log", type=Path, required=True)

   return parser.parse_args()


if __name__ == "__main__":
   sys.exit(asyncio.run(run(parse_arguments().doctor_log)))
