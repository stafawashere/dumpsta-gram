"""The discovery reads: the explore grid, a place's header and grid, the new posts check, the
reels feed, and an audio's page.

The explore grid is a REST GET on the follow list's header set with the explore page as referer,
and a later page adds ``max_id``. An audio's page is a REST form POST in the comet envelope with
the header set the audio page sent, ``x-fb-lsd`` and ``x-ig-d`` and no ``x-csrftoken``, as
``probes/e2_last_reads_replay.py --stage audio`` sent it.
The rest are persisted queries. A place's two reads carry the place's page as referer and the
new posts check the site root, as ``probes/e2_discovery_feeds.py`` sent them. Both reels feed
pages carry ``/reels/``, as ``probes/e2_capture_replays.py --stage reels`` sent them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlencode

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, ORIGIN
from dumpstagram._private.web.documents.discovery import (
   LOCATION_INFO,
   LOCATION_POSTS,
   NEW_FEED_POSTS,
   REELS_FEED_FIRST_PAGE,
   REELS_FEED_NEXT_PAGE,
)
from dumpstagram._private.web.requests.common import build_graphql_request, jazoest_for
from dumpstagram._private.web.requests.profiles import _rest_read_headers
from dumpstagram.errors import AuthenticationFailed
from dumpstagram.models import LocationTab
from dumpstagram.session import Session

__all__ = [
   "AUDIO_PAGE_ROUTE",
   "EXPLORE_PARAMETERS",
   "EXPLORE_REFERER",
   "LOCATION_PAGE_SIZE",
   "REELS_CONTAINER_MODULE",
   "REELS_FIRST_PAGE_SIZE",
   "REELS_NEXT_PAGE_SIZE",
   "REELS_PAGE_URL",
   "audio_page_url",
   "build_audio_page_request",
   "build_explore_grid_request",
   "build_location_info_request",
   "build_location_posts_request",
   "build_new_feed_posts_request",
   "build_reels_feed_first_page_request",
   "build_reels_feed_next_page_request",
   "location_page_url",
   "refuse_what_is_not_a_location_id",
   "refuse_what_is_not_an_audio_id",
   "seen_reels_text",
]

_EXPLORE_GRID_URL = "https://www.instagram.com/api/v1/discover/web/explore_grid/"

EXPLORE_REFERER = f"{ORIGIN}/explore/"
"""The page a browser reads the grid from."""

EXPLORE_PARAMETERS = {
   "include_fixed_destinations": "true",
   "is_nonpersonalized_explore": "false",
   "is_prefetch": "false",
   "module": "explore_popular",
   "omit_cover_media": "false",
}
"""The five query parameters the recorded browse sent and both replays sent, as sent. A later
page adds ``max_id`` between ``is_prefetch`` and ``module``, the place the browser's six later
pages sent it (W115)."""

_AUDIO_PAGE_URL = "https://www.instagram.com/api/v1/clips/music/"

AUDIO_PAGE_ROUTE = "comet.igweb.PolarisClipsAudioRoute"
"""The ``__crn`` the audio page's POST carried, on both captured audio pages."""

_AUDIO_ID = re.compile(r"[0-9]{1,30}")

_ASBD_ID = "359341"

LOCATION_PAGE_SIZE = 12
"""The ``first`` both grid replays sent. The answers carried 21 and 24 edges, so it shapes the
request and predicts nothing about the answer."""

SHORT_DRAMA_PROVIDER = "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider"
"""The one provider flag the grid carries, false, as the replays sent it."""

RECO_DEBUG_PROVIDER = "__relay_internal__pv__PolarisReelsRecoDebugOverlayEnabledrelayprovider"
"""The reels feed's second provider flag, false on both pages, as the browser sent it."""

REELS_PAGE_URL = f"{ORIGIN}/reels/"
"""The reels tab, the referer of both reels feed pages."""

REELS_CONTAINER_MODULE = "clips_tab_desktop_page"
"""The ``data.container_module`` a 1192 px wide ``/reels/`` tab sent on both pages."""

REELS_FIRST_PAGE_SIZE = 2
"""The ``first`` the tab's first page sent. The replays answered 1 and 2 reels for it."""

