"""The home timeline request."""

from __future__ import annotations

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, ORIGIN
from dumpstagram._private.web.documents.feed import HOME_TIMELINE_FEED
from dumpstagram._private.web.requests.common import build_graphql_request
from dumpstagram.session import Session

__all__ = [
   "FEED_DEVICE_ID",
   "FEED_PAGE_SIZE",
   "build_feed_page_request",
]

FEED_PAGE_SIZE = 12
"""What the web client asks the timeline for, and advisory rather than binding.

Three observations of this exact value returned 14, 12 and 5 edges, so the number shapes the
request and predicts nothing about the answer. The web client's value is sent because a
different one is a difference a fingerprint check can read, and because no other value has
been measured.
"""

FEED_DEVICE_ID = "0905A51C-CD35-4174-84B3-5E0C764E353B"
"""The ``device_id`` the timeline query carries.

Not a device fingerprint and not derived from anything local. It is one opaque value observed
on the measured request, reproduced because the field is required to be present and only this
value has ever been sent. Whether the upstream validates it at all is unmeasured, which is why
it is a constant here rather than something generated per session.
"""


def build_feed_page_request(
   session: Session,
   *,
   after: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """One page of the signed-in account's home timeline.

   ``after`` is the previous page's ``end_cursor``, and ``None`` asks for the first page. The
   same query serves both, so there is no first-page variant to get wrong.

   The relay provider flags carry the values the web client sent on the measured request.
   They select experiment branches rather than data, and none was ablated, so they are
   reproduced rather than reasoned about.

   This request goes to a different path from every other query in the registry, which
   :data:`~dumpstagram._private.web.documents.common.GRAPHQL_QUERY_URL` explains.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/home-timeline-feed-page.md``.
   """

   variables = {
      "after": after,
      "before": None,
      "data": {
         "device_id": FEED_DEVICE_ID,
         "is_async_ads_double_request": "0",
         "is_async_ads_in_headload_enabled": "0",
         "is_async_ads_rti": "0",
         "rti_delivery_backend": "0",
      },
      "first": FEED_PAGE_SIZE,
      "last": None,
      "variant": "home",
      "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": False,
      "__relay_internal__pv__PolarisMultiCaptionCarouselEnabledrelayprovider": True,
      "__relay_internal__pv__PolarisReelsRecoDebugOverlayEnabledrelayprovider": False,
      "__relay_internal__pv__PolarisAdDebugToolEnabledrelayprovider": False,
   }

   return build_graphql_request(
      session,
      HOME_TIMELINE_FEED,
      variables,
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )
