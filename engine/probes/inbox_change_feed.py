"""Read only by default. Two live requests, four with ``--stage full``, one more with a bootstrap.
With ``--send-arranged`` it writes twice, one direct message and its unsend, nine requests.

Step 21 of the build plan: does the inbox listing work as a change feed. Three properties decide
it: rows move when a thread gains a message, some field on the row changes when it does, and
nothing changes when nothing happened. The plan's five lines:

1. Inbox read. Per row on the first page: thread id, position, activity marker, newest message id.
2. Inbox read after ``--spacing`` seconds with nothing done. Every recorded value must match.
3. ``--stage full`` only. The probe waits at a prompt while the owner sends one message by hand,
   in the browser, to a thread that is not at the top of the inbox. The engine sends nothing.
   With ``--send-arranged`` the engine sends it instead, ruling 30: ``send_message`` into the
   thread named by ``--thread-fbid``, the owner-named target's thread, with the text in
   ``IG_DM_TEXT``, which never reaches the log. Nothing is sent without
   ``--approve send-message``.
4. Inbox read. The thread must be at position 0 with its marker advanced, every other row the same.
5. ``thread_messages`` on that thread with ``newer_than_message_id`` set to its newest message id
   from read 1. It must return exactly the new message with ``has_next_page`` false.

The default stage stops after line 2, because the owner has to be present for line 3. Line 5 goes
through ``IGDMessageListOffMsysQuery``, which does not mark the thread seen.

``--send-arranged`` adds what a write owes. Line 5's base is the target's newest message id from
read 1, or ``--base-message-id`` when read 1 listed no message there, the arranged message's
predecessor. A base that was not listed live cannot tell a filter from the newest page, so
line 5b then reads one other thread from read 4 with the second of its carried messages as the
base, where a filter returns one message and the newest page returns more. Then the arranged
message is unsent, the thread open and the unsend, and read 6 lists the inbox once more to
confirm it is gone. Nine requests, ten with a bootstrap. A ``CheckpointRequired`` stops the run
where it is, unsend included.

Every inbox read is built by ``build_inbox_listing_request``, classified by ``classify`` and
mapped by ``parse_inbox_listing``, the engine's own. One iris device id is minted per run and
sent on every read, as one open inbox page would. The raw payload is also checked key by key, so
the log does not rest on the mapper alone.

Recorded: per row the ``thread_fbid``, position, pin flag, ``last_activity_timestamp_ms`` and the
newest message id, plus whether the ids agree with each other and with the measured thread's
``fbid``, the page info, ``iris_inactive_subscription_uq_seq_id`` equality across reads, and
timings. No name, no title, no message text.

Run it from `engine/` with:

   uv run python probes/inbox_change_feed.py
   uv run python probes/inbox_change_feed.py --stage full
   uv run python probes/inbox_change_feed.py --stage full --send-arranged \\
      --approve send-message --thread-fbid FBID [--base-message-id MESSAGE_ID]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from _probe_support import SESSION_PATH, THREAD_FBID, load_env, report_run

from dumpstagram._core.direct import read_thread_messages
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._core.writes.direct import send_message, unsend_message
from dumpstagram._private.transport import HttpxTransport, Request, Response, cookies_for
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse.direct import (
   InboxMessage,
   InboxThread,
   parse_inbox_listing,
   parse_inbox_recent_messages,
)
from dumpstagram._private.web.requests.direct import build_inbox_listing_request
from dumpstagram.errors import CheckpointRequired, DumpstagramError
from dumpstagram.models import Page
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_THREAD_FBID", "IG_USER_AGENT", "IG_SESSION_FILE", "IG_DM_TEXT")

REQUEST_CAPS = {"reads": 3, "full": 5}
"""Two or four planned requests, one more for a bootstrap. The full stage's thread read reuses
the tokens the inbox reads already refreshed, so it has no bootstrap of its own to allow for."""

ARRANGED_REQUEST_CAP = 10
"""Reads 1, 2 and 4, the send, reads 5 and 5b, the thread open, the unsend and read 6, and one
bootstrap."""

SETTLE_SECONDS = 5.0
"""How long read 4 waits after the send's answer, so the listing is read after the send and
not raced against it."""

DEFAULT_SPACING_SECONDS = 60.0
"""The listener's default poll interval, ruling 9, so read 2 sees what a second poll would."""

MAILBOX_ROOT = "get_slide_mailbox_for_iris_subscription"


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


