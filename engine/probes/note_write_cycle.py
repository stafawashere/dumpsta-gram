"""Writes twice, the owner's own note only. Five live requests, six with a bootstrap.

One note set for close friends and one delete of the note it made, approved by the owner on
2026-09-23 (ruling 30 in the build plan). The set replaces any note the owner has up, which the
owner allowed, and the account ends with no note. The note is visible to the owner's close
friends list for about the write floor, 30 s.

Step 14's live acceptance run. Everything goes through the public ``AsyncClient`` under the
default behavior: ``notes``, ``set_note`` with ``NoteAudience.CLOSE_FRIENDS``, ``notes``
confirming exactly one item authored by the viewer with the returned id and audience,
``delete_note`` with that id, and ``notes`` confirming the viewer has none.

The only thing the probe adds is a counter around ``HttpxTransport.send``, which also refuses a
seventh request. The note text is ``IG_NOTE_TEXT`` from ``.env``, chosen by the owner, and only
its length is recorded. Recorded otherwise: tray counts, the viewer's own item id and audience
at each read, each request's friendly name, status and length, and timings.

It sends nothing without ``--approve set-note``. Run it from `engine/` with:

   uv run python probes/note_write_cycle.py --approve set-note
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from _probe_support import SESSION_PATH, load_env, report_run

from dumpstagram._private.transport import HttpxTransport, Request, Response
from dumpstagram.aio import AsyncClient
from dumpstagram.errors import DumpstagramError
from dumpstagram.models import Note, NoteAudience
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE")

REQUEST_CAP = 6


def describe(notes: tuple[Note, ...], viewer_id: str) -> dict[str, object]:
   own_notes = [note for note in notes if note.author_id == viewer_id]

   return {
      "item_count": len(notes),
      "own_count": len(own_notes),
      "own_ids": [note.id for note in own_notes],
      "own_audiences": [note.audience.name.lower() for note in own_notes],
   }


async def run(approved: bool) -> int:
   everything = load_env()
   environment = {key: value for key, value in everything.items() if key in NON_CREDENTIAL_KEYS}
   note_text = everything.get("IG_NOTE_TEXT", "")

   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT")

   report: dict[str, object] = {"session_path": str(session_path), "approved": approved}

   if not approved:
      report["failed_with"] = "not approved, pass --approve set-note"
      report_run("note-write-cycle-refused", report)

      return 2

   if not note_text:
      report["failed_with"] = "no IG_NOTE_TEXT in .env"
      report_run("note-write-cycle-failed", report)

      return 2

   report["note_text_length"] = len(note_text)

   session = Session.load(session_path)
   viewer_id = session.ds_user_id
   report["session_had_actor_id"] = session.actor_id is not None

   sent: list[dict[str, object]] = []
   started_at = time.monotonic()
   original_send = HttpxTransport.send

   async def counted_send(transport: HttpxTransport, request: Request) -> Response:
      if len(sent) >= REQUEST_CAP:
         raise RuntimeError(f"refusing request {len(sent) + 1}, the cap is {REQUEST_CAP}")

      entry: dict[str, object] = {
         "name": request.headers.get("x-fb-friendly-name", "document"),
         "offset_ms": int((time.monotonic() - started_at) * 1000),
      }
      sent.append(entry)

      response = await original_send(transport, request)
      entry["status"] = response.status_code
      entry["length"] = len(response.content)

      return response

   HttpxTransport.send = counted_send  # type: ignore[method-assign]
   reads: list[dict[str, object]] = []
   report["reads"] = reads
   report["requests"] = sent

   try:
      async with AsyncClient(session, user_agent=user_agent) as client:
         reads.append(describe(await client.notes(), viewer_id))

         created = await client.set_note(note_text, audience=NoteAudience.CLOSE_FRIENDS)
         report["created"] = {
            "id": created.id,
            "audience": created.audience.name.lower(),
            "author_is_viewer": created.author_id == viewer_id,
            "text_matches": created.text == note_text,
         }

         middle = describe(await client.notes(), viewer_id)
         reads.append(middle)

         await client.delete_note(created.id)

         after = describe(await client.notes(), viewer_id)
         reads.append(after)
   except DumpstagramError as failure:
      report["failed_with"] = type(failure).__name__
      report["failure_text"] = str(failure)[:200]
      report_run("note-write-cycle-failed", report)

      return 3
   finally:
      HttpxTransport.send = original_send  # type: ignore[method-assign]

   session.save(session_path)

   exactly_one_own_with_the_id = middle["own_ids"] == [created.id]
   listed_for_close_friends = middle["own_audiences"] == ["close_friends"]
   ends_with_none = after["own_count"] == 0

   report["requests_spent"] = len(sent)
   report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
   report["exactly_one_own_note_with_the_returned_id"] = exactly_one_own_with_the_id
   report["listed_for_close_friends"] = listed_for_close_friends
   report["ends_with_no_own_note"] = ends_with_none

   report_run("note-write-cycle", report)

   return 0


if __name__ == "__main__":
   parser = argparse.ArgumentParser()
   parser.add_argument("--approve", default="")
   arguments = parser.parse_args()

   sys.exit(asyncio.run(run(arguments.approve == "set-note")))
