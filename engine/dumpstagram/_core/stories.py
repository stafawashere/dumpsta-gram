"""The stories tray, one account's live stories and one highlight, asynchronously.

Each read is one query sent alone with the site root as referer. A browser reads the tray inside
a page load and a reel when the story viewer opens, and it then marks each item it shows seen
with a separate mutation, starting with the first. With ``mark_first_item_seen`` a reel or
highlight read is followed by that mutation for its first item, one write, which is what the
namespace asks for under the default behavior (W94). The tray read marks nothing, as a browser's
tray marks nothing.
"""

from __future__ import annotations

from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._core.writes.stories import mark_story_item_seen
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse.stories import (
   parse_highlight_reel,
   parse_stories_tray,
   parse_story_reel,
)
from dumpstagram._private.web.requests.profiles import refuse_what_is_not_a_user_id
from dumpstagram._private.web.requests.stories import (
   build_highlight_request,
   build_stories_tray_request,
   build_story_reel_request,
   refuse_what_is_not_a_highlight_id,
)
from dumpstagram.models import StoryReel, TrayReel
from dumpstagram.session import Session

__all__ = ["read_highlight", "read_stories_tray", "read_story_reel"]


async def read_stories_tray(
   sender: PacedSender,
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> tuple[TrayReel, ...]:
   """The stories tray, one live request (W69)."""

   async def attempt() -> tuple[TrayReel, ...]:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_stories_tray_request(session, user_agent=user_agent)
      response = await sender.send(request)

      return parse_stories_tray(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_story_reel(
   sender: PacedSender,
   session: Session,
   user_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
   mark_first_item_seen: bool = False,
) -> StoryReel | None:
   """The live stories of the account whose numeric id is ``user_id``, one live request, ``None``
   when it has none (W70). With ``mark_first_item_seen``, a reel with items is followed by the
   seen mutation for its first item, one write outside the read's token recovery, so the read
   is never sent again because the write failed and the write is never sent twice (W94)."""

   refuse_what_is_not_a_user_id(user_id)

   async def attempt() -> StoryReel | None:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_story_reel_request(session, user_id, user_agent=user_agent)
      response = await sender.send(request)

      return parse_story_reel(classify(response))

   reel = await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)

   if reel is None:
      return None

   if mark_first_item_seen:
      await _mark_the_first_item_seen(sender, session, reel, user_agent=user_agent)

   return reel


async def read_highlight(
   sender: PacedSender,
   session: Session,
   highlight_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
   mark_first_item_seen: bool = False,
) -> StoryReel:
   """The highlight whose id is ``highlight_id``, one live request (W70), followed with
   ``mark_first_item_seen`` by the seen mutation for its first item, as :func:`read_story_reel`
   (W94)."""

   refuse_what_is_not_a_highlight_id(highlight_id)

   async def attempt() -> StoryReel:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_highlight_request(session, highlight_id, user_agent=user_agent)
      response = await sender.send(request)

      return parse_highlight_reel(classify(response))

   highlight = await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)

   if mark_first_item_seen:
      await _mark_the_first_item_seen(sender, session, highlight, user_agent=user_agent)

   return highlight


async def _mark_the_first_item_seen(
   sender: PacedSender,
   session: Session,
   reel: StoryReel,
   *,
   user_agent: str,
) -> None:
   """The item a browser shows first when the viewer opens, and so the one it marks first. A reel
   with no items has nothing shown and nothing marked."""

   if not reel.items:
      return

   await mark_story_item_seen(sender, session, reel, reel.items[0], user_agent=user_agent)
