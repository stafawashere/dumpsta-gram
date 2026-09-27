"""The stories tray, one account's live stories and one highlight, asynchronously.

Each read is one query sent alone with the site root as referer. A browser reads the tray inside
a page load and a reel when the story viewer opens, and it then marks each item it shows seen
with a separate mutation. The engine sends no seen mutation, which is W68's named departure from
W6 until the arranged run of E2 batch 12 verifies the mutation on the owner's own story, so a
story read through the engine today does not put the viewer in anyone's seen list.
"""

from __future__ import annotations

from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
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
) -> StoryReel | None:
   """The live stories of the account whose numeric id is ``user_id``, one live request, ``None``
   when it has none (W70)."""

   refuse_what_is_not_a_user_id(user_id)

   async def attempt() -> StoryReel | None:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_story_reel_request(session, user_id, user_agent=user_agent)
      response = await sender.send(request)

      return parse_story_reel(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_highlight(
   sender: PacedSender,
   session: Session,
   highlight_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> StoryReel:
   """The highlight whose id is ``highlight_id``, one live request (W70)."""

   refuse_what_is_not_a_highlight_id(highlight_id)

   async def attempt() -> StoryReel:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_highlight_request(session, highlight_id, user_agent=user_agent)
      response = await sender.send(request)

      return parse_highlight_reel(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)
