"""Read only. Two requests.

Why ``direct.notes()`` raised ``SchemaChanged`` on 2026-09-27: the notes tray answered an item
whose ``inbox_tray_item_type`` is ``ambient_data``, beside the notes. Reads the tray once and
logs every item's type and the keys each type carries, never a value. The answer is kept under
the skill's captures so a fixture can be pseudonymised from it.

   1  the inbox document, for fresh tokens (the bootstrap)
   2  the notes tray, IGDInboxTrayQuery, the verified read notes() sends

Run it from `engine/` with:

   uv run python probes/notes_tray_shape.py
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter

from _e2_support import E2Replay, dig, run_probe

from dumpstagram._private.web.requests.notes import build_inbox_tray_request

PLANNED = 2


async def body(replay: E2Replay) -> None:
   await replay.bootstrap()

   tray = await replay.engine_read(
      "notes tray", build_inbox_tray_request(replay.session, user_agent=replay.user_agent)
   )
   items = dig(tray, "data", "response", "inbox_tray_items") or []
   kinds = Counter(
      str(item.get("inbox_tray_item_type")) for item in items if isinstance(item, dict)
   )
   replay.record("item_kinds", dict(kinds))

   for kind in kinds:
      examples = [
         item
         for item in items
         if isinstance(item, dict) and item.get("inbox_tray_item_type") == kind
      ]
      replay.shape(f"tray_item_{kind}", examples)


if __name__ == "__main__":
   sys.exit(asyncio.run(run_probe("notes-tray-shape", PLANNED, 0, body)))
