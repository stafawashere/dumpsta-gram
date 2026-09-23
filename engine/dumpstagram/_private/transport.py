"""The one place this library speaks HTTP, and the one place ``httpx`` exists.

Three rules hold here and are gated.

The transport does not retry. `httpx` retries connection failures on its own if asked, and
`_core` owns a retry budget, so leaving both on multiplies into attempts nobody budgeted.
The underlying transport is constructed with ``retries=0``.

The transport does not branch on a status code. Every observed failure on this upstream
arrives as HTTP 200 carrying an error envelope, so a status branch here would report success
for a body that says otherwise. A status code is carried on :class:`Response` for the
classifier to look at if it ever needs to, and nothing in this module reads it.

The transport bounds the body before anything parses it. An oversized body is a
:class:`~dumpstagram.errors.TransportFailure`, because the read is what failed. It is not a
:class:`~dumpstagram.errors.SchemaChanged`, which would claim the library understood the
response well enough to know it was malformed.

Every ``httpx`` exception is translated with ``raise ... from``, so the original is still
reachable from ``__cause__`` while the HTTP client stays an implementation choice.

A transport can be pinned to one host, and then it refuses every other host, redirect hops
included. The reason is the cookie jar: a jar built from a plain mapping has no domain, so
``httpx`` sends its ``sessionid`` to whatever host a request names. A pinned transport turns a
wrong wiring into an error instead of an account token handed to another site.

A cookieless transport keeps no jar in practice: it starts empty, refuses to store what a
response sets, refuses a request that names a ``cookie`` header itself, and never follows a
redirect. It exists for the
facebook.com calls a page load makes, which a browser sends with no cookies.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from http.cookiejar import CookieJar, DefaultCookiePolicy
from types import TracebackType
from typing import Protocol, runtime_checkable
from uuid import uuid4

import httpx

from dumpstagram.errors import TransportFailure
from dumpstagram.session import ProxyConfig, Session

__all__ = [
   "DEFAULT_MAX_RESPONSE_BYTES",
   "DEFAULT_TIMEOUTS",
   "HttpxTransport",
   "Request",
   "Response",
   "Sender",
   "Timeouts",
   "WriteRequest",
   "cookies_for",
]


@dataclass(frozen=True)
class Timeouts:
   """Per-category timeouts, in seconds.

   Named per category rather than given as one number, because a single timeout hides which
   stage stalled and makes a pool starvation look like a slow server.
   """

   connect: float = 10.0
   read: float = 30.0
   write: float = 30.0
   pool: float = 10.0


DEFAULT_TIMEOUTS = Timeouts()

DEFAULT_MAX_RESPONSE_BYTES = 25 * 1024 * 1024
"""Generous for a real inbox page, firm enough that a stuck stream cannot exhaust memory.

