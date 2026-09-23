"""Writes twice, the owner's own note only. Six live requests, seven if close friends is refused.

One note set with the close friends audience and one delete of the note it made, approved by
the owner on 2026-09-23 (ruling 30 in the build plan). The set replaces whatever note the owner
has up, which the owner allowed, and the delete leaves the account with no note. The note is
visible to the owner's close friends list for the roughly half a minute between the writes.

Step 14's discovery run, done from the engine side under ruling 23, which allows no browser
load. It replays the two note mutations with requests built by the engine's own
``build_graphql_request`` and sends them through ``send_write``, and answers:

- whether the ``actorID`` the bootstrap now harvests is 17 digits and differs from
  ``ds_user_id``, and whether the create accepts it as ``actor_id``
- whether the create accepts audience 1, which no create has sent before, and whether the
  created item and the tray both carry it back
- the create answer's key shape, which the engine maps into ``Note``
- whether the delete answers a null root and the tray then holds no note by the viewer

The sequence is: a bootstrap, a tray read, the set, a tray read, the delete, a tray read. If
the upstream refuses audience 1, the refusal is recorded and the set is sent once more with
audience 0, and only then does the run go on. The doc_id values live in this file, not in the
package, because neither finding had its second observation when it ran.

The note text is ``IG_NOTE_TEXT`` from ``.env``, chosen by the owner, and only its length is
recorded. Recorded otherwise: key names, types and lengths of each answer, the audience and
note_style numbers, whether ids match, and timings.

It sends nothing without ``--approve set-note``. Run it from `engine/` with:

   uv run python probes/note_discovery.py --approve set-note
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import Any

from _probe_support import SESSION_PATH, load_env, report_run

from dumpstagram._core.notes import find_own_note, read_notes
from dumpstagram._core.pacer import Pacer, WritePolicy
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.writing import send_write
from dumpstagram._private.transport import (
   HttpxTransport,
   Request,
   Response,
   WriteRequest,
   cookies_for,
)
from dumpstagram._private.web.bootstrap import BOOTSTRAP_URL, DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.documents import PersistedQuery
from dumpstagram._private.web.requests import build_graphql_request
from dumpstagram.errors import DumpstagramError
from dumpstagram.models import Note
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE")

REQUEST_CAP = 7

CLOSE_FRIENDS = 1
MUTUAL_FOLLOWS = 0

CREATE_NOTE = PersistedQuery(
   doc_id="28592645767037889",
   friendly_name="usePolarisCreateInboxTrayItemSubmitMutation",
   finding_id="set-my-own-note-on-the-direct-inbox",
)
DELETE_NOTE = PersistedQuery(
   doc_id="28419182984337833",
   friendly_name="usePolarisDeleteInboxTrayItemSubmitMutation",
   finding_id="delete-my-own-note-on-the-direct-inbox",
)

WRITE_POLICY = WritePolicy(stop_after_unrecognised_rejection=False)
"""The probe decides by hand what follows a refused audience, so the fallback set can go."""


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


def shape_of(value: Any) -> Any:
   """Key names, types and string lengths, and no value."""

   if isinstance(value, dict):
      return {key: shape_of(inner) for key, inner in sorted(value.items())}

   if isinstance(value, list):
      return [shape_of(value[0])] if value else []

   if isinstance(value, str):
      return f"str:{len(value)}"

   if value is None:
      return None

   return type(value).__name__


def describe_tray(notes: tuple[Note, ...], viewer_id: str) -> dict[str, object]:
   own_notes = [note for note in notes if note.author_id == viewer_id]
   own = find_own_note(notes, viewer_id)

   described: dict[str, object] = {"item_count": len(notes), "own_count": len(own_notes)}

   if own is not None:
      described["own_id"] = own.id
      described["own_text_length"] = len(own.text)
      described["own_audience"] = int(own.audience)

   return described


def create_variables(actor_id: str, text: str, audience: int, number: int) -> dict[str, Any]:
   return {
      "input": {
         "actor_id": actor_id,
         "additional_params": {"note_create_params": {"note_style": 0, "text": text}},
         "audience": audience,
         "client_mutation_id": str(number),
         "inbox_tray_item_type": "note",
      }
   }


def describe_create_answer(payload: Any, viewer_id: str, text: str) -> dict[str, object]:
   data = payload.get("data") if isinstance(payload, dict) else None
   root = data.get("xdt_create_inbox_tray_item") if isinstance(data, dict) else None
   item = root.get("inbox_tray_item") if isinstance(root, dict) else None
   note = item.get("note_dict") if isinstance(item, dict) else None

   described: dict[str, object] = {"shape": shape_of(payload)}

   if isinstance(item, dict) and isinstance(note, dict):
      described["item_id"] = item.get("inbox_tray_item_id")
      described["audience"] = note.get("audience")
      described["note_style"] = note.get("note_style")
      described["author_is_viewer"] = str(note.get("author_id")) == viewer_id
      described["text_matches"] = note.get("text") == text

   return described


async def run(approved: bool) -> int:
   everything = load_env()
   environment = {key: value for key, value in everything.items() if key in NON_CREDENTIAL_KEYS}
   note_text = everything.get("IG_NOTE_TEXT", "")

   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT") or DEFAULT_USER_AGENT

   report: dict[str, object] = {"session_path": str(session_path), "approved": approved}

   if not approved:
      report["failed_with"] = "not approved, pass --approve set-note"
      report_run("note-discovery-refused", report)

      return 2

   if not session_path.exists() or not note_text:
      report["failed_with"] = "no session file or no IG_NOTE_TEXT in .env"
      report_run("note-discovery-failed", report)

      return 2

   report["note_text_length"] = len(note_text)

   session = Session.load(session_path)
   viewer_id = session.ds_user_id
   transport = CappedTransport(HttpxTransport(cookies=cookies_for(session), proxy=session.proxy))
   steps: list[dict[str, object]] = []
   report["steps"] = steps

   async with PacedSender(transport, Pacer(), writes=WRITE_POLICY) as sender:

      async def read_tray(label: str) -> dict[str, object]:
         step: dict[str, object] = {"read": label}
         steps.append(step)

         try:
            notes = await read_notes(sender, session, user_agent=user_agent)
         except DumpstagramError as failure:
            step["failed_with"] = type(failure).__name__
            step["failure_text"] = str(failure)[:200]

            return step

         step.update(describe_tray(notes, viewer_id))

         return step

      async def write(
         query: PersistedQuery, variables: dict[str, Any]
      ) -> tuple[Any, dict[str, object]]:
         request = build_graphql_request(
            session, query, variables, referer=BOOTSTRAP_URL, user_agent=user_agent
         )
         step: dict[str, object] = {"write": query.friendly_name}
         steps.append(step)

         try:
            payload = await send_write(sender, session, WriteRequest(request, query.friendly_name))
         except DumpstagramError as failure:
            step["failed_with"] = type(failure).__name__
            step["failure_code"] = getattr(failure, "code", None)
            step["failure_text"] = str(failure)[:200]

            return None, step

         return payload, step

      try:
         await bootstrap(sender, session, user_agent=user_agent)
      except DumpstagramError as failure:
         report["failed_with"] = type(failure).__name__
         report["requests"] = transport.sent
         report_run("note-discovery-failed", report)

         return 3

      actor_id = session.actor_id or ""
      is_seventeen_digits = actor_id.isdigit() and len(actor_id) == 17
      differs_from_viewer = actor_id != viewer_id
      report["actor_id_length"] = len(actor_id)
      report["actor_id_is_seventeen_digits"] = is_seventeen_digits
      report["actor_id_differs_from_ds_user_id"] = differs_from_viewer

      before = await read_tray("before")
      tray_answered = "failed_with" not in before
      actor_id_usable = is_seventeen_digits and differs_from_viewer
      may_write = tray_answered and actor_id_usable

      if not may_write:
         report["stopped_before_writing"] = "the tray read failed or the actor id is unusable"
         report["requests"] = transport.sent
         report_run("note-discovery-stopped", report)

         return 4

      audience_sent = CLOSE_FRIENDS
      payload, step = await write(
         CREATE_NOTE,
         create_variables(actor_id, note_text, CLOSE_FRIENDS, sender.pacer.next_write_number()),
      )
      step["audience_sent"] = CLOSE_FRIENDS

      if payload is None:
         report["close_friends_refused"] = True
         audience_sent = MUTUAL_FOLLOWS
         payload, step = await write(
            CREATE_NOTE,
            create_variables(actor_id, note_text, MUTUAL_FOLLOWS, sender.pacer.next_write_number()),
         )
         step["audience_sent"] = MUTUAL_FOLLOWS

      report["audience_sent"] = audience_sent

      if payload is None:
         report["stopped_after"] = "both sets were refused"
         await read_tray("after_refused_sets")
         report["requests"] = transport.sent
         report_run("note-discovery-stopped", report)

         return 5

      created = describe_create_answer(payload, viewer_id, note_text)
      step["answer"] = created
      created_id = created.get("item_id")

      middle = await read_tray("after_set")
      middle["own_id_matches_created"] = middle.get("own_id") == created_id

      own_id = middle.get("own_id") or created_id
      delete_payload, delete_step = await write(DELETE_NOTE, {"inbox_tray_item_id": own_id})
      delete_step["sent_created_id"] = own_id == created_id

      if delete_payload is not None:
         data = delete_payload.get("data") if isinstance(delete_payload, dict) else None
         delete_step["top_level_keys"] = sorted(delete_payload.keys())
         delete_step["data_keys"] = sorted(data.keys()) if isinstance(data, dict) else None
         delete_step["root_is_null"] = (
            isinstance(data, dict)
            and "xdt_delete_inbox_tray_item" in data
            and data["xdt_delete_inbox_tray_item"] is None
         )

      after = await read_tray("after_delete")

   session.save(session_path)

   report["requests"] = transport.sent
   report["requests_spent"] = len(transport.sent)
   report["elapsed_ms"] = int((time.monotonic() - transport.started_at) * 1000)
   report["ends_with_no_own_note"] = after.get("own_count") == 0

   report_run("note-discovery", report)

   return 0


if __name__ == "__main__":
   parser = argparse.ArgumentParser()
   parser.add_argument("--approve", default="")
   arguments = parser.parse_args()

   sys.exit(asyncio.run(run(arguments.approve == "set-note")))
