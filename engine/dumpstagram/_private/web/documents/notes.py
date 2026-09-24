"""The notes tray on the direct inbox, and setting and deleting the viewer's own note."""

from __future__ import annotations

from dumpstagram._private.web.documents.common import PersistedQuery

__all__ = [
   "CREATE_NOTE",
   "DELETE_NOTE",
   "INBOX_TRAY",
]

INBOX_TRAY = PersistedQuery(
   doc_id="29231580869776032",
   friendly_name="IGDInboxTrayQuery",
   finding_id="read-the-notes-tray-on-the-direct-inbox",
)
"""The notes tray on the direct inbox, one note per author, in one unpaged call.

It takes no variables. An inbox load sends it as one of the ten queries of its direct block,
within 4 ms of the others, and the viewer's own note is the item authored by ``ds_user_id``.

Verified six times across four runs between 2026-09-21 and 2026-09-23, replays and browser
loads both. The id was unchanged throughout, and an inbox cold load later on 2026-09-23 sent it
again.
"""

CREATE_NOTE = PersistedQuery(
   doc_id="28592645767037889",
   friendly_name="usePolarisCreateInboxTrayItemSubmitMutation",
   finding_id="set-my-own-note-on-the-direct-inbox",
)
"""Set the viewer's note, replacing any note already up. The note composer's Share holds it.

The input names the account by its Facebook-side ``actor_id``, never ``ds_user_id``, and the
answer carries the created item in the shape the tray lists it. Observed from the composer on
2026-09-21 with audience 0, and sent by the engine on 2026-09-23 with audience 1, close
friends, which the answer and the tray both carried back.
"""

DELETE_NOTE = PersistedQuery(
   doc_id="28419182984337833",
   friendly_name="usePolarisDeleteInboxTrayItemSubmitMutation",
   finding_id="delete-my-own-note-on-the-direct-inbox",
)
"""Delete the viewer's note, keyed on the tray item id, the one variable it takes.

A delete answers its root field null with no error, and that null is the success: two browser
deletes on 2026-09-21 and one engine delete on 2026-09-23 answered so, and a tray read after
each found no note by the viewer.
"""
