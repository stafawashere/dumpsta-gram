"""Reads in its inbox stage. Its send stage writes twice: one direct text message, with the
text in IG_DM_TEXT, to the account the owner named, who is notified and can read it before the
unsend, then the unsend. One live request in the inbox stage and three in the send stage, one
more in either for a bootstrap.

The owner named the account (``IG_FOLLOW_TARGET`` in the root ``.env``, passed here by its
numeric id) and approved direct messages to it, ruling 30 in the build plan. The text is read
from ``IG_DM_TEXT`` and never written here or to a log.

Step 18's discovery run from the engine side. The browser observed the send and the unsend once
each, in reverse-engineer run ``run-2026-09-23-145957``; this probe is the second observation of
both, built by the engine's own ``build_graphql_request`` and sent through ``send_write``.

``--stage inbox --user-id ID``, one request. Reads the inbox's first page and records whether a
thread with the account is on it, with the row's ``id``, ``thread_fbid``, ``thread_key``, the
length of ``thread_id``, and the newest message id it carries.

``--stage send --user-id ID --thread-fbid FBID --thread-id ID``, three requests. The send, a
read of the thread (its newest page, or the page newer than ``--base-message-id`` when given),
and the unsend. The thread's state before the send is known from the browser run, which left it
with its one message unsent, so no read goes before it; the step's live budget allowed three. It
answers:

- whether the mutation answers on ``/api/graphql`` with the fourteen variables the browser sent
- what the answer carries under its root, and whether its ``message_id`` is the id the read has
- whether the read echoes the ``offline_threading_id`` the send carried
- whether ``newer_than_message_id`` returns exactly the new message and nothing older
- whether the unsend answers with ``thread_id``, the 39-digit id, as the browser sent it

Recorded: ids, counts, lengths, answer shapes and timings. No text, no username, no name.

It sends nothing in the send stage without ``--approve send-message``. Run it from `engine/`:

   uv run python probes/direct_send_discovery.py --stage inbox --user-id ID
   uv run python probes/direct_send_discovery.py --approve send-message --stage send \\
      --user-id ID --thread-fbid FBID --thread-id THREAD_ID
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
import time
import uuid
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
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.documents.common import PersistedQuery
from dumpstagram._private.web.parse.direct import THREAD_PAGE_PATH
from dumpstagram._private.web.requests.common import build_graphql_request
from dumpstagram._private.web.requests.direct import (
   build_inbox_listing_request,
   build_thread_older_page_request,
   thread_url,
)
from dumpstagram.errors import DumpstagramError
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE", "IG_DM_TEXT")

REQUEST_CAPS = {"inbox": 2, "send": 3}

TEXT_SEND = PersistedQuery(
   doc_id="26911679871773184",
   friendly_name="IGDirectTextSendMutation",
   finding_id="send-a-direct-text-message",
)
UNSEND = PersistedQuery(
   doc_id="26948700068153789",
   friendly_name="IGDMessageUnsendDialogOffMsysMutation",
   finding_id="unsend-a-direct-message",
)

SEND_ROOT = "xig_direct_text_send_with_slide_messaging_response"
UNSEND_ROOT = "direct_unsend_message"


def offline_threading_id(now_ms: int) -> str:
   """The browser's construction, read off IGDOfflineThreadingID: the millisecond clock with
   22 random bits after it, cut to 63 bits, as a decimal string."""

   random_bits = secrets.randbits(22)

   return str(((now_ms << 22) | random_bits) & ((1 << 63) - 1))


def raw_message_nodes(payload: Any) -> list[dict[str, Any]]:
   node: Any = payload

   for key in THREAD_PAGE_PATH:
      node = node.get(key) if isinstance(node, dict) else None

   edges = node.get("edges") if isinstance(node, dict) else None

   if not isinstance(edges, list):
      return []

   return [
      edge["node"]
      for edge in edges
      if isinstance(edge, dict) and isinstance(edge.get("node"), dict)
   ]


def describe_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, object]]:
   described: list[dict[str, object]] = []

   for node in nodes:
      body = node.get("text_body")
      described.append(
         {
            "id": node.get("id"),
            "message_id_equals_id": node.get("message_id") == node.get("id"),
            "offline_threading_id": node.get("offline_threading_id"),
            "thread_fbid": node.get("thread_fbid"),
            "sender_fbid": node.get("sender_fbid"),
            "content_type": node.get("content_type"),
            "timestamp_ms": node.get("timestamp_ms"),
            "text_length": len(body) if isinstance(body, str) else None,
         }
      )

   return described


WRITE_POLICY = WritePolicy(stop_after_unrecognised_rejection=False)


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


def inbox_rows(payload: Any) -> list[dict[str, Any]]:
   data = payload.get("data") if isinstance(payload, dict) else None
   mailbox = data.get("get_slide_mailbox_for_iris_subscription") if isinstance(data, dict) else None

   if not isinstance(mailbox, dict):
      return []

   rows: list[dict[str, Any]] = []
   pinned = mailbox.get("pinned_threads_v2") or []
   edges = (mailbox.get("threads_by_folder") or {}).get("edges") or []

   for holder in [*pinned, *(edge.get("node") or {} for edge in edges)]:
      thread = holder.get("as_ig_direct_thread") if isinstance(holder, dict) else None

      if isinstance(thread, dict):
         rows.append(thread)

   return rows


def describe_target_row(thread: dict[str, Any], user_id: str) -> dict[str, object]:
   messages = (thread.get("slide_messages") or {}).get("edges") or []
   newest = messages[0].get("node") if messages else None
   thread_id = thread.get("thread_id")

   return {
      "id": thread.get("id"),
      "thread_fbid": thread.get("thread_fbid"),
      "thread_key": thread.get("thread_key"),
      "thread_id_length": len(thread_id) if isinstance(thread_id, str) else None,
      "is_group": thread.get("is_group"),
      "user_ids": [str(user.get("id")) for user in thread.get("users") or []],
      "target_is_a_user": user_id in [str(user.get("id")) for user in thread.get("users") or []],
      "newest_message_id": newest.get("message_id") if isinstance(newest, dict) else None,
      "carried_messages": len(messages),
   }


async def run(arguments: argparse.Namespace) -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}

   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT") or DEFAULT_USER_AGENT
   stage = arguments.stage
   kind = f"direct-send-discovery-{stage}"

   report: dict[str, object] = {"session_path": str(session_path), "stage": stage}

   is_a_send = stage == "send"
   is_approved = arguments.approve == "send-message"

   if is_a_send and not is_approved:
      report["failed_with"] = "not approved, pass --approve send-message"
      report_run(f"{kind}-refused", report)

      return 2

   if not session_path.exists() or not arguments.user_id:
      report["failed_with"] = "no session file or no --user-id"
      report_run(f"{kind}-failed", report)

      return 2

   session = Session.load(session_path)
   transport = CappedTransport(
      HttpxTransport(cookies=cookies_for(session), proxy=session.proxy), REQUEST_CAPS[stage]
   )

   async with PacedSender(transport, Pacer(), writes=WRITE_POLICY) as sender:

      async def read_json(build: Any) -> Any:
         async def attempt() -> Any:
            if not session.fb_dtsg:
               await bootstrap(sender, session, user_agent=user_agent)

            return classify(await sender.send(build()))

         return await with_token_recovery(attempt, sender=sender, session=session)

      if stage == "inbox":
         device_id = str(uuid.uuid4())

         try:
            payload = await read_json(
               lambda: build_inbox_listing_request(
                  session, device_id=device_id, user_agent=user_agent
               )
            )
         except DumpstagramError as failure:
            report["failed_with"] = type(failure).__name__
            report["failure_text"] = str(failure)[:200]
            report["requests"] = transport.sent
            report_run(f"{kind}-failed", report)

            return 3

         rows = inbox_rows(payload)
         matching = [
            describe_target_row(thread, arguments.user_id)
            for thread in rows
            if arguments.user_id in [str(user.get("id")) for user in thread.get("users") or []]
         ]
         report["rows_read"] = len(rows)
         report["target_rows"] = matching
         report["one_to_one_thread_found"] = any(row["is_group"] is False for row in matching)
         report["row_key_union"] = sorted({key for thread in rows for key in thread})

      if stage == "send":
         outcome = await send_cycle(sender, session, arguments, environment, user_agent, report)

         if outcome != 0:
            report["requests"] = transport.sent
            report["requests_spent"] = len(transport.sent)
            report_run(f"{kind}-stopped", report)

            return outcome

   session.save(session_path)

   report["requests"] = transport.sent
   report["requests_spent"] = len(transport.sent)
   report["elapsed_ms"] = int((time.monotonic() - transport.started_at) * 1000)

   report_run(kind, report)

   return 0


async def send_cycle(
   sender: PacedSender,
   session: Session,
   arguments: argparse.Namespace,
   environment: dict[str, str],
   user_agent: str,
   report: dict[str, object],
) -> int:
   text = environment.get("IG_DM_TEXT", "")
   thread_fbid = arguments.thread_fbid
   has_what_it_needs = bool(text) and bool(thread_fbid) and bool(arguments.thread_id)

   if not has_what_it_needs:
      report["failed_with"] = "no IG_DM_TEXT, no --thread-fbid or no --thread-id"

      return 2

   async def read_page(newer_than: str | None) -> list[dict[str, Any]]:
      async def attempt() -> Any:
         if not session.fb_dtsg:
            await bootstrap(sender, session, user_agent=user_agent)

         request = build_thread_older_page_request(
            session, thread_fbid, newer_than_message_id=newer_than, user_agent=user_agent
         )

         return classify(await sender.send(request))

      payload = await with_token_recovery(attempt, sender=sender, session=session)

      return raw_message_nodes(payload)

   newer_than_base = arguments.base_message_id or None
   report["newer_than_base"] = newer_than_base

   threading_id = offline_threading_id(int(time.time() * 1000))
   variables = {
      "ig_thread_igid": thread_fbid,
      "offline_threading_id": threading_id,
      "recipient_igids": None,
      "replied_to_client_context": None,
      "replied_to_item_id": None,
      "reply_to_message_id": None,
      "sampled": None,
      "text": {"sensitive_string_value": text},
      "mentions": [],
      "mentioned_user_ids": [],
      "commands": None,
      "forwarded_from_thread_id": None,
      "is_forwarded_from_own_message": None,
      "send_attribution": "igd_web_chat_tab:in_thread",
   }
   report["offline_threading_id"] = threading_id
   report["text_length"] = len(text)
   request = build_graphql_request(
      session, TEXT_SEND, variables, referer=thread_url(thread_fbid), user_agent=user_agent
   )
   sent_at_ms = int(time.time() * 1000)

   try:
      payload = await send_write(sender, session, WriteRequest(request, "send_message"))
   except DumpstagramError as failure:
      report["send_failed_with"] = type(failure).__name__
      report["failure_code"] = getattr(failure, "code", None)
      report["failure_text"] = str(failure)[:200]

      return 3

   data = payload.get("data") if isinstance(payload, dict) else None
   answer = data.get(SEND_ROOT) if isinstance(data, dict) else None
   report["send_top_level_keys"] = sorted(payload.keys()) if isinstance(payload, dict) else None
   report["send_answer"] = shape_of(answer)
   message_id = answer.get("message_id") if isinstance(answer, dict) else None
   report["send_message_id"] = message_id
   report["send_id_equals_message_id"] = isinstance(answer, dict) and answer.get("id") == message_id
   report["send_timestamp_ms"] = answer.get("timestamp_ms") if isinstance(answer, dict) else None
   report["local_clock_ms"] = sent_at_ms

   try:
      after = await read_page(newer_than_base)
   except DumpstagramError as failure:
      report["read_failed_with"] = type(failure).__name__
      report["read_failure_text"] = str(failure)[:200]
      after = []

   described_after = describe_nodes(after)
   report["after_newer_than"] = described_after
   report["read_returned"] = len(after)
   report["read_is_exactly_the_new_message"] = [row["id"] for row in described_after] == [
      message_id
   ]
   report["read_echoes_offline_threading_id"] = any(
      row["offline_threading_id"] == threading_id for row in described_after
   )
   report["after_node_key_union"] = sorted({key for node in after for key in node})

   if not isinstance(message_id, str):
      report["unsend_skipped"] = "the send answer carried no message_id"

      return 4

   unsend_request = build_graphql_request(
      session,
      UNSEND,
      {"message_id": message_id, "send_data": {"thread_id": arguments.thread_id}},
      referer=thread_url(thread_fbid),
      user_agent=user_agent,
   )

   try:
      unsend_payload = await send_write(sender, session, WriteRequest(unsend_request, "unsend"))
   except DumpstagramError as failure:
      report["unsend_failed_with"] = type(failure).__name__
      report["unsend_failure_code"] = getattr(failure, "code", None)
      report["unsend_failure_text"] = str(failure)[:200]

      return 5

   unsend_data = unsend_payload.get("data") if isinstance(unsend_payload, dict) else None
   report["unsend_answer"] = unsend_data.get(UNSEND_ROOT) if isinstance(unsend_data, dict) else None
   report["unsend_top_level_keys"] = (
      sorted(unsend_payload.keys()) if isinstance(unsend_payload, dict) else None
   )

   return 0


if __name__ == "__main__":
   parser = argparse.ArgumentParser()
   parser.add_argument("--approve", default="")
   parser.add_argument("--stage", choices=("inbox", "send"), required=True)
   parser.add_argument("--user-id", default="")
   parser.add_argument("--thread-fbid", default="")
   parser.add_argument("--thread-id", default="")
   parser.add_argument("--base-message-id", default="")
   parsed = parser.parse_args()

   sys.exit(asyncio.run(run(parsed)))
