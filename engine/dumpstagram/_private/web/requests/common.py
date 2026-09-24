"""Build the GraphQL request the web client sends, byte shape included.

Ablation on 33 single-removal requests found that exactly three of roughly 38 items sent are
validated: the ``fb_dtsg`` body field, the ``sec-fetch-site`` header, and the ``content-type``
header. Everything else can be dropped without the upstream noticing.

They are sent anyway, and that is a deliberate choice rather than an oversight. A request
carrying only what is validated is a request no browser has ever sent, which makes it
trivially distinguishable from one. The three validated items are named in
:data:`VALIDATED_BODY_FIELDS` and :data:`VALIDATED_HEADERS`, and a gate fails if one stops
being sent.

``jazoest`` is computed rather than scraped: the string ``"2"`` followed by the sum of the
character codes of ``fb_dtsg``.

Nothing above this package knows any of it. ``_core`` passes an intent and typed parameters.

Each query names the path it answers on, because two were observed and posting to the wrong
one returns HTTP 200 with a null root field and no error envelope. See
:class:`~dumpstagram._private.web.documents.common.PersistedQuery`.

Finding: ``skills/reverse-engineer/knowledge/endpoints/direct-thread-message-page.md``.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlencode

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, ORIGIN
from dumpstagram._private.web.documents.common import PersistedQuery
from dumpstagram.errors import AuthenticationFailed, SchemaChanged
from dumpstagram.session import Session

__all__ = [
   "VALIDATED_BODY_FIELDS",
   "VALIDATED_HEADERS",
   "build_graphql_request",
   "jazoest_for",
]

_USER_ID = re.compile(r"[0-9]{1,30}")

VALIDATED_BODY_FIELDS = ("fb_dtsg",)
"""The only body field the upstream was observed to check. Dropping it returns the HTML shell."""

VALIDATED_HEADERS = ("sec-fetch-site", "content-type")
"""The only headers the upstream was observed to check."""

_CONTENT_TYPE = "application/x-www-form-urlencoded"


def jazoest_for(fb_dtsg: str) -> str:
   """``"2"`` followed by the sum of the character codes of ``fb_dtsg``.

   Not a checksum the upstream verifies. It is reproduced because the browser sends it and a
   wrong or absent value is a difference a fingerprint check can read.
   """

   return "2" + str(sum(ord(character) for character in fb_dtsg))


def build_graphql_request(
   session: Session,
   query: PersistedQuery,
   variables: dict[str, Any],
   *,
   referer: str,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """One persisted-query POST, shaped the way the web client shapes it.

   Raises :class:`~dumpstagram.errors.AuthenticationFailed` when the session carries no
   ``fb_dtsg``, because sending an empty one returns the HTML application shell under HTTP
   200 and the caller would be told the schema changed.

   A query on ``/graphql/query`` also carries ``x-bloks-version-id`` and
   ``x-root-field-name``, and raises :class:`~dumpstagram.errors.SchemaChanged` when the session
   has no bloks version id, because the bootstrap page stopped carrying it.
   """

   if not session.fb_dtsg:
      raise AuthenticationFailed(
         "session has no fb_dtsg, so it has not been bootstrapped since it was loaded"
      )

   is_missing_bloks_version = query.sends_path_headers and not session.bloks_version_id

   if is_missing_bloks_version:
      raise SchemaChanged(
         "the bootstrap page carried no WebBloksVersioningID, so the x-bloks-version-id "
         f"header {query.friendly_name} needs cannot be sent",
         path="WebBloksVersioningID",
      )

   spin = session.spin
   revision = spin.revision if spin is not None else None
   branch = spin.branch if spin is not None else None
   spin_timestamp = spin.timestamp if spin is not None else None

   body = {
      "av": session.ds_user_id,
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
      "fb_dtsg": session.fb_dtsg,
      "jazoest": jazoest_for(session.fb_dtsg),
      "lsd": session.lsd or "",
      "__spin_r": revision or "",
      "__spin_b": branch or "",
      "__spin_t": spin_timestamp or "",
      "fb_api_caller_class": "RelayModern",
      "fb_api_req_friendly_name": query.friendly_name,
      "server_timestamps": "true",
      "doc_id": query.doc_id,
      "variables": json.dumps(variables),
   }

   headers = {
      "content-type": _CONTENT_TYPE,
      "sec-fetch-site": "same-origin",
      "sec-fetch-mode": "cors",
      "sec-fetch-dest": "empty",
      "user-agent": user_agent,
      "x-ig-app-id": session.app_id or "",
      "x-csrftoken": session.csrftoken,
      "x-fb-lsd": session.lsd or "",
      "x-fb-friendly-name": query.friendly_name,
      "x-asbd-id": "359341",
      "origin": ORIGIN,
      "referer": referer,
      "accept": "*/*",
      "accept-language": "en-US,en;q=0.9",
   }

   if query.sends_path_headers:
      headers["x-bloks-version-id"] = session.bloks_version_id or ""
      headers["x-root-field-name"] = query.root_field or ""

   return Request(
      method="POST",
      url=query.url,
      headers=headers,
      content=urlencode(body).encode("utf-8"),
      follow_redirects=False,
   )
