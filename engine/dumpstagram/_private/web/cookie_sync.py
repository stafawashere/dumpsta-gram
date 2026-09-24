"""The four requests of the page-load cookie sync, and how to read their answers.

Seconds after a page loads, the page mounts a hidden facebook.com iframe. Once it is ready, two
flows run side by side: the page exchanges the ``fr`` it keeps in ``localStorage`` for the
current one, and the iframe fetches an encrypted blob from facebook.com that the page posts
back to instagram.com. Every captured load sent all four, from ``run-2026-09-23-003559``,
``run-2026-09-23-004555`` and ``run-2026-09-23-022159``.

The two facebook.com requests go through the cookieless transport and carry what the iframe
document carries, read from that document the way the bootstrap reads its own page. The two
instagram.com requests carry the session's page envelope.

Left out, as the GraphQL builder leaves them out: ``__s``, ``__dyn``, ``__csr``, ``__hsdp``,
``__hblp`` and ``__sjsp``, which the page computes from the modules it has loaded rather than
reading them from anywhere, and ``__crn``. ``__req`` is sent as ``1``. The iframe also posts
``/ajax/qm/`` to facebook.com, which has no finding and is not sent.

Findings: ``facebook-cookie-sync-iframe-document``, ``get-encrypted-fr-cookie``,
``facebook-cookie-sync-fetch`` and ``instagram-cookie-sync-post``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode, urlsplit

from dumpstagram._private.transport import Request, Response
from dumpstagram._private.web.bootstrap import (
   DEFAULT_USER_AGENT,
   ORIGIN,
   PageParameters,
   read_page_parameters,
)
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.documents.page_load import GET_FR_COOKIE
from dumpstagram._private.web.requests.common import build_graphql_request, jazoest_for
from dumpstagram.errors import SchemaChanged
from dumpstagram.session import Session

__all__ = [
   "FACEBOOK_SYNC_URL",
   "INSTAGRAM_SYNC_URL",
   "LOGIN_SYNC_URL",
   "build_facebook_sync_request",
   "build_fr_cookie_request",
   "build_iframe_document_request",
   "build_instagram_sync_request",
   "read_fr",
   "read_iframe_parameters",
   "read_sync_data",
   "syncs_on",
]

LOGIN_SYNC_URL = "https://www.facebook.com/instagram/login_sync/"
FACEBOOK_SYNC_URL = "https://www.facebook.com/instagram/sync/"
INSTAGRAM_SYNC_URL = "https://www.instagram.com/sync/instagram/"

SKIPPED_PATH_MARKERS = ("terms", "challenge", "auth_platform")
"""A page whose path contains any of these mounts no iframe, read from
``PolarisFacebookCookieSyncImpl.react``. The check is a substring test on the whole path, so a
profile whose username contains one is skipped too, exactly as the page skips it."""

FR_ROOT_FIELD = "xdt_api__v1__web__accounts__get_encrypted_credentials"

_ASBD_ID = "359341"
_CONTENT_TYPE = "application/x-www-form-urlencoded"
_IFRAME_ACCEPT = (
   "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,"
   "*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
)


def syncs_on(page_url: str) -> bool:
   """Whether a page at ``page_url`` runs the cookie sync at all."""

   path = urlsplit(page_url).path

   return not any(marker in path for marker in SKIPPED_PATH_MARKERS)


def build_iframe_document_request(user_agent: str = DEFAULT_USER_AGENT) -> Request:
   """The hidden iframe's navigation. Its referer is the bare origin whatever page mounted it,
   which is what every capture recorded, profile pages included."""

   return Request(
      method="GET",
      url=LOGIN_SYNC_URL,
      headers={
         "user-agent": user_agent,
         "accept": _IFRAME_ACCEPT,
         "accept-language": "en-US,en;q=0.9",
         "referer": f"{ORIGIN}/",
         "sec-fetch-site": "cross-site",
         "sec-fetch-mode": "navigate",
         "sec-fetch-dest": "iframe",
         "upgrade-insecure-requests": "1",
      },
      follow_redirects=False,
   )


def read_iframe_parameters(document: Response) -> PageParameters:
   """The iframe document's own request parameters, or :class:`SchemaChanged` without them.

   Without ``lsd`` and ``haste_session`` the iframe's fetch cannot be shaped the way the iframe
   shapes it, and a page whose iframe never becomes ready sends none of the rest.
   """

   parameters = read_page_parameters(document.text)
   missing = [
      name
      for name, value in (("LSD", parameters.lsd), ("haste_session", parameters.haste_session))
      if not value
   ]

   if missing:
      raise SchemaChanged(
         "the cookie sync iframe document no longer carries " + " and ".join(missing),
         path=missing[0],
      )

   return parameters


def build_fr_cookie_request(
   session: Session, page_url: str, user_agent: str = DEFAULT_USER_AGENT
) -> Request:
   """The exchange of the stored ``fr``, which is ``null`` when the session holds none."""

   variables: dict[str, Any] = {"_request_data": {}, "payload": session.fr}

   return build_graphql_request(
      session, GET_FR_COOKIE, variables, referer=page_url, user_agent=user_agent
   )


def read_fr(response: Response) -> str:
   """The ``fr`` the exchange answered with, which may be the empty string."""

   payload = classify(response)
   data = payload.get("data") if isinstance(payload, dict) else None
   root = data.get(FR_ROOT_FIELD) if isinstance(data, dict) else None
   fr = root.get("fr") if isinstance(root, dict) else None

   if not isinstance(fr, str):
      raise SchemaChanged(
         "the fr exchange answered without a string fr", path=f"data.{FR_ROOT_FIELD}.fr"
      )

   return fr


def build_facebook_sync_request(
   parameters: PageParameters, user_agent: str = DEFAULT_USER_AGENT
) -> Request:
   """The iframe's fetch, keyed on what its own document carries.

   ``fb_dtsg_ag`` goes first and bare, with no ``=``, as the iframe sends it, which a params
   mapping cannot express, so the query string is written into the URL.
   """

   spin = parameters.spin
   query = {
      "__user": "0",
      "__a": "1",
      "__req": "1",
      "__hs": parameters.haste_session or "",
      "dpr": "2",
      "__ccg": "EXCELLENT",
      "__rev": spin.revision or "",
      "__hsi": parameters.hsi or "",
      "__comet_req": "15",
      "__spin_r": spin.revision or "",
      "__spin_b": spin.branch or "",
      "__spin_t": spin.timestamp or "",
   }

   return Request(
      method="GET",
      url=f"{FACEBOOK_SYNC_URL}?fb_dtsg_ag&{urlencode(query)}",
      headers={
         "user-agent": user_agent,
         "accept": "*/*",
         "accept-language": "en-US,en;q=0.9",
         "referer": LOGIN_SYNC_URL,
         "sec-fetch-site": "same-origin",
         "sec-fetch-mode": "cors",
         "sec-fetch-dest": "empty",
         "x-asbd-id": _ASBD_ID,
         "x-fb-lsd": parameters.lsd or "",
      },
      follow_redirects=False,
   )


def read_sync_data(response: Response) -> str:
   """The encrypted blob the iframe hands the page, ``payload.data`` of its answer."""

   payload = classify(response)
   inner = payload.get("payload") if isinstance(payload, dict) else None
   data = inner.get("data") if isinstance(inner, dict) else None

   carries_data = isinstance(data, str) and bool(data)

   if not carries_data:
      raise SchemaChanged(
         "the facebook.com sync answered without payload.data", path="payload.data"
      )

   return str(data)


def build_instagram_sync_request(
   session: Session,
   encrypted_data: str,
   page_url: str,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The page's post of the iframe's blob, in the page envelope and with no ``x-csrftoken``,
   no ``x-ig-app-id`` and no ``av``, as captured."""

   fb_dtsg = session.fb_dtsg or ""
   spin = session.spin
   revision = spin.revision if spin is not None else None
   branch = spin.branch if spin is not None else None
   spin_timestamp = spin.timestamp if spin is not None else None

   body = {
      "encrypted_data": encrypted_data,
      "__d": "www",
      "__user": "0",
      "__a": "1",
      "__req": "1",
      "__hs": session.haste_session or "",
      "dpr": "2",
      "__ccg": "EXCELLENT",
      "__rev": revision or "",
      "__hsi": session.hsi or "",
      "__comet_req": "7",
      "fb_dtsg": fb_dtsg,
      "jazoest": jazoest_for(fb_dtsg),
      "lsd": session.lsd or "",
      "__spin_r": revision or "",
      "__spin_b": branch or "",
      "__spin_t": spin_timestamp or "",
   }

   return Request(
      method="POST",
      url=INSTAGRAM_SYNC_URL,
      headers={
         "content-type": _CONTENT_TYPE,
         "sec-fetch-site": "same-origin",
         "sec-fetch-mode": "cors",
         "sec-fetch-dest": "empty",
         "user-agent": user_agent,
         "x-fb-lsd": session.lsd or "",
         "x-asbd-id": _ASBD_ID,
         "origin": ORIGIN,
         "referer": page_url,
         "accept": "*/*",
         "accept-language": "en-US,en;q=0.9",
      },
      content=urlencode(body).encode("utf-8"),
      follow_redirects=False,
   )