def row_record(position: int, thread: InboxThread) -> dict[str, object]:
   return {
      "position": position,
      "thread_fbid": thread.thread_fbid,
      "is_pinned": thread.is_pinned,
      "last_activity_ms": thread.last_activity_ms,
      "last_message_id": thread.last_message_id,
   }


def raw_checks(payload: Any, measured_thread_fbid: str) -> dict[str, object]:
   """What the raw payload says, independently of the mapper. Booleans, counts and lengths."""

   root = payload.get("data", {}).get(MAILBOX_ROOT, {})
   connection = root.get("threads_by_folder", {})
   rows = [edge["node"]["as_ig_direct_thread"] for edge in connection.get("edges", [])]
   pinned = root.get("pinned_threads_v2") or []
   row_ids = {row.get("id") for row in rows}

   activity = [int(row["last_activity_timestamp_ms"]) for row in rows]
   newest_first = activity == sorted(activity, reverse=True)

   first_message_matches_activity = []
   messages_newest_first = []
   message_counts = []

   for row in rows:
      message_nodes = [edge["node"] for edge in row["slide_messages"]["edges"]]
      stamps = [int(node["timestamp_ms"]) for node in message_nodes]
      message_counts.append(len(message_nodes))
      messages_newest_first.append(stamps == sorted(stamps, reverse=True))

      if stamps:
         first_message_matches_activity.append(stamps[0] == int(row["last_activity_timestamp_ms"]))

   measured_positions_by_fbid = [
      index for index, row in enumerate(rows) if row.get("thread_fbid") == measured_thread_fbid
   ]
   measured_positions_by_key = [
      index for index, row in enumerate(rows) if row.get("thread_key") == measured_thread_fbid
   ]
   uq_seq_id = root.get("iris_inactive_subscription_uq_seq_id")

   return {
      "mailbox_keys": sorted(root.keys()),
      "connection_keys": sorted(connection.keys()),
      "row_keys": sorted(rows[0].keys()) if rows else [],
      "row_count": len(rows),
      "rows_newest_activity_first": newest_first,
      "messages_per_row": sorted(set(message_counts)),
      "messages_newest_first_on_every_row": all(messages_newest_first),
      "first_message_timestamp_equals_activity": first_message_matches_activity.count(True),
      "first_message_timestamp_differs_from_activity": first_message_matches_activity.count(False),
      "id_equals_thread_fbid": sum(row.get("id") == row.get("thread_fbid") for row in rows),
      "thread_key_equals_thread_fbid": sum(
         row.get("thread_key") == row.get("thread_fbid") for row in rows
      ),
      "group_rows": sum(bool(row.get("is_group")) for row in rows),
      "pinned_rows": sum(bool(row.get("is_pin")) for row in rows),
      "pinned_threads_v2_count": len(pinned),
      "pinned_threads_v2_all_in_connection": all(
         (item.get("as_ig_direct_thread") or {}).get("id") in row_ids for item in pinned
      ),
      "measured_thread_positions_by_thread_fbid": measured_positions_by_fbid,
      "measured_thread_positions_by_thread_key": measured_positions_by_key,
      "uq_seq_id_type": type(uq_seq_id).__name__,
      "uq_seq_id": uq_seq_id,
   }


def page_record(page: Page[InboxThread]) -> dict[str, object]:
   return {
      "has_next_page": page.has_next_page,
      "end_cursor_length": len(page.end_cursor) if page.end_cursor else None,
      "rows": [row_record(position, thread) for position, thread in enumerate(page.items)],
   }


def compare_reads(first: dict[str, Any], second: dict[str, Any]) -> dict[str, object]:
   first_rows = first["rows"]
   second_rows = second["rows"]
   differing_positions = [
      position
      for position, (before, after) in enumerate(zip(first_rows, second_rows, strict=False))
      if before != after
   ]

   return {
      "every_row_identical": first_rows == second_rows,
      "row_count_equal": len(first_rows) == len(second_rows),
      "differing_positions": differing_positions,
      "has_next_page_equal": first["has_next_page"] == second["has_next_page"],
      "end_cursor_length_equal": first["end_cursor_length"] == second["end_cursor_length"],
   }


def without_position(rows: list[dict[str, Any]], excluded_fbid: str | None) -> list[dict[str, Any]]:
   return [
      {key: value for key, value in row.items() if key != "position"}
      for row in rows
      if row["thread_fbid"] != excluded_fbid
   ]