REELS_NEXT_PAGE_SIZE = 10
"""The ``first`` the tab's next page sent. The replays answered 4 reels for it."""

_LOCATION_ID = re.compile(r"[0-9]{1,30}")


def refuse_what_is_not_a_location_id(location_id: str) -> None:
   """Raise :class:`ValueError` for anything but digits, before anything is built or sent.

   A place's reads are keyed on its ``pk``, and what they answer for a slug or a name is
   unobserved.
   """

   is_a_location_id = _LOCATION_ID.fullmatch(location_id) is not None

   if not is_a_location_id:
      raise ValueError(
         f"{location_id!r} is not a numeric place id. Pass Location.id or Place.id, not a name"
      )


def location_page_url(location_id: str) -> str:
   """The place's page, the referer of both its reads."""

   return f"{ORIGIN}/explore/locations/{location_id}/"


def build_explore_grid_request(
   session: Session,
   *,
   web_session_id: str,
   after: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """One page of the explore grid, a GET carrying the five observed parameters, and ``max_id``
   on a later page, the previous page's root ``max_id``.

   The browser sent the six in alphabetical order on every later page, so ``max_id`` goes where
   that order puts it.

   Findings: ``read-the-explore-grid`` and ``read-the-explore-grid-next-page``.
   """

   params = dict(EXPLORE_PARAMETERS)

   if after is not None:
      params = dict(sorted({**params, "max_id": after}.items()))

   return Request(
      method="GET",
      url=_EXPLORE_GRID_URL,
      headers={
         **_rest_read_headers(session, web_session_id, user_agent),
         "referer": EXPLORE_REFERER,
      },
      params=params,
      follow_redirects=False,
   )


def refuse_what_is_not_an_audio_id(audio_id: str) -> None:
   """Raise :class:`ValueError` for anything but digits, before anything is built or sent.

   An audio's page is keyed on the numeric id its address carries, and what it answers for a
   title or a name is unobserved.
   """

   is_an_audio_id = _AUDIO_ID.fullmatch(audio_id) is not None

   if not is_an_audio_id:
      raise ValueError(
         f"{audio_id!r} is not a numeric audio id. Pass Post.audio_id or MediaAudio.audio_id, "
         "not a title"
      )


def audio_page_url(audio_id: str) -> str:
   """The audio's page, the referer of its reads."""

   return f"{ORIGIN}/reels/audio/{audio_id}/"


def build_audio_page_request(
   session: Session,
   audio_id: str,
   *,
   after: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """One page of the audio's page, a form POST, the first when ``after`` is None.

   The form is the one the page sent: ``audio_cluster_id``, ``max_id`` and
   ``original_sound_audio_asset_id`` first, both ids the audio's, ``max_id`` empty on the first
   page as the browser sent it on both audio pages and the previous page's ``paging_info.max_id``
   after it, then the comet envelope without the fields the engine has never produced (``__s``,
   ``__dyn``, ``__csr`` and the rest), the delete post form's subset. The headers are the page's:
   ``x-fb-lsd`` and ``x-ig-d``, no ``x-csrftoken``, no ``x-ig-app-id``. The page's
   ``qpl_active_flow_ids`` field and ``x-fb-qpl-active-flows`` header, seen once, are not sent.
   The audio id is not checked here; the capability refuses anything but digits first.

   Findings: ``read-an-audio-page`` and ``read-an-audio-page-next-page``.
   """

   token = session.fb_dtsg

   if not token:
      raise AuthenticationFailed(
         "session has no fb_dtsg, so it has not been bootstrapped since it was loaded"
      )

   spin = session.spin
   revision = (spin.revision if spin is not None else None) or ""
   fields = {
      "audio_cluster_id": audio_id,
      "max_id": after or "",
      "original_sound_audio_asset_id": audio_id,
      "__d": "www",
      "__user": "0",
      "__a": "1",
      "__req": "1",
      "__hs": session.haste_session or "",
      "dpr": "2",
      "__ccg": "EXCELLENT",
      "__rev": revision,
      "__hsi": session.hsi or "",
      "__comet_req": "7",
      "fb_dtsg": token,
      "jazoest": jazoest_for(token),
      "lsd": session.lsd or "",
      "__spin_r": revision,
      "__spin_b": (spin.branch if spin is not None else None) or "",
      "__spin_t": (spin.timestamp if spin is not None else None) or "",
      "__crn": AUDIO_PAGE_ROUTE,
   }
   headers = {
      "accept": "*/*",
      "accept-language": "en-US,en;q=0.9",
      "content-type": "application/x-www-form-urlencoded",
      "origin": ORIGIN,
      "referer": audio_page_url(audio_id),
      "sec-fetch-dest": "empty",
      "sec-fetch-mode": "cors",
      "sec-fetch-site": "same-origin",
      "user-agent": user_agent,
      "x-asbd-id": _ASBD_ID,
      "x-fb-lsd": session.lsd or "",
      "x-ig-d": "www",
      "x-ig-max-touch-points": "0",
   }

   return Request(
      method="POST",
      url=_AUDIO_PAGE_URL,
      headers=headers,
      content=urlencode(fields).encode("utf-8"),
      follow_redirects=False,
   )


def build_location_info_request(
   session: Session,
   location_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The header of the place whose ``pk`` is ``location_id``.

   Finding: ``read-a-location-s-info``.
   """

   return build_graphql_request(
      session,
      LOCATION_INFO,
      {"location_id_str": location_id, "show_nearby": False},
      referer=location_page_url(location_id),
      user_agent=user_agent,
   )


def build_location_posts_request(
   session: Session,
   location_id: str,
   *,
   tab: LocationTab = LocationTab.RANKED,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The first page of the place's grid, ``after`` null, as both replays sent it.

   Finding: ``read-a-location-page-tab``.
   """

   variables: dict[str, Any] = {
      "location_id": location_id,
      "first": LOCATION_PAGE_SIZE,
      "after": None,
      "tab": tab.value,
      "page_size_override": None,
      SHORT_DRAMA_PROVIDER: False,
   }

   return build_graphql_request(
      session,
      LOCATION_POSTS,
      variables,
      referer=location_page_url(location_id),
      user_agent=user_agent,
   )


def build_new_feed_posts_request(
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Whether the home feed has new posts, no variables, the site root as referer.

   Finding: ``check-for-new-feed-posts``.
   """

   return build_graphql_request(
      session,
      NEW_FEED_POSTS,
      {},
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )


def seen_reels_text(reel_pks: Sequence[str]) -> str:
   """``data.seen_reels`` as the browser sent it: a JSON string, not an object, listing ``{"id":
   <pk>}`` for each reel already shown, the numeric pk without its ``_<author id>``, compact."""

   return json.dumps([{"id": pk} for pk in reel_pks], separators=(",", ":"))


def build_reels_feed_first_page_request(
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The reels feed's first page, every variable a constant, in the browser's order.

   Finding: ``read-the-reels-tab-first-page``.
   """

   variables = {
      "data": {"container_module": REELS_CONTAINER_MODULE},
      "first": REELS_FIRST_PAGE_SIZE,
      "useChannelsPagination": False,
      RECO_DEBUG_PROVIDER: False,
      SHORT_DRAMA_PROVIDER: False,
   }

   return build_graphql_request(
      session,
      REELS_FEED_FIRST_PAGE,
      variables,
      referer=REELS_PAGE_URL,
      user_agent=user_agent,
   )


def build_reels_feed_next_page_request(
   session: Session,
   *,
   cursor: str,
   seen_reel_pks: Sequence[str],
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The reels feed's page after ``cursor``, with the reels already shown as ``seen_reels``.

   Finding: ``read-the-reels-tab-next-page``.
   """

   variables = {
      "after": cursor,
      "before": None,
      "data": {
         "container_module": REELS_CONTAINER_MODULE,
         "seen_reels": seen_reels_text(seen_reel_pks),
      },
      "first": REELS_NEXT_PAGE_SIZE,
      "last": None,
      RECO_DEBUG_PROVIDER: False,
      SHORT_DRAMA_PROVIDER: False,
   }

   return build_graphql_request(
      session,
      REELS_FEED_NEXT_PAGE,
      variables,
      referer=REELS_PAGE_URL,
      user_agent=user_agent,
   )
