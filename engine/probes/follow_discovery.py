"""Writes four times in its cycle stage, on the one account the owner named only. Up to eleven
live requests over two stages, one more with a bootstrap.

Two follows and two unfollows of ``IG_FOLLOW_TARGET`` from the root ``.env``, the account the
owner named in chat on 2026-09-23 and approved follow and unfollow on (ruling 30 in the build
plan). The account is notified by each follow, and a private account sees a follow request
until the unfollow withdraws it. The account ends in the relationship it started in.

Step 17's discovery run, done from the engine side under ruling 23, which allows no browser
load. Requests are built by the engine's own ``build_graphql_request`` and the writes are sent
through ``send_write``. Two stages, so the relationship is read before anything is written:

``--stage read``, two requests, three if the username does not resolve on the timeline route.
Resolves the username to the numeric account id through the timeline query, falling back to the
profile page document, then reads the profile by id and records whether the account is private,
the key union of ``friendship_status`` and each of its flags. The username is never logged,
only the id.

``--stage cycle --user-id ID``, nine requests. A profile read, then two cycles of a write, a
read, the reversing write and a read. From not following, a cycle is follow then unfollow. From
following or a pending request it is unfollow then follow, and it refuses to start when the
account is private and followed, because the follow that would restore it creates a request the
account has to approve. It answers:

- whether both mutations answer on ``/api/graphql`` with ``target_user_id`` as the numeric id
- what each answer carries under ``xdt_create_friendship`` and ``xdt_destroy_friendship``
- what a follow of a private account does to ``following`` and ``outgoing_request``, and
  whether the unfollow withdraws the request
- whether each read after a write shows the state the write asked for

A rejected write stops the run after its reversal is attempted, and the log says whether the
account ended in its starting relationship. The doc_id values live in this file, not in the
package, because neither finding was verified when it ran.

Recorded: the account id, ``is_private``, the ``friendship_status`` flags, answer shapes, and
timings. No username, no name, no text.

It sends nothing without ``--approve follow``. Run it from `engine/` with:

   uv run python probes/follow_discovery.py --approve follow --stage read
   uv run python probes/follow_discovery.py --approve follow --stage cycle --user-id ID
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
from dumpstagram._core.profiles import resolve_username
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
from dumpstagram._private.web.bootstrap import (
   DEFAULT_USER_AGENT,
   ORIGIN,
   bootstrap,
   build_document_request,
)
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.documents import PersistedQuery
from dumpstagram._private.web.parse import parse_profile
from dumpstagram._private.web.preload import read_profile_id
from dumpstagram._private.web.requests import (
   build_graphql_request,
   build_profile_request,
   profile_page_url,
)
from dumpstagram.errors import DumpstagramError, NotFound
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE", "IG_FOLLOW_TARGET")

REQUEST_CAPS = {"read": 4, "cycle": 10}

CYCLES = 2

FOLLOW = PersistedQuery(
   doc_id="27767812149509802",
   friendly_name="usePolarisFollowUserFollowMutation",
   finding_id="follow-a-user",
)
UNFOLLOW = PersistedQuery(
   doc_id="25174972798866458",
   friendly_name="usePolarisFollowUserUnfollowMutation",
   finding_id="unfollow-a-user",
)

ANSWER_ROOTS = {
   FOLLOW.friendly_name: "xdt_create_friendship",
   UNFOLLOW.friendly_name: "xdt_destroy_friendship",
}

WRITE_POLICY = WritePolicy(stop_after_unrecognised_rejection=False)
"""The probe decides by hand what follows a rejection, so the restoring write can go."""


class CappedTransport:
   def __init__(self, inner: HttpxTransport, cap: int) -> None:
      self.inner = inner
      self.cap = cap
      self.sent: list[dict[str, object]] = []
      self.started_at = time.monotonic()

   async def send(self, request: Request) -> Response:
      if len(self.sent) >= self.cap:
         raise RuntimeError(f"refusing request {len(self.sent) + 1}, the cap is {self.cap}")

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


def shape_of(value: Any) -> Any:
   """Key names, types and string lengths. Flags and numbers are kept, strings are not."""

   if isinstance(value, dict):
      return {key: shape_of(inner) for key, inner in sorted(value.items())}

   if isinstance(value, list):
      return [shape_of(value[0])] if value else []

   if isinstance(value, str):
      return f"str:{len(value)}"

   return value


def describe_relationship(payload: Any, user_id: str) -> dict[str, object]:
   data = payload.get("data") if isinstance(payload, dict) else None
   user = data.get("user") if isinstance(data, dict) else None

   if not isinstance(user, dict):
      return {"user_is_object": False}

   friendship = user.get("friendship_status")
   described: dict[str, object] = {
      "id_matches": str(user.get("id")) == user_id,
      "is_private": user.get("is_private"),
      "friendship_status_type": type(friendship).__name__,
      "friendship_status": shape_of(friendship),
      "user_value_types": {key: type(value).__name__ for key, value in sorted(user.items())},
   }

   try:
      parse_profile(payload)
      described["maps_into_profile"] = True
   except DumpstagramError as failure:
      described["maps_into_profile"] = False
      described["mapping_failure"] = str(failure)[:200]

   return described


def relationship_flags(described: dict[str, object]) -> tuple[object, object]:
   friendship = described.get("friendship_status")

   if not isinstance(friendship, dict):
      return None, None

   return friendship.get("following"), friendship.get("outgoing_request")


async def run(approved: bool, stage: str, user_id: str) -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}

   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   target_username = environment.get("IG_FOLLOW_TARGET", "")
   user_agent = environment.get("IG_USER_AGENT") or DEFAULT_USER_AGENT
   kind = f"follow-discovery-{stage}"

   report: dict[str, object] = {"session_path": str(session_path), "approved": approved}

   if not approved:
      report["failed_with"] = "not approved, pass --approve follow"
      report_run(f"{kind}-refused", report)

      return 2

   has_what_the_stage_needs = bool(target_username) if stage == "read" else bool(user_id)

   if not session_path.exists() or not has_what_the_stage_needs:
      report["failed_with"] = "no session file, no IG_FOLLOW_TARGET in .env, or no --user-id"
      report_run(f"{kind}-failed", report)

      return 2

   session = Session.load(session_path)
   transport = CappedTransport(
      HttpxTransport(cookies=cookies_for(session), proxy=session.proxy), REQUEST_CAPS[stage]
   )
   steps: list[dict[str, object]] = []
   report["steps"] = steps

   async with PacedSender(transport, Pacer(), writes=WRITE_POLICY) as sender:

      async def read_json(build: Any) -> Any:
         async def attempt() -> Any:
            if not session.fb_dtsg:
               await bootstrap(sender, session, user_agent=user_agent)

            return classify(await sender.send(build()))

         return await with_token_recovery(attempt, sender=sender, session=session)

      async def read_relationship(account_id: str, label: str) -> dict[str, object]:
         step: dict[str, object] = {"read": label}
         steps.append(step)

         try:
            payload = await read_json(
               lambda: build_profile_request(session, account_id, user_agent=user_agent)
            )
         except DumpstagramError as failure:
            step["failed_with"] = type(failure).__name__
            step["failure_text"] = str(failure)[:200]

            return step

         step.update(describe_relationship(payload, account_id))

         return step

      async def write(query: PersistedQuery, account_id: str) -> dict[str, object]:
         request = build_graphql_request(
            session,
            query,
            {"target_user_id": account_id},
            referer=f"{ORIGIN}/",
            user_agent=user_agent,
         )
         step: dict[str, object] = {"write": query.friendly_name}
         steps.append(step)

         try:
            payload = await send_write(sender, session, WriteRequest(request, query.friendly_name))
         except DumpstagramError as failure:
            step["failed_with"] = type(failure).__name__
            step["failure_code"] = getattr(failure, "code", None)
            step["failure_text"] = str(failure)[:200]

            return step

         data = payload.get("data") if isinstance(payload, dict) else None
         root_field = ANSWER_ROOTS[query.friendly_name]
         root = data.get(root_field) if isinstance(data, dict) else None

         step["top_level_keys"] = sorted(payload.keys()) if isinstance(payload, dict) else None
         step["data_keys"] = sorted(data.keys()) if isinstance(data, dict) else None
         step["answer"] = shape_of(root)
         step["echoed_id_matches"] = isinstance(root, dict) and str(root.get("id")) == account_id

         return step

      if stage == "read":
         resolved_by = "timeline"

         try:
            account_id = await resolve_username(
               sender, session, target_username, user_agent=user_agent
            )
         except NotFound:
            resolved_by = "document"
            document = await sender.send(
               build_document_request(profile_page_url(target_username), user_agent)
            )
            found = read_profile_id(document.text)

            if found is None:
               report["failed_with"] = "the profile document names no account"
               report["requests"] = transport.sent
               report_run(f"{kind}-failed", report)

               return 3

            account_id = found

         report["resolved_by"] = resolved_by
         report["target_user_id"] = account_id
         await read_relationship(account_id, "relationship")
      else:
         report["target_user_id"] = user_id
         before = await read_relationship(user_id, "before")
         following, requested = relationship_flags(before)
         is_private = before.get("is_private")

         has_a_known_state = isinstance(following, bool) and isinstance(requested, bool)

         if not has_a_known_state:
            report["stopped_before_writing"] = "the relationship read carried no known state"
            report["requests"] = transport.sent
            report_run(f"{kind}-stopped", report)

            return 4

         cannot_be_restored = is_private is True and following is True

         if cannot_be_restored:
            report["stopped_before_writing"] = "private and followed, a refollow would be a request"
            report["requests"] = transport.sent
            report_run(f"{kind}-stopped", report)

            return 4

         starts_connected = following is True or requested is True
         away, back = (UNFOLLOW, FOLLOW) if starts_connected else (FOLLOW, UNFOLLOW)
         report["starting_state"] = {"following": following, "outgoing_request": requested}
         report["order"] = [away.friendly_name, back.friendly_name]

         for cycle in range(1, CYCLES + 1):
            away_step = await write(away, user_id)
            await read_relationship(user_id, f"cycle_{cycle}_after_away")
            back_step = await write(back, user_id)
            after = await read_relationship(user_id, f"cycle_{cycle}_after_back")

            a_write_failed = "failed_with" in away_step or "failed_with" in back_step

            if a_write_failed:
               break

         report["ending_state"] = dict(
            zip(("following", "outgoing_request"), relationship_flags(after), strict=True)
         )
         report["ends_in_starting_state"] = relationship_flags(after) == (following, requested)

   session.save(session_path)

   report["requests"] = transport.sent
   report["requests_spent"] = len(transport.sent)
   report["elapsed_ms"] = int((time.monotonic() - transport.started_at) * 1000)

   report_run(kind, report)

   return 0


if __name__ == "__main__":
   parser = argparse.ArgumentParser()
   parser.add_argument("--approve", default="")
   parser.add_argument("--stage", choices=("read", "cycle"), required=True)
   parser.add_argument("--user-id", default="")
   arguments = parser.parse_args()

   sys.exit(asyncio.run(run(arguments.approve == "follow", arguments.stage, arguments.user_id)))
