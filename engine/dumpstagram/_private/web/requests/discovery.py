"""The discovery reads: the explore grid, a place's header and grid, and the new posts check.

The explore grid is a REST GET on the follow list's header set with the explore page as referer.
The rest are persisted queries. A place's two reads carry the place's page as referer and the
new posts check the site root, as ``probes/e2_discovery_feeds.py`` sent them.
"""

from __future__ import annotations

import re
from typing import Any

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, ORIGIN
from dumpstagram._private.web.documents.discovery import (
   LOCATION_INFO,
   LOCATION_POSTS,
   NEW_FEED_POSTS,
)
from dumpstagram._private.web.requests.common import build_graphql_request
from dumpstagram._private.web.requests.profiles import _rest_read_headers
from dumpstagram.models import LocationTab
from dumpstagram.session import Session

__all__ = [
   "EXPLORE_PARAMETERS",
   "EXPLORE_REFERER",
   "LOCATION_PAGE_SIZE",
   "build_explore_grid_request",
   "build_location_info_request",
   "build_location_posts_request",
   "build_new_feed_posts_request",
   "location_page_url",
   "refuse_what_is_not_a_location_id",
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
"""The five query parameters the recorded browse sent and both replays sent, as sent. What a
later page adds is not observed (W77)."""

LOCATION_PAGE_SIZE = 12
"""The ``first`` both grid replays sent. The answers carried 21 and 24 edges, so it shapes the
request and predicts nothing about the answer."""

SHORT_DRAMA_PROVIDER = "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider"
"""The one provider flag the grid carries, false, as the replays sent it."""

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
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The explore grid's first page, a GET carrying the five observed parameters.

   Finding: ``read-the-explore-grid``.
   """

   return Request(
      method="GET",
      url=_EXPLORE_GRID_URL,
      headers={
         **_rest_read_headers(session, web_session_id, user_agent),
         "referer": EXPLORE_REFERER,
      },
      params=dict(EXPLORE_PARAMETERS),
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
