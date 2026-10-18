"""Read only by default. `--stage identity`: 3 requests, 4 with a second thread. `--stage
mark-read`: 4 requests, 2 of them writes, and refuses to run without `--approve mark-read`.

Release phase 2, items 1 and 3.

`identity` answers which identifier tells the viewer's own messages and reactions apart, with no
guess. It bootstraps from the root `.env`, reads the inbox's first page, and opens the newest
thread whose inbox row lists a message the viewer sent. It records, per message node and per
`msg_reactions` entry, whether `sender_fbid` equals the mailbox id (the viewer's messaging id),
whether `sender.igid` (or `sender_igid`) equals `ds_user_id`, and whether `sender_fbid` equals
`Session.actor_id`, as counts of agreement only. It also counts content types and content
`__typename` values. No id, text, name or URL is written, only booleans and counts.

`mark-read` is the engine's replay of finding `mark-a-direct-thread-read` and the first engine
observation of its validation mutation, sent the way the browser sent them 2 ms apart. It only
marks a thread the inbox already lists as read by the viewer (receipt at or after the last
activity), so the read receipt the other participant can see does not move. It opens that
thread to learn its 39-digit `thread_id` and the newest message's time, then sends the pair once
each, never again. The phase 2 prompt is the owner's approval for exactly this write.

Run it from `engine/` with:

   uv run python probes/viewer_identity_and_mark_read.py --stage identity
   uv run python probes/viewer_identity_and_mark_read.py --stage mark-read --approve mark-read
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import sys
import time
import uuid
from typing import Any

from _probe_support import REQUIRED_CREDENTIAL_KEYS, load_env, report_run

from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
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
from dumpstagram._private.web.parse.direct import parse_inbox_page, parse_thread_id
from dumpstagram._private.web.requests.common import build_graphql_request
from dumpstagram._private.web.requests.direct import (
   build_inbox_listing_request,
   build_thread_detail_request,
   thread_url,
)
from dumpstagram.errors import DumpstagramError
from dumpstagram.session import Session

REQUEST_CAP = 5

MARK_READ = PersistedQuery(
   doc_id="27399783383056109",
   friendly_name="useIGDMarkThreadAsReadMutation",
   finding_id="mark-a-direct-thread-read",
)

MARK_READ_VALIDATION = PersistedQuery(
   doc_id="35211594988486314",
   friendly_name="useIGDMarkThreadAsReadValidationMutation",
   finding_id="mark-a-direct-thread-read-validation",
)

THREAD_DETAIL_ROOT = ("data", "get_slide_thread_nullable", "as_ig_direct_thread")


class CappedTransport:
   def __init__(self, inner: HttpxTransport) -> None:
      self.inner = inner
      self.sent: list[dict[str, object]] = []

   async def send(self, request: Request) -> Response:
      if len(self.sent) >= REQUEST_CAP:
         raise RuntimeError(f"request cap {REQUEST_CAP} reached, nothing more is sent")

      name = request.headers.get("x-fb-friendly-name", "document")
      started = time.monotonic()
      response = await self.inner.send(request)
      self.sent.append(
         {
            "name": name,
            "status": response.status_code,
            "bytes": len(response.content),
            "ms": int((time.monotonic() - started) * 1000),
         }
      )

      return response

   async def aclose(self) -> None:
      await self.inner.aclose()


def _dig(payload: Any, path: tuple[str, ...]) -> Any:
   node = payload

   for key in path:
      node = node.get(key) if isinstance(node, dict) else None

   return node


def _thread_nodes(payload: Any) -> list[dict[str, Any]]:
   thread = _dig(payload, THREAD_DETAIL_ROOT)
   edges = _dig(thread, ("slide_messages", "edges")) or []

   return [
      edge["node"]
      for edge in edges
      if isinstance(edge, dict) and isinstance(edge.get("node"), dict)
   ]


def _agreement(
   nodes: list[dict[str, Any]], viewer_fbid: str, session: Session
) -> dict[str, object]:
   messages: collections.Counter[str] = collections.Counter()
   reactions: collections.Counter[str] = collections.Counter()
   content_types: collections.Counter[str] = collections.Counter()
   typenames: collections.Counter[str] = collections.Counter()

   for node in nodes:
      raw_sender = node.get("sender")
      sender: dict[str, Any] = raw_sender if isinstance(raw_sender, dict) else {}
      igid = sender.get("igid")
      by_fbid = node.get("sender_fbid") == viewer_fbid
      by_igid = igid == session.ds_user_id
      by_actor = node.get("sender_fbid") == session.actor_id

      messages[
         f"fbid_is_viewer={by_fbid} igid_is_viewer={by_igid} igid_present={igid is not None}"
      ] += 1
      messages[f"fbid_equals_actor_id={by_actor}"] += 1
      content_types[str(node.get("content_type"))] += 1
      content = node.get("content")
      typenames[str(content.get("__typename")) if isinstance(content, dict) else "none"] += 1

      for entry in node.get("msg_reactions") or []:
         reactions[
            f"fbid_is_viewer={entry.get('sender_fbid') == viewer_fbid}"
            f" igid_is_viewer={entry.get('sender_igid') == session.ds_user_id}"
         ] += 1

      paired = sorted(entry.get("sender_fbid") for entry in node.get("reactions") or [])
      igid_paired = sorted(entry.get("sender_fbid") for entry in node.get("msg_reactions") or [])
      reactions[f"reactions_and_msg_reactions_same_senders={paired == igid_paired}"] += 1

   return {
      "node_count": len(nodes),
      "messages": dict(messages),
      "reactions": dict(reactions),
      "content_types": dict(content_types),
      "content_typenames": dict(typenames),
   }


def _adopt() -> Session:
   environment = load_env()
   missing = [key for key in REQUIRED_CREDENTIAL_KEYS if not environment.get(key)]

   if missing:
      raise SystemExit(f"missing required keys in .env: {', '.join(missing)}")

   extra_cookies = {"mid": environment["IG_MID"]} if environment.get("IG_MID") else {}

   return Session(
      sessionid=environment["IG_SESSIONID"],
      ds_user_id=environment["IG_DS_USER_ID"],
      csrftoken=environment["IG_CSRFTOKEN"],
      extra_cookies=extra_cookies,
   )


async def _identity(sender: PacedSender, session: Session, report: dict[str, object]) -> None:
   await bootstrap(sender, session, user_agent=DEFAULT_USER_AGENT)

   report["actor_id_present"] = session.actor_id is not None

   inbox_payload = classify(
      await sender.send(build_inbox_listing_request(session, device_id=str(uuid.uuid4())))
   )
   inbox = parse_inbox_page(inbox_payload)
   viewer_fbid = inbox.mailbox_id
   report["mailbox_id_equals_actor_id"] = viewer_fbid == session.actor_id
   report["inbox_rows"] = len(inbox.page.items)

   rows = _dig(
      inbox_payload,
      ("data", "get_slide_mailbox_for_iris_subscription", "threads_by_folder", "edges"),
   )
   row_viewer_ids: collections.Counter[str] = collections.Counter()
   chosen: list[str] = []

   for edge in rows or []:
      row = _dig(edge, ("node", "as_ig_direct_thread")) or {}
      row_viewer = _dig(row, ("viewer", "interop_messaging_user_fbid"))
      row_viewer_ids[f"row_viewer_equals_mailbox_id={row_viewer == viewer_fbid}"] += 1
      row_messages = _dig(row, ("slide_messages", "edges")) or []
      senders = {_dig(message, ("node", "sender_fbid")) for message in row_messages}

      if viewer_fbid in senders and len(senders) > 1 and len(chosen) < 2:
         chosen.append(str(row.get("thread_fbid")))

   report["row_viewer_ids"] = dict(row_viewer_ids)
   report["threads_opened"] = len(chosen)
   report["threads"] = []

   for thread_fbid in chosen:
      payload = classify(await sender.send(build_thread_detail_request(session, thread_fbid)))
      report["threads"].append(_agreement(_thread_nodes(payload), viewer_fbid, session))  # type: ignore[attr-defined]


async def _mark_read(sender: PacedSender, session: Session, report: dict[str, object]) -> None:
   await bootstrap(sender, session, user_agent=DEFAULT_USER_AGENT)

   inbox = parse_inbox_page(
      classify(await sender.send(build_inbox_listing_request(session, device_id=str(uuid.uuid4()))))
   )
   read_rows = [
      row
      for row in inbox.page.items
      if not row.is_unread and not row.is_group and row.last_message_id is not None
   ]
   report["read_one_to_one_rows"] = len(read_rows)

   if not read_rows:
      report["stopped"] = "no one-to-one thread the viewer has already read, nothing sent"

      return

   target = read_rows[0]
   detail = classify(await sender.send(build_thread_detail_request(session, target.thread_fbid)))
   thread_id = parse_thread_id(detail)
   newest = next(
      (node for node in _thread_nodes(detail) if node.get("id") == target.last_message_id), None
   )
   report["thread_id_length"] = len(thread_id)
   report["newest_found_on_open"] = newest is not None

   if newest is None:
      report["stopped"] = "the inbox row's newest message was not on the open page, nothing sent"

      return

   message_id = str(newest["id"])
   referer = thread_url(target.thread_fbid)
   mark = build_graphql_request(
      session,
      MARK_READ,
      {
         "metadata": {"ig_thread_igid": thread_id},
         "data": {"item_id": "", "message_id": message_id},
      },
      referer=referer,
   )
   validation = build_graphql_request(
      session,
      MARK_READ_VALIDATION,
      {
         "metadata": {"ig_thread_igid": thread_id},
         "data": {"message_id": message_id, "message_timestamp_ms": str(newest["timestamp_ms"])},
      },
      referer=referer,
   )

   marked = await send_write(sender, session, WriteRequest(mark, "mark_thread_read"))
   receipt = _dig(marked, ("data", "xig_direct_item_seen_mutation_with_slide_messaging_response"))
   report["mark_read_answer"] = {
      "root_keys": sorted(receipt) if isinstance(receipt, dict) else repr(type(receipt)),
      "typename": receipt.get("__typename") if isinstance(receipt, dict) else None,
      "participant_is_mailbox_id": isinstance(receipt, dict)
      and receipt.get("participant_eimu_id") == inbox.mailbox_id,
      "watermark_at_or_after_newest": isinstance(receipt, dict)
      and int(receipt.get("watermark_timestamp_ms") or 0) >= int(newest["timestamp_ms"]),
   }

   validated = await send_write(
      sender, session, WriteRequest(validation, "mark_thread_read_validation")
   )
   report["validation_answer"] = _dig(validated, ("data", "xig_direct_mark_read_id_validation"))


async def run(stage: str) -> int:
   session = _adopt()
   transport = CappedTransport(HttpxTransport(cookies=cookies_for(session), proxy=session.proxy))
   report: dict[str, object] = {"stage": stage, "credentials_read_from_env": True}
   started = time.monotonic()
   kind = f"viewer-identity-{stage}"

   try:
      async with PacedSender(transport, Pacer()) as sender:
         if stage == "identity":
            await _identity(sender, session, report)
         else:
            await _mark_read(sender, session, report)
   except (DumpstagramError, RuntimeError) as failure:
      report["failed_with"] = type(failure).__name__
      report["failure_text"] = str(failure)[:200]
      kind += "-failed"

   report["requests"] = transport.sent
   report["elapsed_ms"] = int((time.monotonic() - started) * 1000)
   report_run(kind, report)

   return 0 if "failed_with" not in report else 3


def main() -> int:
   parser = argparse.ArgumentParser()
   parser.add_argument("--stage", choices=("identity", "mark-read"), required=True)
   parser.add_argument("--approve", default="")
   arguments = parser.parse_args()

   if arguments.stage == "mark-read" and arguments.approve != "mark-read":
      print("mark-read sends two writes: pass --approve mark-read")

      return 2

   return asyncio.run(run(arguments.stage))


if __name__ == "__main__":
   sys.exit(main())