The largest body measured locally was the bootstrap HTML at roughly 1.6 MB, so this leaves
more than an order of magnitude of headroom.
"""


@dataclass(frozen=True)
class Request:
   """One outbound request, described without naming the HTTP client.

   ``content`` is the encoded body. Form encoding belongs to the adapter in
   ``_private/web/requests.py``, because the body shape is surface knowledge and this module
   is surface agnostic.
   """

   method: str
   url: str
   headers: Mapping[str, str] = field(default_factory=dict)
   params: Mapping[str, str] = field(default_factory=dict)
   content: bytes | None = None
   follow_redirects: bool = True


@dataclass(frozen=True)
class WriteRequest:
   """A request that changes something on the account, and may leave the machine only once.

   It is not a :class:`Request`, so nothing that sends reads can be handed one by mistake.
   ``token`` is drawn fresh for every object, and the paced sender records it on departure and
   refuses it the second time. A capability that builds a new object for the same write gets a
   new token, which is why a write is also kept out of every retry helper by the modules it may
   import.

   ``operation`` names the write for the error raised when its outcome is unknown, and carries
   no identifier of another account and no text the caller supplied.
   """

   request: Request
   operation: str
   token: str = field(default_factory=lambda: uuid4().hex)


@dataclass(frozen=True)
class Response:
   """One inbound response, already read and already bounded.

   ``final_url`` is the URL after any redirects, which is where checkpoint detection looks
   before it is allowed to look at the body.
   """

   status_code: int
   headers: Mapping[str, str]
   content: bytes
   final_url: str
   history_urls: tuple[str, ...] = ()

   @property
   def text(self) -> str:
      return _decode(self.content, self.headers.get("content-type", ""))


def cookies_for(session: Session) -> dict[str, str]:
   """The cookie jar one account's requests carry.

   The three required cookies are written last, so an ``extra_cookies`` mapping that happens
   to carry a stale ``sessionid`` cannot shadow the one the session was constructed with.
   """

   jar = dict(session.extra_cookies)

   jar["sessionid"] = session.sessionid
   jar["ds_user_id"] = session.ds_user_id
   jar["csrftoken"] = session.csrftoken

   return jar


@runtime_checkable
class Sender(Protocol):
   """The seam ``_core`` is tested against.

   A fake sender is a class with this one method and no network. Neither side of it names an
   HTTP client.
   """

   async def send(self, request: Request) -> Response: ...


def _refusing_jar() -> CookieJar:
   """A jar whose policy allows no domain, so it stores nothing a response sets.

   Only storing is refused. ``httpx`` copies the jar into a fresh one without this policy when
   it builds each request, so the jar being empty is what keeps a request cookieless. It is
   handed over as a bare ``CookieJar`` for the same reason: ``httpx.Cookies`` wrapping it
   would be copied and the policy lost at construction.
   """

   return CookieJar(policy=DefaultCookiePolicy(allowed_domains=[]))


def _decode(content: bytes, content_type: str) -> str:
   charset = "utf-8"
   for part in content_type.split(";")[1:]:
      name, _, value = part.strip().partition("=")
      if name.strip().lower() == "charset":
         charset = value.strip().strip('"') or "utf-8"

   try:
      return content.decode(charset, errors="replace")
   except LookupError:
      return content.decode("utf-8", errors="replace")


class HttpxTransport:
   """A :class:`Sender` backed by ``httpx``.

   Owns the client it creates and closes it in :meth:`aclose`. A client passed in belongs to
   the caller and is left open, per the ownership table in
   ``engine/docs/engineering/04-errors-resources-logging.md``.

   ``allowed_host`` pins the transport to one host. ``cookieless`` builds the facebook.com
   kind described in the module docstring, and it cannot be given cookies. Both apply to a
   caller's client as well, because the pin is installed as a request hook on whichever
   client sends.
   """

   def __init__(
      self,
      *,
      cookies: Mapping[str, str] | None = None,
      proxy: ProxyConfig | None = None,
      timeouts: Timeouts = DEFAULT_TIMEOUTS,
      max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
      client: httpx.AsyncClient | None = None,
      allowed_host: str | None = None,
      cookieless: bool = False,
   ) -> None:
      if cookieless and cookies:
         raise ValueError("a cookieless transport cannot be given cookies")

      self._max_response_bytes = max_response_bytes
      self._timeouts = timeouts
      self._owns_client = client is None
      self._allowed_host = allowed_host
      self._cookieless = cookieless

      if client is not None:
         self._client = client
         self._pin(client)

         if cookieless:
            client.cookies = _refusing_jar()

         return

      verify = proxy.verify_tls if proxy is not None else True
      jar: CookieJar | dict[str, str] = _refusing_jar() if cookieless else dict(cookies or {})
      self._client = httpx.AsyncClient(
         cookies=jar,
         timeout=httpx.Timeout(
            connect=timeouts.connect,
            read=timeouts.read,
            write=timeouts.write,
            pool=timeouts.pool,
         ),
         transport=httpx.AsyncHTTPTransport(
            retries=0,
            verify=verify,
            proxy=proxy.url if proxy is not None else None,
         ),
         follow_redirects=False,
      )
      self._pin(self._client)

   @property
   def allowed_host(self) -> str | None:
      """The one host this transport sends to, or ``None`` when it is not pinned."""

      return self._allowed_host

   @property
   def cookieless(self) -> bool:
      """Whether this transport refuses to store or send any cookie."""

      return self._cookieless

   def _pin(self, client: httpx.AsyncClient) -> None:
      if self._allowed_host is None:
         return

      hooks = client.event_hooks
      hooks["request"] = [*hooks.get("request", []), self._refuse_other_hosts]
      client.event_hooks = hooks

   async def _refuse_other_hosts(self, request: httpx.Request) -> None:
      host = request.url.host
      is_other_host = host != self._allowed_host

      if is_other_host:
         raise TransportFailure(
            f"refused a {request.method} request to {host}, "
            f"this transport sends only to {self._allowed_host}"
         )

   async def send(self, request: Request) -> Response:
      names_a_cookie = any(name.lower() == "cookie" for name in request.headers)
      is_cookie_on_cookieless = self._cookieless and names_a_cookie

      if is_cookie_on_cookieless:
         raise ValueError("a cookieless transport refuses a request carrying a cookie header")

      try:
         built = self._client.build_request(
            request.method,
            request.url,
            headers=dict(request.headers),
            params=dict(request.params) or None,
            content=request.content,
         )
         response = await self._client.send(
            built,
            stream=True,
            follow_redirects=request.follow_redirects and not self._cookieless,
         )
      except httpx.HTTPError as exc:
         raise TransportFailure(f"{request.method} request failed at the transport") from exc

      try:
         content = await self._read_bounded(response, request)
      finally:
         await response.aclose()

      return Response(
         status_code=response.status_code,
         headers={key.lower(): value for key, value in response.headers.items()},
         content=content,
         final_url=str(response.url),
         history_urls=tuple(str(previous.url) for previous in response.history),
      )

   async def _read_bounded(self, response: httpx.Response, request: Request) -> bytes:
      chunks: list[bytes] = []
      total = 0

      try:
         stream = response.aiter_bytes()
         async for chunk in stream:
            total += len(chunk)
            if total > self._max_response_bytes:
               raise TransportFailure(
                  f"response body exceeded {self._max_response_bytes} bytes "
                  f"for {request.method} request"
               )

            chunks.append(chunk)
      except httpx.HTTPError as exc:
         raise TransportFailure("response body could not be read") from exc

      return b"".join(chunks)

   async def aclose(self) -> None:
      if self._owns_client:
         await self._client.aclose()

   async def __aenter__(self) -> HttpxTransport:
      return self

   async def __aexit__(
      self,
      exc_type: type[BaseException] | None,
      exc: BaseException | None,
      traceback: TracebackType | None,
   ) -> None:
      await self.aclose()