def judge_hand_message(first: dict[str, Any], after: dict[str, Any]) -> dict[str, object]:
   """Line 4: which thread moved to the top, and whether every other row stayed as it was."""

   before_by_fbid = {row["thread_fbid"]: row for row in first["rows"]}
   top = after["rows"][0] if after["rows"] else None
   top_fbid = top["thread_fbid"] if top else None
   moved = before_by_fbid.get(top_fbid) if top_fbid else None

   if top is None or moved is None:
      return {"top_thread_fbid": top_fbid, "top_was_listed_in_read_one": False}

   others_unchanged = without_position(first["rows"], top_fbid) == without_position(
      after["rows"], top_fbid
   )

   return {
      "top_thread_fbid": top_fbid,
      "top_was_listed_in_read_one": True,
      "top_position_in_read_one": moved["position"],
      "top_was_not_at_top_before": moved["position"] != 0,
      "marker_advanced": top["last_activity_ms"] > moved["last_activity_ms"],
      "last_message_id_changed": top["last_message_id"] != moved["last_message_id"],
      "other_rows_unchanged_apart_from_position": others_unchanged,
      "read_one_last_message_id": moved["last_message_id"],
   }


def rows_after_a_move(
   before: list[dict[str, Any]], after: list[dict[str, Any]], moved_fbid: str
) -> dict[str, object]:
   """Every row but the moved one: same values, and one place lower when it sat above the moved
   row's old place, the same place when it sat below. A row read 4 no longer lists fell off."""

   old_position = next(
      (row["position"] for row in before if row["thread_fbid"] == moved_fbid), len(before)
   )
   after_by_fbid = {row["thread_fbid"]: row for row in after}
   values_changed = []
   positions_unexpected = []
   fell_off = []

   for row in before:
      if row["thread_fbid"] == moved_fbid:
         continue

      later = after_by_fbid.get(row["thread_fbid"])

      if later is None:
         fell_off.append(row["position"])

         continue

      expected_position = row["position"] + 1 if row["position"] < old_position else row["position"]
      same_values = {key: value for key, value in row.items() if key != "position"} == {
         key: value for key, value in later.items() if key != "position"
      }

      if not same_values:
         values_changed.append(row["position"])

      if later["position"] != expected_position:
         positions_unexpected.append(row["position"])

   listed_before = {row["thread_fbid"] for row in before}
   newly_listed = [
      row["position"]
      for row in after
      if row["thread_fbid"] not in listed_before and row["thread_fbid"] != moved_fbid
   ]

   return {
      "every_other_row_unchanged": not values_changed and not positions_unexpected,
      "read_one_positions_with_changed_values": values_changed,
      "read_one_positions_not_where_expected": positions_unexpected,
      "read_one_positions_no_longer_listed": fell_off,
      "read_four_positions_newly_listed": newly_listed,
   }


def judge_arranged_message(
   first: dict[str, Any], after: dict[str, Any], target_fbid: str, sent_id: str
) -> dict[str, object]:
   """Line 4 for a message whose thread is known in advance."""

   before = next((row for row in first["rows"] if row["thread_fbid"] == target_fbid), None)
   later = next((row for row in after["rows"] if row["thread_fbid"] == target_fbid), None)

   judgement: dict[str, object] = {
      "target_listed_in_read_one": before is not None,
      "target_position_in_read_one": before["position"] if before else None,
      "target_was_at_top_before": before is not None and before["position"] == 0,
      "target_had_a_listed_message_in_read_one": bool(before and before["last_message_id"]),
      "target_listed_in_read_four": later is not None,
      "target_position_in_read_four": later["position"] if later else None,
      "target_moved_to_top": later is not None and later["position"] == 0,
      "newest_id_is_the_sent_message": later is not None and later["last_message_id"] == sent_id,
   }

   if before is not None and later is not None:
      judgement["marker_advanced"] = later["last_activity_ms"] > before["last_activity_ms"]
      judgement["marker_advance_ms"] = later["last_activity_ms"] - before["last_activity_ms"]

   judgement.update(rows_after_a_move(first["rows"], after["rows"], target_fbid))

   return judgement


