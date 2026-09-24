"""Typed representations of the notes tray on the direct inbox.

Every field below was observed on live `IGDInboxTrayQuery` responses, 13 items on 2026-09-21 and
15 on 2026-09-23, recorded in
`skills/reverse-engineer/knowledge/endpoints/read-the-notes-tray-on-the-direct-inbox.md`.

Fields the upstream sends and these models do not carry are named in
`dumpstagram/_private/web/parse/notes.py` beside the mapping that drops them.

Nothing here parses. Construction is done by the mapper in `_private/web/parse/notes.py`, which
reads named keys and raises rather than filling a default, so an upstream rename is loud.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum

__all__ = ["Note", "NoteAudience"]


class NoteAudience(IntEnum):
   """Who a note is shown to.

   The values are the web client's own, read out of its ``PolarisNotesTypes`` module on
   2026-09-23, where the enum is ``MUTUAL_FOLLOWS`` 0, ``BESTIES`` 1 and ``INTERNAL`` 2. The
   note composer offers the first two, labelled "Followers you follow back" and "Close
   Friends", and its close friends choice carries the value 1. ``INTERNAL`` is declared by the
   client and offered only to Meta's own staff, so it is listed for the same reason every slot
   of :class:`~dumpstagram.models.FeedItemKind` is listed: a value outside the three is a
   :class:`~dumpstagram.errors.SchemaChanged`, not a member invented at runtime.

   Only 0 and 1 have been seen in a tray, and only 0 has been sent by a create.
   """

   MUTUAL_FOLLOWS = 0
   CLOSE_FRIENDS = 1
   INTERNAL = 2


@dataclass(frozen=True)
class Note:
   """One note in the tray, one per author.

   ``id`` is the tray item's own identifier, 17 digits on every measured item. It is the value
   a delete names, and it is not the author's id.

   ``author_id`` is the author's numeric Instagram account id, the one
   :attr:`~dumpstagram.models.Profile.id` carries and the ``ds_user_id`` cookie holds for the
   viewer. The viewer's own note is the item whose ``author_id`` equals the viewer's
   ``ds_user_id``, and it is absent when the viewer has none. The Facebook-side id the same
   account has elsewhere is a different number and never appears here.

   ``text`` is empty rather than absent on a note that carries only a song, which is how
   seven of the fifteen items measured on 2026-09-23 arrived.

   ``author_username`` comes from the tray's picture of the author, and is ``None`` when that
   picture names some other account, which has not been observed.
   """

   id: str
   author_id: str
   text: str
   audience: NoteAudience
   created_at: datetime
   is_emoji_only: bool
   author_username: str | None = None
