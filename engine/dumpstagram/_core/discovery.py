"""The explore grid, a place's header and grid, the new posts check, the reels feed, and an
audio's page, asynchronously.

Each read is one request sent alone. A browser reads the explore grid and a place's two reads
inside the page loads of ``/explore/`` and ``/explore/locations/<pk>/``, and polls the new posts
check from the home page; the page loads are not modelled, a named departure from ADR-0013 as
every read before these. An audio's page is read as its page reads it, without the page's
document (W116). A browser on ``/reels/`` also plays each reel and reports the view, and
asks for an ads pool; the engine plays nothing, so neither is sent (W101). None of them changes
anything another person can see.
"""

from __future__ import annotations

from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse.discovery import (
   parse_audio_page,
   parse_explore_grid,
   parse_location_info,
   parse_location_posts,
   parse_new_feed_posts,
   parse_reels_feed_page,
)
from dumpstagram._private.web.requests.discovery import (
   build_audio_page_request,
   build_explore_grid_request,
   build_location_info_request,
   build_location_posts_request,
   build_new_feed_posts_request,
   build_reels_feed_first_page_request,
   build_reels_feed_next_page_request,
   refuse_what_is_not_a_location_id,
   refuse_what_is_not_an_audio_id,
)
from dumpstagram._private.web.requests.profiles import new_web_session_id
from dumpstagram.models import (
   AudioPage,
   ExploreGrid,
   LocationPosts,
   LocationTab,
   Page,
   Place,
   Post,
)
from dumpstagram.session import Session

__all__ = [
   "REELS_CURSOR_SEPARATOR",
   "audio_clips_page",
   "explore_posts_page",
   "read_audio_page",
   "read_explore_grid",
   "read_location_info",
   "read_location_posts",
   "read_new_feed_posts",
   "read_reels_feed_page",
   "reels_cursor",
   "split_reels_cursor",
]

REELS_CURSOR_SEPARATOR = ":"
"""What joins the reels a page showed to the upstream's cursor in the cursor a reels page hands
out.

The next page query is keyed on the previous page's cursor and on ``seen_reels``, the reels
already shown, so the cursor carries both and a caller carries nothing else (W101). The reels are
their numeric pks joined by commas, which neither part holds; the upstream's cursors were
URL-safe base64 on all four answers read, and only the first separator is split on.
"""

_SEEN_REEL_SEPARATOR = ","


def reels_cursor(seen_reel_pks: tuple[str, ...], upstream_cursor: str) -> str:
   seen = _SEEN_REEL_SEPARATOR.join(seen_reel_pks)

   return f"{seen}{REELS_CURSOR_SEPARATOR}{upstream_cursor}"


def split_reels_cursor(after: str) -> tuple[tuple[str, ...], str]:
   """The reels already shown and the upstream cursor a reels page's ``end_cursor`` carries.

   Raises :class:`ValueError` for anything a reels page did not hand out, before anything is
   sent.
   """

   seen, separator, upstream_cursor = after.partition(REELS_CURSOR_SEPARATOR)
   seen_reel_pks = tuple(seen.split(_SEEN_REEL_SEPARATOR)) if seen else ()
   names_only_reels = all(pk.isascii() and pk.isdigit() for pk in seen_reel_pks)
   is_a_reels_cursor = bool(separator) and names_only_reels and bool(upstream_cursor)

   if not is_a_reels_cursor:
      raise ValueError(
         "a reels cursor is the end_cursor of a page feeds.reels returned, "
         "not a cursor from another read"
      )

   return seen_reel_pks, upstream_cursor


def _public_reels_page(page: Page[Post]) -> Page[Post]:
   """``page`` with its cursor joined to the pks of the reels it holds, which the next page names
   as seen."""

   upstream_cursor = page.end_cursor
   end_cursor = None

   if upstream_cursor is not None:
      shown = tuple(reel.pk for reel in page.items)
      end_cursor = reels_cursor(shown, upstream_cursor)

   return Page(items=page.items, has_next_page=page.has_next_page, end_cursor=end_cursor)