def filter_control(
   after: dict[str, Any], carried: tuple[tuple[InboxMessage, ...], ...], target_fbid: str
) -> tuple[str, str, str] | None:
   """A thread from read 4 with at least two carried messages: its fbid, the second message's
   id as the base, and the newest id, the only one a filtering read may return."""

   for row, messages in zip(after["rows"], carried, strict=True):
      is_the_target = row["thread_fbid"] == target_fbid
      has_a_live_base = len(messages) >= 2

      if has_a_live_base and not is_the_target:
         return row["thread_fbid"], messages[1].id, messages[0].id

   return None


def describe_top_up(page: Page[Any], expected_ids: list[str]) -> dict[str, object]:
   ids = [message.id for message in page.items]

   return {
      "message_count": len(ids),
      "has_next_page": page.has_next_page,
      "message_ids": ids,
      "is_exactly_the_expected": ids == expected_ids,
   }


async def run_arranged(
   sender: PacedSender,
   session: Session,
   read_inbox: Any,
   first: dict[str, Any],
   arguments: argparse.Namespace,
   text: str,
   user_agent: str,
   report: dict[str, Any],
) -> None:
   target = arguments.thread_fbid
   target_before = next((row for row in first["rows"] if row["thread_fbid"] == target), None)
   report["arranged"] = arranged = {"target_thread_fbid": target, "text_length": len(text)}

   if target_before is not None and target_before["position"] == 0:
      arranged["moves_to_the_top_tested"] = False

   sent = await send_message(sender, session, target, text, user_agent=user_agent)
   arranged["sent"] = {
      "id": sent.id,
      "sent_at": sent.sent_at.isoformat(),
      "offline_threading_id": sent.offline_threading_id,
   }

   try:
      await asyncio.sleep(SETTLE_SECONDS)
      after = await read_inbox("read 4")
      report["arranged_message"] = judge_arranged_message(first, after, target, sent.id)

      live_base = target_before["last_message_id"] if target_before else None
      base = live_base or arguments.base_message_id
      arranged["read_five_base"] = base
      arranged["read_five_base_kind"] = (
         "the target's newest message listed in read 1"
         if live_base
         else "given, the arranged message's predecessor, not listed live in read 1"
      )

      if base:
         top_up = await read_thread_messages(
            sender, session, target, newer_than_message_id=base, user_agent=user_agent
         )
         report["top_up"] = describe_top_up(top_up, [sent.id])

      if not live_base:
         control = filter_control(after, after["carried"], target)
         report["filter_control"] = {"available": control is not None}

         if control is not None:
            thread_fbid, control_base, newest = control
            control_page = await read_thread_messages(
               sender,
               session,
               thread_fbid,
               newer_than_message_id=control_base,
               user_agent=user_agent,
            )
            report["filter_control"].update(
               {
                  "thread_fbid": thread_fbid,
                  "base": control_base,
                  "expected_newest": newest,
                  **describe_top_up(control_page, [newest]),
               }
            )
   except CheckpointRequired:
      arranged["unsent"] = False
      arranged["unsend_skipped_because"] = "CheckpointRequired"

      raise
   except Exception:
      await unsend_message(sender, session, target, sent.id, user_agent=user_agent)
      arranged["unsent"] = True

      raise

   await unsend_message(sender, session, target, sent.id, user_agent=user_agent)
   arranged["unsent"] = True

   final = await read_inbox("read 6")
   target_final = next((row for row in final["rows"] if row["thread_fbid"] == target), None)
   carried_ids = {message.id for messages in final["carried"] for message in messages}
   report["after_unsend"] = after_unsend = {
      "sent_id_still_carried_by_any_row": sent.id in carried_ids,
      "target_listed": target_final is not None,
      "target_position": target_final["position"] if target_final else None,
      "target_newest_id": target_final["last_message_id"] if target_final else None,
   }

   if target_final is not None and target_before is not None:
      after_unsend["target_newest_id_as_in_read_one"] = (
         target_final["last_message_id"] == target_before["last_message_id"]
      )
      after_unsend["target_marker_as_in_read_one"] = (
         target_final["last_activity_ms"] == target_before["last_activity_ms"]
      )


