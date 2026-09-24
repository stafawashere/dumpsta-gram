"""Writes on the owner's own post only, in the cycle stage. Two to nine live requests per stage.

The ``scout`` stage reads one page of the post's comments and sends the comment delete mutation
once with an input that names no comment, so nothing can be deleted, to read which input fields
the upstream says it wants. Two requests, three with a bootstrap. Nobody sees anything.

The ``coerce`` stage sends the same mutation once with ``comment_id`` "0", which names no
comment, and ``media_id``. The scout's empty input answered ``noncoercible_variable_value``
without naming a field, so an answer other than that one says the two names coerce. One
request, two with a bootstrap. Nothing can be deleted.

The ``cycle`` stage posts one comment on the owner's own post, reads the page, deletes it,
reads the page, then posts and deletes a second time and reads the page once more. Seven
requests, eight with a bootstrap, nine if a delete has to fall back to the REST route. Each
comment is visible for about the 30 s write spacing to anyone who can see the post, which on
a private account is its approved followers. Approved by the owner on 2026-09-23 for this run.
The text is ``IG_COMMENT_TEXT`` from the root ``.env`` and never appears in this file or a log.

Step 16's discovery run, done from the engine side under ruling 23 in the build plan, which
allows no browser load. It replays the three hypothesis contracts from Step 13.0,
``read-a-post-comment-page``, ``comment-on-a-post`` and ``delete-my-own-comment``, with requests
built by the engine's own ``build_graphql_request`` and writes sent through ``send_write``.

Every comment this run creates is deleted in the same run. When the GraphQL delete fails, the
REST route the bundle also compiles is tried once for that comment, and when that fails too the
run stops writing and the log names the comment id still up.

Recorded: comment ids, counts, key names, lengths, whether a comment's author is the viewer,
envelopes and timings. No comment text and no username.

It sends nothing without ``--approve comment-cycle``. Run it from `engine/` with:

   uv run python probes/comment_discovery.py --approve comment-cycle --stage scout --pk PK
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
from dumpstagram._core.redaction import redact
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
from dumpstagram._private.web.documents.common import PersistedQuery
from dumpstagram._private.web.requests.common import build_graphql_request
from dumpstagram.errors import DumpstagramError
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE", "IG_COMMENT_TEXT")

STAGE_CAPS = {"scout": 3, "coerce": 2, "cycle": 9}

COMMENT_PAGE = PersistedQuery(
   doc_id="28169471862682868",
   friendly_name="PolarisPostCommentsPaginationQuery",
   finding_id="read-a-post-comment-page",
)
COMMENT_CREATE = PersistedQuery(
   doc_id="27261905640092552",
   friendly_name="PolarisPostCommentInputRevampedMutation",
   finding_id="comment-on-a-post",
)
COMMENT_DELETE = PersistedQuery(
   doc_id="27034318419564986",
   friendly_name="usePolarisPostDeleteCommentMutation",
   finding_id="delete-my-own-comment",
)

COMMENT_PAGE_ROOT = "xdt_api__v1__media__media_id__comments__connection"
CREATE_ROOT = "xig_comment_create"
DELETE_ROOT = "xig_comment_delete"

PAGE_SIZE = 10

WRITE_POLICY = WritePolicy(stop_after_unrecognised_rejection=False)
"""The probe decides by hand which write follows a rejection, so a cleanup delete can go."""


class CappedTransport:
   def __init__(self, inner: HttpxTransport, cap: int) -> None:
      self.inner = inner
      self.cap = cap
      self.sent: list[dict[str, object]] = []
      self.started_at = time.monotonic()
      self.last_text = ""

   async def send(self, request: Request) -> Response:
      if len(self.sent) >= self.cap:
         raise RuntimeError(f"refusing request {len(self.sent) + 1}, the cap is {self.cap}")

      entry: dict[str, object] = {
         "name": request.headers.get("x-fb-friendly-name", request.url.split("?")[0][-60:]),
         "offset_ms": int((time.monotonic() - self.started_at) * 1000),
      }
      self.sent.append(entry)

      response = await self.inner.send(request)
      entry["status"] = response.status_code
      entry["length"] = len(response.content)
      self.last_text = response.text

      return response

   async def aclose(self) -> None:
      await self.inner.aclose()


def shape(value: Any, depth: int = 0) -> Any:
   if depth > 4:
      return type(value).__name__

   if isinstance(value, dict):
      return {key: shape(item, depth + 1) for key, item in sorted(value.items())}

   if isinstance(value, list):
      return [shape(value[0], depth + 1), f"len {len(value)}"] if value else []

   if isinstance(value, str):
      return f"str len {len(value)}"

   return type(value).__name__


def comment_page_variables(pk: str) -> dict[str, Any]:
   return {
      "after": None,
      "before": None,
      "first": PAGE_SIZE,
      "last": None,
      "media_id": pk,
      "sort_order": "popular",
      "__relay_internal__pv__PolarisIsLoggedInrelayprovider": True,
   }


def describe_page(payload: Any, viewer_id: str) -> dict[str, object]:
   data = payload.get("data") if isinstance(payload, dict) else None
   connection = data.get(COMMENT_PAGE_ROOT) if isinstance(data, dict) else None

   if not isinstance(connection, dict):
      return {"connection_is_object": False, "data_keys": sorted(data) if data else None}

   edges = connection.get("edges") or []
   nodes = [edge.get("node") for edge in edges if isinstance(edge, dict)]
   node_keys: set[str] = set()
   ids: list[str] = []
   viewer_ids: list[str] = []

   for node in nodes:
      if not isinstance(node, dict):
         continue

      node_keys.update(node.keys())
      comment_id = str(node.get("pk"))
      ids.append(comment_id)

      author = node.get("user")
      author_id = str(author.get("pk") or author.get("id")) if isinstance(author, dict) else None

      if author_id == viewer_id:
         viewer_ids.append(comment_id)

   return {
      "connection_keys": sorted(connection.keys()),
      "page_info": connection.get("page_info"),
      "edge_count": len(edges),
      "node_keys": sorted(node_keys),
      "first_node_shape": shape(nodes[0]) if nodes else None,
      "comment_ids": ids,
      "viewer_comment_ids": viewer_ids,
   }


def listed(step: dict[str, object]) -> list[str]:
   ids = step.get("comment_ids")

   return [str(each) for each in ids] if isinstance(ids, list) else []


def new_viewer_comment(step: dict[str, object]) -> str | None:
   ids = step.get("viewer_comment_ids")

   return str(ids[0]) if isinstance(ids, list) and len(ids) == 1 else None


def describe_created(payload: Any, viewer_id: str, text_length: int) -> dict[str, object]:
   data = payload.get("data") if isinstance(payload, dict) else None
   root = data.get(CREATE_ROOT) if isinstance(data, dict) else None

   if not isinstance(root, dict):
      return {"root_is_object": False}

   nested = root.get("comment_dict")
   comment: dict[str, Any] = nested if isinstance(nested, dict) else root
   author = comment.get("user")
   author_id = str(author.get("pk") or author.get("id")) if isinstance(author, dict) else None
   text = comment.get("text")

   return {
      "root_keys": sorted(root.keys()),
      "typename": root.get("__typename"),
      "comment_keys": sorted(comment.keys()),
      "comment_id": comment.get("pk") or comment.get("id"),
      "pk_equals_id": comment.get("pk") == comment.get("id"),
      "author_is_viewer": author_id == viewer_id,
      "text_length_matches": isinstance(text, str) and len(text) == text_length,
   }


def build_rest_delete(session: Session, pk: str, comment_id: str, user_agent: str) -> Request:
   return Request(
      method="POST",
      url=f"{ORIGIN}/api/v1/web/comments/{pk}/delete/{comment_id}/",
      headers={
         "content-type": "application/x-www-form-urlencoded",
         "sec-fetch-site": "same-origin",
         "sec-fetch-mode": "cors",
         "sec-fetch-dest": "empty",
         "user-agent": user_agent,
         "x-ig-app-id": session.app_id or "",
         "x-csrftoken": session.csrftoken,
         "x-requested-with": "XMLHttpRequest",
         "x-asbd-id": "359341",
         "origin": ORIGIN,
         "referer": f"{ORIGIN}/",
         "accept": "*/*",
      },
      content=b"",
      follow_redirects=False,
   )


async def run(stage: str, approved: bool, pk: str) -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}

   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT") or DEFAULT_USER_AGENT
   comment_text = environment.get("IG_COMMENT_TEXT", "")

   report: dict[str, object] = {"stage": stage, "post_pk": pk, "approved": approved}
   kind = f"comment-discovery-{stage}"

   if not approved:
      report["failed_with"] = "not approved, pass --approve comment-cycle"
      report_run(f"{kind}-refused", report)

      return 2

   if stage == "cycle" and not comment_text:
      report["failed_with"] = "no IG_COMMENT_TEXT in .env"
      report_run(f"{kind}-failed", report)

      return 2

   report["comment_text_length"] = len(comment_text)

   session = Session.load(session_path)
   transport = CappedTransport(
      HttpxTransport(cookies=cookies_for(session), proxy=session.proxy), STAGE_CAPS[stage]
   )
   steps: list[dict[str, object]] = []
   report["steps"] = steps
   post_referer = f"{ORIGIN}/"

   async with PacedSender(transport, Pacer(), writes=WRITE_POLICY) as sender:

      async def ensure_tokens() -> None:
         if not session.fb_dtsg:
            await bootstrap(sender, session, user_agent=user_agent)

      async def read_page(label: str) -> dict[str, object]:
         step: dict[str, object] = {"read": label}
         steps.append(step)

         async def attempt() -> Any:
            await ensure_tokens()
            request = build_graphql_request(
               session,
               COMMENT_PAGE,
               comment_page_variables(pk),
               referer=post_referer,
               user_agent=user_agent,
            )

            return classify(await sender.send(request))

         try:
            payload = await with_token_recovery(attempt, sender=sender, session=session)
         except DumpstagramError as failure:
            step["failed_with"] = type(failure).__name__
            step["failure_text"] = redact(str(failure))[:300]

            return step

         step.update(describe_page(payload, session.ds_user_id))

         return step

      async def graphql_write(
         label: str, query: PersistedQuery, variables: dict[str, Any], root: str
      ) -> tuple[dict[str, object], Any]:
         await ensure_tokens()

         step: dict[str, object] = {"write": label, "friendly_name": query.friendly_name}
         steps.append(step)
         request = build_graphql_request(
            session, query, variables, referer=post_referer, user_agent=user_agent
         )

         try:
            payload = await send_write(sender, session, WriteRequest(request, label))
         except DumpstagramError as failure:
            step["failed_with"] = type(failure).__name__
            step["failure_code"] = getattr(failure, "code", None)
            step["answer_text"] = redact(transport.last_text)[:1500]

            return step, None

         data = payload.get("data") if isinstance(payload, dict) else None
         step["top_level_keys"] = sorted(payload) if isinstance(payload, dict) else None
         step["root_present"] = isinstance(data, dict) and root in data
         step["root_shape"] = shape(data.get(root)) if isinstance(data, dict) else None

         return step, payload

      if stage == "scout":
         await read_page("before")
         step, _ = await graphql_write(
            "delete_with_no_comment",
            COMMENT_DELETE,
            {"input": {"client_mutation_id": "1"}},
            DELETE_ROOT,
         )

      if stage == "coerce":
         await graphql_write(
            "delete_of_comment_zero",
            COMMENT_DELETE,
            {"input": {"client_mutation_id": "1", "comment_id": "0", "media_id": pk}},
            DELETE_ROOT,
         )

      if stage == "cycle":
         mutation_numbers = iter(range(1, 10))

         async def create(label: str) -> str | None:
            step, payload = await graphql_write(
               label,
               COMMENT_CREATE,
               {"connections": [], "data": {"comment_text": comment_text, "media_id": pk}},
               CREATE_ROOT,
            )

            if payload is None:
               return None

            created = describe_created(payload, session.ds_user_id, len(comment_text))
            step.update(created)
            created_id = created.get("comment_id")

            return str(created_id) if created_id else None

         async def delete(label: str, comment_id: str) -> bool:
            variables = {
               "input": {
                  "client_mutation_id": str(next(mutation_numbers)),
                  "comment_id": comment_id,
                  "media_id": pk,
               }
            }
            step, payload = await graphql_write(label, COMMENT_DELETE, variables, DELETE_ROOT)
            step["comment_id"] = comment_id
            step["answer_null_root"] = (
               payload is not None and payload.get("data", {}).get(DELETE_ROOT) is None
            )

            return payload is not None

         async def rest_delete(comment_id: str) -> bool:
            step: dict[str, object] = {"write": "rest_delete_fallback", "comment_id": comment_id}
            steps.append(step)
            request = build_rest_delete(session, pk, comment_id, user_agent)

            try:
               payload = await send_write(
                  sender, session, WriteRequest(request, "rest_delete_fallback")
               )
            except DumpstagramError as failure:
               step["failed_with"] = type(failure).__name__
               step["answer_text"] = redact(transport.last_text)[:600]

               return False

            step["answer_shape"] = shape(payload)

            return True

         async def remove(label: str, comment_id: str) -> bool:
            if await delete(label, comment_id):
               return True

            return await rest_delete(comment_id)

         left_up: list[str] = []
         report["comments_left_up"] = left_up

         first_id = await create("create_first")
         after_create = await read_page("after_first_create")

         if first_id is None:
            first_id = new_viewer_comment(after_create)
            report["first_id_from_read"] = first_id

         if first_id is None:
            report["stopped"] = "the first create answered no id and the read showed none"
         else:
            was_present = first_id in listed(after_create)
            after_create["created_id_present"] = was_present
            removed = await remove("delete_first", first_id)
            after_delete = await read_page("after_first_delete")
            is_gone = first_id not in listed(after_delete)
            after_delete["created_id_gone"] = is_gone
            still_listed = removed and not is_gone

            if still_listed:
               removed = await rest_delete(first_id)
               after_delete = await read_page("after_rest_fallback")
               is_gone = first_id not in listed(after_delete)
               after_delete["created_id_gone"] = is_gone

            read_answered = "failed_with" not in after_delete
            cycle_was_clean = was_present and removed and is_gone and read_answered

            if not cycle_was_clean:
               if not is_gone:
                  left_up.append(first_id)

               report["stopped"] = "the first delete did not confirm, no second cycle"
            else:
               second_id = await create("create_second")

               if second_id is None:
                  report["stopped"] = "the second create answered no id"
               else:
                  second_removed = await remove("delete_second", second_id)
                  final = await read_page("after_second_delete")
                  second_gone = second_id not in listed(final)
                  final["created_id_gone"] = second_gone
                  second_cycle_was_clean = second_removed and second_gone

                  if not second_cycle_was_clean:
                     left_up.append(second_id)

   session.save(session_path)

   report["requests"] = transport.sent
   report["requests_spent"] = len(transport.sent)
   report["elapsed_ms"] = int((time.monotonic() - transport.started_at) * 1000)

   report_run(kind, report)

   return 0


if __name__ == "__main__":
   parser = argparse.ArgumentParser()
   parser.add_argument("--approve", default="")
   parser.add_argument("--stage", choices=sorted(STAGE_CAPS), required=True)
   parser.add_argument("--pk", required=True)
   arguments = parser.parse_args()

   sys.exit(asyncio.run(run(arguments.stage, arguments.approve == "comment-cycle", arguments.pk)))