def explore_posts_page(grid: ExploreGrid) -> Page[Post]:
   """An explore page as the page walk reads it: every post in the grid's order, the upstream's
   ``more_available`` as the terminator, and the root ``max_id`` as the cursor (W115)."""

   return Page(items=grid.posts, has_next_page=grid.more_available, end_cursor=grid.end_cursor)


def audio_clips_page(page: AudioPage) -> Page[Post]:
   """An audio page as the page walk reads it: its reels, the upstream's ``more_available`` as the
   terminator, and ``paging_info.max_id`` as the cursor (W116)."""

   return Page(items=page.clips, has_next_page=page.more_available, end_cursor=page.end_cursor)


async def read_explore_grid(
   sender: PacedSender,
   session: Session,
   *,
   after: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> ExploreGrid:
   """One page of the explore grid, the first when ``after`` is None, one live request (W77,
   W115).

   ``after`` is a previous page's ``end_cursor``, the root ``max_id``, sent back as it came. The
   GET carries no page token, so no bootstrap is spent on it, as with the followers page.
   """

   async def attempt() -> ExploreGrid:
      request = build_explore_grid_request(
         session, web_session_id=new_web_session_id(), after=after, user_agent=user_agent
      )
      response = await sender.send(request)

      return parse_explore_grid(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_location_info(
   sender: PacedSender,
   session: Session,
   location_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> Place:
   """The header of the place whose ``pk`` is ``location_id``, one live request (W78)."""

   refuse_what_is_not_a_location_id(location_id)

   async def attempt() -> Place:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_location_info_request(session, location_id, user_agent=user_agent)
      response = await sender.send(request)

      return parse_location_info(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_location_posts(
   sender: PacedSender,
   session: Session,
   location_id: str,
   *,
   tab: LocationTab = LocationTab.RANKED,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> LocationPosts:
   """The first page of the place's grid, one live request (W79)."""

   refuse_what_is_not_a_location_id(location_id)
   tab = LocationTab(tab)

   async def attempt() -> LocationPosts:
      lacks_page_tokens = not session.fb_dtsg or not session.bloks_version_id

      if lacks_page_tokens:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_location_posts_request(session, location_id, tab=tab, user_agent=user_agent)
      response = await sender.send(request)

      return parse_location_posts(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_new_feed_posts(
   sender: PacedSender,
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> bool:
   """Whether the home feed has new posts, one live request (W80)."""

   async def attempt() -> bool:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_new_feed_posts_request(session, user_agent=user_agent)
      response = await sender.send(request)

      return parse_new_feed_posts(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_reels_feed_page(
   sender: PacedSender,
   session: Session,
   *,
   after: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> Page[Post]:
   """One page of the reels feed, the first when ``after`` is None, one live request (W101).

   ``after`` is a previous page's ``end_cursor``, which carries the upstream's cursor and the
   reels that page showed; anything else raises :class:`ValueError` before anything is sent.
   """

   next_page_key = None if after is None else split_reels_cursor(after)

   async def attempt() -> Page[Post]:
      lacks_page_tokens = not session.fb_dtsg or not session.bloks_version_id

      if lacks_page_tokens:
         await bootstrap(sender, session, user_agent=user_agent)

      if next_page_key is None:
         request = build_reels_feed_first_page_request(session, user_agent=user_agent)
      else:
         seen_reel_pks, upstream_cursor = next_page_key
         request = build_reels_feed_next_page_request(
            session,
            cursor=upstream_cursor,
            seen_reel_pks=seen_reel_pks,
            user_agent=user_agent,
         )

      response = await sender.send(request)

      return _public_reels_page(parse_reels_feed_page(classify(response)))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_audio_page(
   sender: PacedSender,
   session: Session,
   audio_id: str,
   *,
   after: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> AudioPage:
   """One page of the audio whose id is ``audio_id``, the first when ``after`` is None, one live
   request (W116).

   ``audio_id`` must be digits, refused before anything is sent. The form carries the page token
   and ``lsd``, so a session without them is bootstrapped first.
   """

   refuse_what_is_not_an_audio_id(audio_id)

   async def attempt() -> AudioPage:
      lacks_page_tokens = not session.fb_dtsg or not session.lsd

      if lacks_page_tokens:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_audio_page_request(session, audio_id, after=after, user_agent=user_agent)
      response = await sender.send(request)

      return parse_audio_page(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)