async def run(stage: str, spacing: float, arguments: argparse.Namespace) -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}
   send_arranged = arguments.send_arranged
   text = environment.get("IG_DM_TEXT", "")

   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   measured_thread_fbid = environment.get("IG_THREAD_FBID") or THREAD_FBID
   user_agent = environment.get("IG_USER_AGENT") or DEFAULT_USER_AGENT
   kind = f"inbox-change-feed-{stage}-arranged" if send_arranged else f"inbox-change-feed-{stage}"

   report: dict[str, object] = {
      "stage": stage,
      "spacing_seconds": spacing,
      "session_path": str(session_path),
      "credentials_read_from_env": False,
   }

   refusal = None

   if send_arranged and stage != "full":
      refusal = "--send-arranged needs --stage full"
   elif send_arranged and arguments.approve != "send-message":
      refusal = "not approved, pass --approve send-message"
   elif send_arranged and not arguments.thread_fbid:
      refusal = "--send-arranged needs --thread-fbid"
   elif send_arranged and not text:
      refusal = "no IG_DM_TEXT in .env"

   if refusal:
      report["failed_with"] = refusal
      report_run(f"{kind}-refused", report)

      return 2

   if not session_path.exists():
      report["failed_with"] = "no session file, run probes/adopt_and_save.py first"
      report_run(f"{kind}-failed", report)

      return 2

   session = Session.load(session_path)
   cap = ARRANGED_REQUEST_CAP if send_arranged else REQUEST_CAPS[stage]
   transport = CappedTransport(
      HttpxTransport(cookies=cookies_for(session), proxy=session.proxy), cap
   )
   device_id = str(uuid.uuid4())
   reads: list[dict[str, Any]] = []
   report["reads"] = reads
   report["requests"] = transport.sent

   async with PacedSender(transport, Pacer()) as sender:

      async def read_inbox(label: str) -> dict[str, Any]:
         async def attempt() -> Any:
            if not session.fb_dtsg:
               await bootstrap(sender, session, user_agent=user_agent)

            request = build_inbox_listing_request(
               session, device_id=device_id, user_agent=user_agent
            )

            return classify(await sender.send(request))

         payload = await with_token_recovery(attempt, sender=sender, session=session)
         page = parse_inbox_listing(payload)
         record: dict[str, Any] = {"label": label}
         record["raw"] = raw_checks(payload, measured_thread_fbid)
         record.update(page_record(page))
         reads.append(record)

         return {**record, "carried": parse_inbox_recent_messages(payload)}

      try:
         first = await read_inbox("read 1")
         await asyncio.sleep(spacing)
         second = await read_inbox("read 2")

         report["no_change_comparison"] = compare_reads(first, second)
         report["uq_seq_id_equal"] = first["raw"]["uq_seq_id"] == second["raw"]["uq_seq_id"]

         if send_arranged:
            await run_arranged(
               sender, session, read_inbox, first, arguments, text, user_agent, report
            )
         elif stage == "full":
            print("Send one message by hand to a thread that is not at the top, then press Enter.")
            await asyncio.to_thread(input)

            after = await read_inbox("read 4")
            judgement = judge_hand_message(first, after)
            report["hand_message"] = judgement

            since = judgement.get("read_one_last_message_id")
            top_thread = judgement.get("top_thread_fbid")
            can_top_up = isinstance(since, str) and isinstance(top_thread, str)

            if can_top_up:
               top_up = await read_thread_messages(
                  sender,
                  session,
                  str(top_thread),
                  newer_than_message_id=str(since),
                  user_agent=user_agent,
               )
               report["top_up"] = {
                  "message_count": len(top_up.items),
                  "has_next_page": top_up.has_next_page,
                  "message_ids": [message.id for message in top_up.items],
                  "matches_the_new_newest_id": [message.id for message in top_up.items]
                  == [after["rows"][0]["last_message_id"]],
               }
      except (DumpstagramError, RuntimeError, KeyError, TypeError, ValueError) as failure:
         report["failed_with"] = type(failure).__name__
         report["failure_text"] = str(failure)[:200]
         report["requests_spent"] = len(transport.sent)
         report_run(f"{kind}-failed", report)

         return 3

   report["requests_spent"] = len(transport.sent)
   report_run(kind, report)

   return 0


def main() -> int:
   parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
   parser.add_argument("--stage", choices=sorted(REQUEST_CAPS), default="reads")
   parser.add_argument("--spacing", type=float, default=DEFAULT_SPACING_SECONDS)
   parser.add_argument("--send-arranged", action="store_true")
   parser.add_argument("--approve", default="")
   parser.add_argument("--thread-fbid", default="")
   parser.add_argument("--base-message-id", default="")
   arguments = parser.parse_args()

   return asyncio.run(run(arguments.stage, arguments.spacing, arguments))


if __name__ == "__main__":
   sys.exit(main())
