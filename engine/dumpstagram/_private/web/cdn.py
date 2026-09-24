"""The request that fetches one media rendition from Instagram's CDN.

Every rendition URL on the home timeline and the post query sat on hosts under
:data:`CDN_HOST_FAMILY`, one per point of presence such as ``scontent-lga3-3``, so the transport
that fetches them is pinned to the family rather than to one host. The URL is signed by the
upstream and is fetched exactly as the payload named it. Five fetches on 2026-09-23, with no
cookie on any of them, answered 200 with the body inline, no redirect, no ``set-cookie`` and no
``content-encoding``. Three of the four that recorded it declared a ``content-length`` equal to
the bytes sent, and the fourth declared none, so the length is checked only where it is given.

The headers are the ones those fetches carried. Music cover artwork was seen on a second family,
``fbcdn.net``, and never fetched, so nothing here reaches it.

Finding: ``skills/reverse-engineer/knowledge/endpoints/cdn-media-rendition-download.md``.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import ORIGIN

__all__ = ["CDN_HOST_FAMILY", "CDN_MAX_CONNECTIONS", "build_rendition_request"]

CDN_HOST_FAMILY = "cdninstagram.com"
"""The domain every rendition host sat under. A host must be a subdomain of it."""

CDN_MAX_CONNECTIONS = 4
"""The most CDN connections one client holds at once, so concurrent downloads are bounded. Four is
the concurrency the prior project's browser script downloaded media with."""

MEDIA_REFERER = f"{ORIGIN}/"


def build_rendition_request(url: str, *, user_agent: str) -> Request:
   """A cookieless GET of one signed rendition URL, redirects not followed.

   A URL that is not ``https`` raises :class:`ValueError` before anything is sent. The host is
   left to the transport's pin, which refuses anything outside the family.
   """

   scheme = urlsplit(url).scheme

   if scheme != "https":
      raise ValueError("a rendition is fetched over https only")

   return Request(
      method="GET",
      url=url,
      headers={"user-agent": user_agent, "referer": MEDIA_REFERER, "accept": "*/*"},
      follow_redirects=False,
   )
