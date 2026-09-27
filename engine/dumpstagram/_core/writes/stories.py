"""Mark one story item seen, sent once through ``_core/writing.py``.

The item's owner sees the viewer in the item's seen list, so this is a write another person can
see, and it counts against the write budget like any write. Marking an item already seen was
not observed. The mutation's answer is its only confirmation: a highlight read carries no seen
field, and a live reel's seen state is on its tray row, which the tray read reconciles.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.writing import send_write
from dumpstagram._private.transport import WriteRequest
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.parse.stories import story_was_marked_seen
from dumpstagram._private.web.requests.stories import build_story_seen_request
from dumpstagram.errors import UpstreamRejected
from dumpstagram.models import StoryItem, StoryReel
from dumpstagram.session import Session

__all__ = ["mark_story_item_seen"]

NOT_MARKED_SEEN = "story_not_marked_seen"
"""The code raised when the answer carries no seen response, never observed."""


async def mark_story_item_seen(
   sender: PacedSender,
   session: Session,
   reel: StoryReel,
   item: StoryItem,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   clock: Callable[[], float] = time.time,
) -> None:
   """Mark ``item`` of ``reel`` seen. One write, and one bootstrap first when the session
   carries no page token.

   The reel id comes from ``reel`` and the owner, the pk and the time posted from ``item``, so
   an item that is not one of ``reel``'s raises :class:`ValueError` before anything is sent:
   a caller cannot pair an item with another reel's id. The time of viewing is ``clock`` when the
   write is built, in whole seconds, as the browser sent it.
   """

   is_in_the_reel = item in reel.items

   if not is_in_the_reel:
      raise ValueError(
         f"item {item.pk} is not one of the items of reel {reel.id}; "
         "pass the StoryReel the item was read in"
      )

   if not session.fb_dtsg:
      await bootstrap(sender, session, user_agent=user_agent)

   request = build_story_seen_request(
      session,
      reel_id=reel.id,
      item_pk=item.pk,
      owner_id=item.owner_id,
      taken_at=int(item.taken_at.timestamp()),
      viewed_at=int(clock()),
      user_agent=user_agent,
   )
   payload = await send_write(sender, session, WriteRequest(request, "mark_story_seen"))

   if not story_was_marked_seen(payload):
      raise UpstreamRejected(
         "the seen mutation was answered without an error but with no seen response",
         code=NOT_MARKED_SEEN,
      )
