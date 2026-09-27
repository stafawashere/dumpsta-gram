"""The viewer's own account reads: the pending follow requests, the activity feed, the saved
posts and collections, and the close friends list.

The follow requests and the activity feed are REST reads of the follow list's family and carry
its header set, with the direct inbox as referer, since a browser sent both inside its inbox
load. The activity feed is a POST that reads, and it carries the three headers a form body
brings. A browser follows it with ``news/inbox_seen``, which nothing here builds (W74).

The saved posts are a REST GET of the same family and the saved collections a persisted query,
both with the site root as referer, since a browser's is the viewer's own saved page and the
engine does not hold the viewer's username (W105, W106). The close friends list is a Bloks app
fetch, the comet form the settings page posts (W107). The page's ``close_friend_count_updater``
action, whose effect is UNRESOLVED, is never built here.
"""

from __future__ import annotations

from urllib.parse import urlencode

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, ORIGIN
from dumpstagram._private.web.documents.account import SAVED_COLLECTIONS
from dumpstagram._private.web.requests.common import build_graphql_request, jazoest_for
from dumpstagram._private.web.requests.profiles import _rest_read_headers
from dumpstagram.errors import AuthenticationFailed, SchemaChanged
from dumpstagram.session import Session

__all__ = [
   "ACCOUNT_READ_REFERER",
   "CLOSE_FRIENDS_APP_ID",
   "CLOSE_FRIENDS_PAGE",
   "SAVED_COLLECTION_TYPES",
   "build_activity_feed_request",
   "build_close_friends_request",
   "build_follow_requests_request",
   "build_saved_collections_request",
   "build_saved_posts_request",
]

ACCOUNT_READ_REFERER = f"{ORIGIN}/direct/inbox/"
"""The page a browser sent both reads from, the direct inbox."""

_FOLLOW_REQUESTS_URL = "https://www.instagram.com/api/v1/friendships/pending/"

_ACTIVITY_FEED_URL = "https://www.instagram.com/api/v1/news/inbox/"

_SAVED_POSTS_URL = "https://www.instagram.com/api/v1/feed/saved/posts/"

_BLOKS_APP_URL = "https://www.instagram.com/async/wbloks/fetch/"

CLOSE_FRIENDS_APP_ID = "com.instagram.portable_settings.privacy.close_friends_screen_v2"
"""The Bloks app the close friends settings screen fetches."""

CLOSE_FRIENDS_PAGE = f"{ORIGIN}/accounts/close_friends/"
"""The settings page a browser fetches the close friends app from, and the fetch's referer."""

_CLOSE_FRIENDS_ROUTE = "comet.igweb.PolarisSettingsCloseFriendsRoute"

SAVED_COLLECTION_TYPES = ("ALL_MEDIA_AUTO_COLLECTION", "MEDIA", "AUDIO_AUTO_COLLECTION")
"""The ``collection_types`` a browser's saved tab sent, a constant in this order."""

SAVED_COLLECTIONS_PAGE_SIZE = 12


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


def build_saved_posts_request(
   session: Session,
   *,
   web_session_id: str,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The first page of the viewer's saved "All posts" view, a GET with no query and no body.

   A browser's referer is ``/<username>/saved/all-posts/``, which needs the viewer's username,
   so the site root is sent, as the profile tabs do (W105).

   Finding: ``read-all-saved-posts``.
   """

   return Request(
      method="GET",
      url=_SAVED_POSTS_URL,
      headers=_rest_read_headers(session, web_session_id, user_agent),
      params={},
      follow_redirects=False,
   )


def build_saved_collections_request(
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The first page of the viewer's saved tab, the variables a browser sent on opening it and
   the site root as referer, for the reason :func:`build_saved_posts_request` gives.

   Finding: ``read-saved-posts``.
   """

   variables = {
      "collection_types": list(SAVED_COLLECTION_TYPES),
      "first": SAVED_COLLECTIONS_PAGE_SIZE,
   }

   return build_graphql_request(
      session, SAVED_COLLECTIONS, variables, referer=f"{ORIGIN}/", user_agent=user_agent
   )


def build_close_friends_request(
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The close friends settings screen's Bloks app, ``type`` app and ``params`` an empty object.

   The body is the comet form the settings page posts, without the fields the engine has never
   produced (``__s``, ``__dyn``, ``__csr``, ``__hsdp``, ``__hblp`` and ``__sjsp``), the subset the
   delete post form sends, and the headers are the ones the page's fetch carried, no ``x-``
   header among them. ``__bkv`` is the Bloks version id the bootstrap reads, so a session without
   one is refused rather than sent with an empty version.

   Finding: ``read-the-close-friends-list``.
   """

   token = session.fb_dtsg

   if not token:
      raise AuthenticationFailed(
         "session has no fb_dtsg, so it has not been bootstrapped since it was loaded"
      )

   bloks_version = session.bloks_version_id

   if not bloks_version:
      raise SchemaChanged(
         "the bootstrap page carried no WebBloksVersioningID, so the Bloks fetch of the close "
         "friends screen cannot name its version",
         path="WebBloksVersioningID",
      )

   spin = session.spin
   revision = (spin.revision if spin is not None else None) or ""
   query = urlencode({"appid": CLOSE_FRIENDS_APP_ID, "type": "app", "__bkv": bloks_version})
   fields = {
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
      "__crn": _CLOSE_FRIENDS_ROUTE,
      "params": "{}",
   }
   headers = {
      "accept": "*/*",
      "accept-language": "en-US,en;q=0.9",
      "content-type": "application/x-www-form-urlencoded",
      "origin": ORIGIN,
      "referer": CLOSE_FRIENDS_PAGE,
      "sec-fetch-dest": "empty",
      "sec-fetch-mode": "cors",
      "sec-fetch-site": "same-origin",
      "user-agent": user_agent,
   }

   return Request(
      method="POST",
      url=f"{_BLOKS_APP_URL}?{query}",
      headers=headers,
      content=urlencode(fields).encode("utf-8"),
      follow_redirects=False,
   )
