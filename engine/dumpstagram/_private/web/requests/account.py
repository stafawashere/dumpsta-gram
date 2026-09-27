"""The viewer's own account reads: the pending follow requests and the activity feed.

Both are REST reads of the follow list's family and carry its header set, with the direct inbox
as referer, since a browser sent both inside its inbox load. The activity feed is a POST that
reads, and it carries the three headers a form body brings. A browser follows it with
``news/inbox_seen``, which nothing here builds (W74).
"""

from __future__ import annotations

from urllib.parse import urlencode

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, ORIGIN
from dumpstagram._private.web.requests.common import jazoest_for
from dumpstagram._private.web.requests.profiles import _rest_read_headers
from dumpstagram.errors import AuthenticationFailed
from dumpstagram.session import Session

__all__ = [
   "ACCOUNT_READ_REFERER",
   "build_activity_feed_request",
   "build_follow_requests_request",
]

ACCOUNT_READ_REFERER = f"{ORIGIN}/direct/inbox/"
"""The page a browser sent both reads from, the direct inbox."""

_FOLLOW_REQUESTS_URL = "https://www.instagram.com/api/v1/friendships/pending/"

_ACTIVITY_FEED_URL = "https://www.instagram.com/api/v1/news/inbox/"


def _account_read_headers(session: Session, web_session_id: str, user_agent: str) -> dict[str, str]:
   return {
      **_rest_read_headers(session, web_session_id, user_agent),
      "referer": ACCOUNT_READ_REFERER,
   }


def build_follow_requests_request(
   session: Session,
   *,
   web_session_id: str,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The pending follow requests, a GET with no query and no body.

   Finding: ``pending-follow-requests``.
   """

   return Request(
      method="GET",
      url=_FOLLOW_REQUESTS_URL,
      headers=_account_read_headers(session, web_session_id, user_agent),
      params={},
      follow_redirects=False,
   )


def build_activity_feed_request(
   session: Session,
   *,
   web_session_id: str,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The activity feed, a POST whose body is only ``fb_dtsg`` then ``jazoest``.

   That is the body both replays sent and both answered. The browser's body was 110 bytes whose
   field names the capture did not keep, so the order of the two is the replay's.

   Finding: ``activity-feed-inbox``.
   """

   token = session.fb_dtsg

   if not token:
      raise AuthenticationFailed(
         "session has no fb_dtsg, so it has not been bootstrapped since it was loaded"
      )

   spin = session.spin
   revision = (spin.revision if spin is not None else None) or ""
   fields = {"fb_dtsg": token, "jazoest": jazoest_for(token)}
   headers = {
      **_account_read_headers(session, web_session_id, user_agent),
      "content-type": "application/x-www-form-urlencoded",
      "origin": ORIGIN,
      "x-instagram-ajax": revision,
   }

   return Request(
      method="POST",
      url=_ACTIVITY_FEED_URL,
      headers=headers,
      content=urlencode(fields).encode("utf-8"),
      follow_redirects=False,
   )
