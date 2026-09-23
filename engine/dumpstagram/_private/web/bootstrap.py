"""Harvest the per-page tokens the web surface requires, out of one authenticated page load.

``fb_dtsg`` and ``lsd`` are not cookies. They live in the HTML of any authenticated page and
come out by regular expression against a minified bundle. This is the second most fragile
thing in the library, behind ``doc_id`` rotation: a module rename, a quoting change, or a
Relay upgrade breaks it with no notice.

So the failure is loud. A missing ``fb_dtsg`` raises
:class:`~dumpstagram.errors.AuthenticationFailed` rather than returning a token of ``None``
for the request builder to send as an empty string, which the upstream answers with the HTML
application shell under HTTP 200.

The viewer id is never taken from the page. Every ``"USER_ID"`` match in the bundle was the
logged-out placeholder ``"0"`` on both days it was measured, and a client that trusts the
first match inverts the outgoing flag on every record it exports without erroring once. It
comes from the ``ds_user_id`` cookie, which is the only place it was ever correct.

The account's Facebook-side id is taken from the page, because no cookie carries it. It is the
``actorID`` of the page's ``RelayAPIConfigDefaults`` config, 17 digits and a different number
from ``ds_user_id``, and a note create sends it as ``actor_id``. It is anchored on that config's
own name, which appears once per page, and it is optional, so a page without it still
bootstraps and only the write that needs it refuses.

Finding: ``skills/reverse-engineer/knowledge/endpoints/bootstrap-web-tokens.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from dumpstagram._private.transport import Request, Response, Sender
from dumpstagram._private.web.classify import classify_checkpoint_only
from dumpstagram.errors import AuthenticationFailed
from dumpstagram.session import Session, SpinParameters

__all__ = [
   "BOOTSTRAP_URL",
   "DEFAULT_APP_ID",
   "DEFAULT_USER_AGENT",
   "FACEBOOK_HOST",
   "INSTAGRAM_HOST",
   "BootstrapTokens",
   "PageParameters",
   "apply_tokens",
   "bootstrap",
   "build_bootstrap_request",
   "build_document_request",
   "read_page_parameters",
   "read_spin",
   "read_tokens",
   "tokens_from",
]

ORIGIN = "https://www.instagram.com"  # provenance: ignore, an origin, not an endpoint

INSTAGRAM_HOST = "www.instagram.com"
"""The only host the transport carrying the account's cookies may send to."""

FACEBOOK_HOST = "www.facebook.com"
"""The host of the page-load cookie sync, reached only through a cookieless transport.

Backed by the findings ``facebook-cookie-sync-iframe-document`` and
``facebook-cookie-sync-fetch``.
"""

BOOTSTRAP_URL = "https://www.instagram.com/direct/inbox/"
"""The page the tokens are read from.

Any authenticated page carries them. This one is used because it is the page the measured
runs used, and because the surface the engine targets first is the direct inbox.
"""

DEFAULT_USER_AGENT = (
   "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
   "Chrome/140.0.0.0 Safari/537.36"
)
"""Sent when the caller supplies none.

The measured runs sent the caller's own browser string. A default belongs here rather than
nowhere, because a request with no user agent at all is the most obvious fingerprint available.
"""

DEFAULT_APP_ID = "936619743392459"  # provenance: ignore, the x-ig-app-id value, not a doc_id
"""Observed in the bundle on both measured days, and sent when the scrape does not find it.

Unlike ``fb_dtsg`` this is not per session and not per page, so a fallback here is a fallback
to a constant that was correct twice rather than a guess.
"""

_FB_DTSG = re.compile(r'"DTSGInitialData",\[\],\{"token":"(.*?)"')
_LSD = re.compile(r'"LSD",\[\],\{"token":"(.*?)"')
_SPIN_REVISION = re.compile(r'"__spin_r":(\d+)')
_SPIN_BRANCH = re.compile(r'"__spin_b":"(.*?)"')
_SPIN_TIMESTAMP = re.compile(r'"__spin_t":(\d+)')
_SERVER_REVISION = re.compile(r'"server_revision":(\d+)')
_HSI = re.compile(r'"hsi":"(.*?)"')
_HASTE_SESSION = re.compile(r'"haste_session":"(.*?)"')
_APP_ID = re.compile(r'"X-IG-App-ID":"(\d+)"')
_BLOKS_VERSION_ID = re.compile(r'"WebBloksVersioningID",\[\],\{"versioningID":"([0-9a-f]+)"')
_ACTOR_ID = re.compile(r'"RelayAPIConfigDefaults",\[\],\{"accessToken":"[^"]*","actorID":"(\d+)"')


@dataclass(frozen=True)
class BootstrapTokens:
   """Everything one page load yields.

   ``fb_dtsg`` is the only member the upstream validates. The rest are sent to match the
   shape a browser sends.
   """

   fb_dtsg: str
   lsd: str
   app_id: str
   spin: SpinParameters
   hsi: str | None
   haste_session: str | None
   bloks_version_id: str | None = None
   """The ``x-bloks-version-id`` a page sends on every ``/graphql/query`` request.

   Optional here because only those requests need it, so a page without it must not stop a
   thread read. The request builder refuses a query that needs it when it is missing.
   """

   actor_id: str | None = None
   """The account's Facebook-side id, which a note create sends as ``actor_id``.

   Never ``ds_user_id``. On every captured inbox and home document it equalled the page's
   ``NON_FACEBOOK_USER_ID`` and differed from the cookie.
   """


