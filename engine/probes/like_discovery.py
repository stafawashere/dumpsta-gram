"""Writes four times, on the owner's own post only. Eight live requests, nine with a bootstrap.

Two unlikes and two likes, or two likes and two unlikes, of the owner's newest post, approved
by the owner on 2026-09-23 for this one run. The post ends in the state it started in. A like
or its absence shows in the post's likers list to anyone who can see the post, which on a
private account is its approved followers, for the roughly two minutes between the pairs.

Step 15's discovery run, done from the engine side under ruling 23 in the build plan, which
allows no browser load tonight. It replays the three hypothesis contracts from Step 13.0,
``read-a-post-by-shortcode``, ``like-a-post`` and ``unlike-a-post``, with requests built by the
engine's own ``build_graphql_request`` and writes sent through ``send_write``, and answers:

- whether the shortcode read answers, and whether its item maps into ``Post``
- which identifier the mutations take, ``pk`` being the one sent, and what the answer echoes
- whether liking an already liked post, and unliking an unliked one, converges or errors,
  build plan 13.3
- whether ``has_liked`` and ``like_count`` follow each write and come back at the end

The owner's newest post read as already liked by the owner on the first attempt, and so did
all eight on the timeline's first page. Unliking and leaving it so would remove the owner's
own state, so the order follows the starting state: from liked it unlikes twice and likes
twice, from not liked it likes twice and unlikes twice.

The sequence is: one timeline read of one post to find it, a shortcode read, the first write
twice, a shortcode read, the reversing write twice, a shortcode read. The doc_id values live
in this file, not in the package, because none of the three findings was verified when it ran.

A rejected write stops its pair. If the post reads as changed after the first pair, the
reversing write is still sent to restore it, whatever else happened, and the log says whether
the post ended in its starting state.

Recorded: the post's ``pk``, key names of the read item, ``has_liked``, ``like_count``, each
write's answer shape and echoed flag, and timings. No caption, no username, no text.

It sends nothing without ``--approve like-cycle``. Run it from `engine/` with:

   uv run python probes/like_discovery.py --approve like-cycle
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import Any

from _probe_support import SESSION_PATH, load_env, report_run

from dumpstagram._core.pacer import Pacer, WritePolicy
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._core.writing import send_write
from dumpstagram._private.transport import (
   HttpxTransport,
   Request,
   Response,
   WriteRequest,
   cookies_for,
)
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, ORIGIN, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.documents import PersistedQuery
from dumpstagram._private.web.parse import parse_post
from dumpstagram._private.web.requests import (
   build_graphql_request,
   build_username_resolution_request,
)
from dumpstagram.errors import DumpstagramError
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_USERNAME", "IG_USER_AGENT", "IG_SESSION_FILE")

REQUEST_CAP = 9

POST_BY_SHORTCODE = PersistedQuery(
   doc_id="27830990013244856",
   friendly_name="PolarisPostRootQuery",
   finding_id="read-a-post-by-shortcode",
)
LIKE = PersistedQuery(
   doc_id="27182485238052618",
   friendly_name="usePolarisLikeMediaXIGLikeMutation",
   finding_id="like-a-post",
)
UNLIKE = PersistedQuery(
   doc_id="27345296031770102",
   friendly_name="usePolarisLikeMediaXIGUnlikeMutation",
   finding_id="unlike-a-post",
)

WRITE_POLICY = WritePolicy(stop_after_unrecognised_rejection=False)
"""The probe decides by hand which write follows a rejection, so the restoring unlike can go."""


class CappedTransport:
   def __init__(self, inner: HttpxTransport) -> None:
      self.inner = inner
      self.sent: list[dict[str, object]] = []
      self.started_at = time.monotonic()

   async def send(self, request: Request) -> Response:
      if len(self.sent) >= REQUEST_CAP:
         raise RuntimeError(f"refusing request {len(self.sent) + 1}, the cap is {REQUEST_CAP}")

      entry: dict[str, object] = {
         "name": request.headers.get("x-fb-friendly-name", "document"),
         "offset_ms": int((time.monotonic() - self.started_at) * 1000),
      }
      self.sent.append(entry)

      response = await self.inner.send(request)
      entry["status"] = response.status_code
      entry["length"] = len(response.content)

      return response

   async def aclose(self) -> None:
      await self.inner.aclose()


def post_url(code: str) -> str:
   return f"{ORIGIN}/p/{code}/"


def own_timeline_nodes(payload: Any, viewer_id: str) -> list[dict[str, Any]]:
   connection = payload.get("data", {}).get("xdt_api__v1__feed__user_timeline_graphql_connection")
   edges = connection.get("edges") if isinstance(connection, dict) else None
   own_nodes: list[dict[str, Any]] = []

   for edge in edges or []:
      node = edge.get("node") if isinstance(edge, dict) else None
      author = node.get("user") if isinstance(node, dict) else None
      author_id = str(author.get("pk") or author.get("id")) if isinstance(author, dict) else None
      is_own_post = node is not None and author_id == viewer_id

      if is_own_post and isinstance(node, dict):
         own_nodes.append(node)

   return own_nodes


def describe_read(payload: Any, pk: str) -> dict[str, object]:
   root = payload.get("data", {}).get("xdt_api__v1__media__shortcode__web_info")
   items = root.get("items") if isinstance(root, dict) else None

   if not isinstance(items, list) or not items:
      return {"root_is_object": isinstance(root, dict), "item_count": 0}

   item = items[0]
   described: dict[str, object] = {
      "root_keys": sorted(root.keys()),
      "item_count": len(items),
      "item_keys": sorted(item.keys()),
      "pk_matches": item.get("pk") == pk,
      "id_is_pk_underscore_owner": str(item.get("id", "")).startswith(f"{pk}_"),
      "has_liked": item.get("has_liked"),
      "like_count": item.get("like_count"),
      "is_seen_present": "is_seen" in item,
   }

   try:
      parse_post(item, "items[0]")
      described["maps_into_post"] = True
   except DumpstagramError as failure:
      described["maps_into_post"] = False
      described["mapping_failure"] = str(failure)[:200]

   return described


def describe_write_answer(payload: Any, root_field: str, pk: str) -> dict[str, object]:
   data = payload.get("data") if isinstance(payload, dict) else None
   root = data.get(root_field) if isinstance(data, dict) else None
   media = root.get("media") if isinstance(root, dict) else None

   described: dict[str, object] = {
      "top_level_keys": sorted(payload.keys()) if isinstance(payload, dict) else None,
      "root_present": isinstance(root, dict),
      "root_keys": sorted(root.keys()) if isinstance(root, dict) else None,
   }

   if isinstance(media, dict):
      echoed_id = str(media.get("id", ""))
      described["media_keys"] = sorted(media.keys())
      described["echoed_id_is_pk"] = echoed_id == pk
      described["echoed_id_is_pk_underscore_owner"] = echoed_id.startswith(f"{pk}_")
      described["echoed_has_liked"] = media.get("has_liked")

   return described


async def run(approved: bool) -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}

   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   username = environment.get("IG_USERNAME", "")
   user_agent = environment.get("IG_USER_AGENT") or DEFAULT_USER_AGENT

   report: dict[str, object] = {"session_path": str(session_path), "approved": approved}

   if not approved:
      report["failed_with"] = "not approved, pass --approve like-cycle"
      report_run("like-discovery-refused", report)

      return 2

   if not session_path.exists() or not username:
      report["failed_with"] = "no session file or no IG_USERNAME in .env"
      report_run("like-discovery-failed", report)

      return 2

   session = Session.load(session_path)
   transport = CappedTransport(HttpxTransport(cookies=cookies_for(session), proxy=session.proxy))
   mutation_counter = 0
   steps: list[dict[str, object]] = []
   report["steps"] = steps

   async with PacedSender(transport, Pacer(), writes=WRITE_POLICY) as sender:

      async def read_json(build: Any) -> Any:
         async def attempt() -> Any:
            if not session.fb_dtsg:
               await bootstrap(sender, session, user_agent=user_agent)

            return classify(await sender.send(build()))

         return await with_token_recovery(attempt, sender=sender, session=session)

      async def write(
         query: PersistedQuery, pk: str, code: str, root_field: str
      ) -> dict[str, object]:
         nonlocal mutation_counter
         mutation_counter += 1

         variables = {
            "input": {
               "client_mutation_id": str(mutation_counter),
               "media_id": pk,
               "tracking_token": None,
            }
         }
         request = build_graphql_request(
            session, query, variables, referer=post_url(code), user_agent=user_agent
         )
         step: dict[str, object] = {"write": query.friendly_name, "identifier_sent": "pk"}
         steps.append(step)

         try:
            payload = await send_write(sender, session, WriteRequest(request, query.friendly_name))
         except DumpstagramError as failure:
            step["failed_with"] = type(failure).__name__
            step["failure_code"] = getattr(failure, "code", None)
            step["failure_text"] = str(failure)[:200]

            return step

         step["answer"] = describe_write_answer(payload, root_field, pk)

         return step

      async def read_post(code: str, pk: str, label: str) -> dict[str, object]:
         variables = {
            "shortcode": code,
            "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": False,
            "__relay_internal__pv__PolarisMultiCaptionCarouselEnabledrelayprovider": True,
         }
         step: dict[str, object] = {"read": label}
         steps.append(step)

         try:
            payload = await read_json(
               lambda: build_graphql_request(
                  session,
                  POST_BY_SHORTCODE,
                  variables,
                  referer=post_url(code),
                  user_agent=user_agent,
               )
            )
         except DumpstagramError as failure:
            step["failed_with"] = type(failure).__name__
            step["failure_text"] = str(failure)[:200]

            return step

         step.update(describe_read(payload, pk))

         return step

      try:
         timeline = await read_json(
            lambda: build_username_resolution_request(session, username, user_agent=user_agent)
         )
      except DumpstagramError as failure:
         report["failed_with"] = type(failure).__name__
         report["requests"] = transport.sent
         report_run("like-discovery-failed", report)

         return 3

      own_nodes = own_timeline_nodes(timeline, session.ds_user_id)

      if not own_nodes:
         report["failed_with"] = "the newest timeline node is missing or not the viewer's own post"
         report["requests"] = transport.sent
         report_run("like-discovery-failed", report)

         return 3

      node = own_nodes[0]
      pk = str(node["pk"])
      code = str(node["code"])
      report["post_pk"] = pk
      report["timeline_has_liked"] = node.get("has_liked")

      before = await read_post(code, pk, "before")
      starting_state = before.get("has_liked")
      read_answered = isinstance(starting_state, bool) and before.get("pk_matches") is True

      if not read_answered:
         report["stopped_before_writing"] = "the read failed or named another post"
         report["requests"] = transport.sent
         report_run("like-discovery-stopped", report)

         return 4

      report["starting_has_liked"] = starting_state

      if starting_state:
         away, back = (UNLIKE, "xig_media_unlike"), (LIKE, "xig_media_like")
      else:
         away, back = (LIKE, "xig_media_like"), (UNLIKE, "xig_media_unlike")

      first_away = await write(away[0], pk, code, away[1])

      if "failed_with" not in first_away:
         await write(away[0], pk, code, away[1])

      middle = await read_post(code, pk, "after_first_pair")
      needs_restoring = middle.get("has_liked") is not starting_state

      if needs_restoring:
         first_back = await write(back[0], pk, code, back[1])

         if "failed_with" not in first_back:
            await write(back[0], pk, code, back[1])

      after = await read_post(code, pk, "after_second_pair")

   session.save(session_path)

   report["requests"] = transport.sent
   report["requests_spent"] = len(transport.sent)
   report["elapsed_ms"] = int((time.monotonic() - transport.started_at) * 1000)
   report["like_count_delta_after_first_pair"] = _delta(before, middle)
   report["like_count_delta_at_the_end"] = _delta(before, after)
   report["ends_in_starting_state"] = after.get("has_liked") is starting_state

   report_run("like-discovery", report)

   return 0


def _delta(before: dict[str, object], after: dict[str, object]) -> int | None:
   before_count = before.get("like_count")
   after_count = after.get("like_count")
   both_counted = isinstance(before_count, int) and isinstance(after_count, int)

   if not both_counted:
      return None

   return int(after_count) - int(before_count)  # type: ignore[call-overload]


if __name__ == "__main__":
   parser = argparse.ArgumentParser()
   parser.add_argument("--approve", default="")
   arguments = parser.parse_args()

   sys.exit(asyncio.run(run(arguments.approve == "like-cycle")))