# G9N7E-K9NZE-GTWKC-XQ9TR


@dataclass(frozen=True)
class PageParameters:
   """The request parameters a page carries that do not depend on being logged in."""

   lsd: str | None
   spin: SpinParameters
   hsi: str | None
   haste_session: str | None


def _first_match(pattern: re.Pattern[str], html: str) -> str | None:
   """The first capture of ``pattern``, or ``None``.

   Every pattern in this module was checked for what its first match actually is, which is
   the generalised form of the inherited ``"USER_ID"`` bug: the first occurrence was the
   logged-out placeholder and match zero was silently wrong. The token patterns here are
   anchored on the Relay bundle's own key names, each of which appears once.
   """

   found = pattern.search(html)

   return found.group(1) if found else None


def build_bootstrap_request(user_agent: str) -> Request:
   """The page load the tokens are read from."""

   return build_document_request(BOOTSTRAP_URL, user_agent)


def build_document_request(url: str, user_agent: str) -> Request:
   """A page load, shaped as a navigation rather than as an API call.

   ``sec-fetch-site: none`` and the document fetch metadata are what a browser sends when the
   user types the address, which is what this request is pretending to be.
   """

   return Request(
      method="GET",
      url=url,
      headers={
         "user-agent": user_agent,
         "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
         "accept-language": "en-US,en;q=0.9",
         "sec-fetch-site": "none",
         "sec-fetch-mode": "navigate",
         "sec-fetch-dest": "document",
      },
      follow_redirects=True,
   )


def read_tokens(html: str) -> BootstrapTokens:
   """Pull the tokens out of one page of HTML, or say why the page was not usable.

   Raises :class:`~dumpstagram.errors.AuthenticationFailed` when ``fb_dtsg`` or ``lsd`` is
   absent. Both are present on every authenticated page, so their absence means the response
   was the logged-out page rather than that the page changed shape.
   """

   fb_dtsg = _first_match(_FB_DTSG, html)
   if not fb_dtsg:
      raise AuthenticationFailed(
         "no fb_dtsg in the bootstrap page, so the session is not authenticated or the "
         "token extraction has broken against a new bundle"
      )

   lsd = _first_match(_LSD, html)
   if not lsd:
      raise AuthenticationFailed(
         "no lsd in the bootstrap page, so the session is not authenticated or the "
         "token extraction has broken against a new bundle"
      )

   return BootstrapTokens(
      fb_dtsg=fb_dtsg,
      lsd=lsd,
      app_id=_first_match(_APP_ID, html) or DEFAULT_APP_ID,
      spin=read_spin(html),
      hsi=_first_match(_HSI, html),
      haste_session=_first_match(_HASTE_SESSION, html),
      bloks_version_id=_first_match(_BLOKS_VERSION_ID, html),
      actor_id=_first_match(_ACTOR_ID, html),
   )


def read_spin(html: str) -> SpinParameters:
   """The ``__spin_*`` family of one page, with ``server_revision`` preferred as the revision."""

   spin_revision = _first_match(_SPIN_REVISION, html)
   server_revision = _first_match(_SERVER_REVISION, html) or spin_revision

   return SpinParameters(
      revision=server_revision,
      branch=_first_match(_SPIN_BRANCH, html),
      timestamp=_first_match(_SPIN_TIMESTAMP, html),
   )


def read_page_parameters(html: str) -> PageParameters:
   """What any page built on the same bundle carries for its own requests, logged in or not.

   The facebook.com cookie sync iframe is such a page. It carries no ``fb_dtsg`` because it is
   logged out, so :func:`read_tokens` would call it a dead session.
   """

   return PageParameters(
      lsd=_first_match(_LSD, html),
      spin=read_spin(html),
      hsi=_first_match(_HSI, html),
      haste_session=_first_match(_HASTE_SESSION, html),
   )


async def bootstrap(
   sender: Sender,
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> BootstrapTokens:
   """Load one authenticated page and write its tokens onto ``session``.

   The session is mutated rather than replaced, because it is the caller's object and the
   rest of the library reads the tokens off it.
   """

   response = await sender.send(build_bootstrap_request(user_agent))

   tokens = tokens_from(response)
   apply_tokens(session, tokens)

   return tokens


def apply_tokens(session: Session, tokens: BootstrapTokens) -> None:
   """Write one page load's tokens onto ``session``, whichever page they came from."""

   session.fb_dtsg = tokens.fb_dtsg
   session.lsd = tokens.lsd
   session.app_id = tokens.app_id
   session.spin = tokens.spin
   session.hsi = tokens.hsi
   session.haste_session = tokens.haste_session
   session.bloks_version_id = tokens.bloks_version_id
   session.actor_id = tokens.actor_id or session.actor_id
   session.bootstrapped_at = datetime.now(UTC)


def tokens_from(response: Response) -> BootstrapTokens:
   """Check for a challenge before reading the page, then read it.

   A checkpoint redirect returns HTML that carries no ``fb_dtsg``, so without this the caller
   is told its credentials are bad when the account is actually sitting in a challenge, and
   the two need different responses from the user.
   """

   classify_checkpoint_only(response)

   return read_tokens(response.text)
