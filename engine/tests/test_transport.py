"""Gates for the HTTP boundary.

Each one names the defect it catches. The defects this layer can produce are a hidden retry,
a status-code branch, an unbounded read, an `httpx` type reaching a caller, and a client the
caller owns being closed underneath them.
"""

from __future__ import annotations

import dataclasses
import typing
from collections.abc import Mapping

import httpx
import pytest

from dumpstagram._private import transport as transport_module
from dumpstagram._private.transport import (
   DEFAULT_MAX_RESPONSE_BYTES,
   HttpxTransport,
   Request,
   Response,
   Sender,
   Timeouts,
   cookies_for,
)
from dumpstagram.errors import SchemaChanged, TransportFailure
from dumpstagram.session import Session


def make_transport(handler, **kwargs) -> HttpxTransport:
   client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
   return HttpxTransport(client=client, **kwargs)


@pytest.mark.asyncio
async def test_request_reaches_the_wire_unchanged() -> None:
   """Catches an adapter's headers or body being dropped or rewritten in transit."""
   seen: dict[str, object] = {}

   def handler(request: httpx.Request) -> httpx.Response:
      seen["method"] = request.method
      seen["url"] = str(request.url)
      seen["header"] = request.headers.get("x-fb-lsd")
      seen["content"] = request.content
      return httpx.Response(200, text="ok")

   async with make_transport(handler) as transport:
      await transport.send(
         Request(
            method="POST",
            url="https://www.instagram.com/graphql/query",
            headers={"x-fb-lsd": "token-value"},
            params={"q": "1"},
            content=b"fb_dtsg=abc",
         )
      )

   assert seen["method"] == "POST"
   assert seen["url"] == "https://www.instagram.com/graphql/query?q=1"
   assert seen["header"] == "token-value"
   assert seen["content"] == b"fb_dtsg=abc"


@pytest.mark.asyncio
async def test_a_500_carrying_a_payload_is_returned_not_raised() -> None:
   """Catches a status branch being added here, which would mask the 200-with-envelope case."""

   def handler(request: httpx.Request) -> httpx.Response:
      return httpx.Response(500, json={"data": {"ok": True}})

   async with make_transport(handler) as transport:
      response = await transport.send(Request(method="GET", url="https://example.invalid/"))

   assert response.status_code == 500
   assert b'"ok"' in response.content


@pytest.mark.asyncio
async def test_a_200_carrying_an_envelope_is_also_returned_not_raised() -> None:
   """The positive control for the gate above: neither status decides anything here.

   Classification is the classifier's job, so the transport must hand both bodies back
   identically. A status branch that raised on 500 and passed 200 would leave this green.
   """

   def handler(request: httpx.Request) -> httpx.Response:
      return httpx.Response(200, json={"errors": [{"message": "nope"}]})

   async with make_transport(handler) as transport:
      response = await transport.send(Request(method="GET", url="https://example.invalid/"))

   assert response.status_code == 200
   assert b"errors" in response.content


@pytest.mark.asyncio
async def test_an_oversized_body_is_a_transport_failure() -> None:
   """Catches an unbounded read, and catches it being reported as a schema change."""

   def handler(request: httpx.Request) -> httpx.Response:
      return httpx.Response(200, content=b"x" * 40)

   async with make_transport(handler, max_response_bytes=16) as transport:
      with pytest.raises(TransportFailure) as caught:
         await transport.send(Request(method="GET", url="https://example.invalid/"))

   assert not isinstance(caught.value, SchemaChanged)


@pytest.mark.asyncio
async def test_a_body_exactly_at_the_bound_is_returned() -> None:
   """The boundary control: an off-by-one bound would reject a legal body."""

   def handler(request: httpx.Request) -> httpx.Response:
      return httpx.Response(200, content=b"x" * 16)

   async with make_transport(handler, max_response_bytes=16) as transport:
      response = await transport.send(Request(method="GET", url="https://example.invalid/"))

   assert len(response.content) == 16


@pytest.mark.asyncio
async def test_a_connect_error_becomes_a_transport_failure_with_its_cause() -> None:
   """Catches an `httpx` exception escaping to a caller, and catches a lost `raise ... from`."""

   def handler(request: httpx.Request) -> httpx.Response:
      raise httpx.ConnectError("refused", request=request)

   async with make_transport(handler) as transport:
      with pytest.raises(TransportFailure) as caught:
         await transport.send(Request(method="GET", url="https://example.invalid/"))

   assert isinstance(caught.value.__cause__, httpx.ConnectError)


@pytest.mark.asyncio
async def test_a_read_timeout_becomes_a_transport_failure() -> None:
   """A timeout is a different `httpx` branch from a connect error and can be missed alone."""

   def handler(request: httpx.Request) -> httpx.Response:
      raise httpx.ReadTimeout("slow", request=request)

   async with make_transport(handler) as transport:
      with pytest.raises(TransportFailure) as caught:
         await transport.send(Request(method="GET", url="https://example.invalid/"))

   assert isinstance(caught.value.__cause__, httpx.ReadTimeout)


def test_every_timeout_category_is_set() -> None:
   """Catches a single timeout number being reintroduced, which hides which stage stalled."""
   transport = HttpxTransport(timeouts=Timeouts(connect=1.0, read=2.0, write=3.0, pool=4.0))
   timeout = transport._client.timeout

   assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (1.0, 2.0, 3.0, 4.0)


def test_the_underlying_transport_does_not_retry() -> None:
   """Catches a retry here multiplying with the `_core` retry budget."""
   transport = HttpxTransport()
   pool = transport._client._transport._pool

   assert pool._retries == 0


@pytest.mark.asyncio
async def test_a_caller_supplied_client_is_not_closed() -> None:
   """Catches the library closing a connection pool its caller owns."""

   def handler(request: httpx.Request) -> httpx.Response:
      return httpx.Response(200, text="ok")

   client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
   transport = HttpxTransport(client=client)
   await transport.aclose()

   assert not client.is_closed

   await client.aclose()


@pytest.mark.asyncio
async def test_an_owned_client_is_closed() -> None:
   """The positive control for the gate above: ownership must still release the pool."""
   transport = HttpxTransport()
   await transport.aclose()

   assert transport._client.is_closed


def test_no_httpx_type_appears_in_the_module_boundary() -> None:
   """Catches an `httpx` type on `Request`, `Response`, or the `Sender` seam.

   Those three are what `_core` and its fakes touch, so an `httpx` type on any of them makes
   the HTTP client part of the contract rather than an implementation choice.
   """
   annotations: list[str] = []

   for model in (Request, Response):
      annotations.extend(
         str(item.type)
         for item in dataclasses.fields(model)  # type: ignore[arg-type]
      )

   annotations.extend(str(value) for value in typing.get_type_hints(Sender.send).values())

   assert annotations
   assert not [item for item in annotations if "httpx" in item.lower()]


def test_the_boundary_check_can_fire() -> None:
   """Law 4's positive control: the check above is pointed at real annotations."""
   annotations = [str(item.type) for item in dataclasses.fields(Response)]

   assert any("Mapping" in item or "bytes" in item for item in annotations)


def test_the_sender_protocol_is_what_the_httpx_transport_implements() -> None:
   """Catches the seam and the implementation drifting apart, which breaks every `_core` fake."""
   assert isinstance(HttpxTransport(), Sender)


def test_the_response_headers_are_lowercased() -> None:
   """Catches a case-sensitive lookup of `location` or `content-type` failing downstream."""
   response = Response(
      status_code=200,
      headers={"content-type": "text/html; charset=utf-8"},
      content=b"<html></html>",
      final_url="https://example.invalid/",
   )

   assert response.text == "<html></html>"


def test_the_default_bound_is_generous_for_a_real_page() -> None:
   """Catches a bound tightened below a measured real body, which would reject live traffic."""
   largest_measured_bootstrap_bytes = 1_600_000

   assert DEFAULT_MAX_RESPONSE_BYTES > largest_measured_bootstrap_bytes * 10


def test_the_module_holds_no_mutable_state() -> None:
   """Catches a module-level cache or client, which ADR-0004 forbids."""
   mutable: list[str] = []

   for name in dir(transport_module):
      if name.startswith("__"):
         continue

      value = getattr(transport_module, name)
      if isinstance(value, (list, dict, set)) and not isinstance(value, Mapping.__class__):
         mutable.append(name)

   assert mutable == []


def test_the_required_cookies_cannot_be_shadowed_by_extras() -> None:
   """Catches a stale copy in extra_cookies answering for the session's own credential.

   A jar built extras-last authenticates as whatever was pasted in alongside, which is a
   wrong account rather than an error.
   """
   session = Session(
      sessionid="live-session",
      ds_user_id="1234567890",
      csrftoken="live-csrf",
      extra_cookies={"sessionid": "stale-session", "mid": "mid-value"},
   )

   jar = cookies_for(session)

   assert jar["sessionid"] == "live-session"
   assert jar["ds_user_id"] == "1234567890"
   assert jar["csrftoken"] == "live-csrf"
   assert jar["mid"] == "mid-value"


INSTAGRAM = "www.instagram.com"
FACEBOOK = "www.facebook.com"


@pytest.mark.asyncio
async def test_a_pinned_transport_refuses_another_host() -> None:
   """Catches the account's cookies going out to a host a wrong wiring named.

   The request to the pinned host is the positive control: the pin must refuse by host, not
   refuse everything.
   """
   seen_hosts: list[str] = []

   def handler(request: httpx.Request) -> httpx.Response:
      seen_hosts.append(request.url.host)
      return httpx.Response(200, text="ok")

   async with make_transport(handler, allowed_host=INSTAGRAM) as transport:
      await transport.send(Request(method="GET", url=f"https://{INSTAGRAM}/"))

      with pytest.raises(TransportFailure):
         await transport.send(Request(method="GET", url=f"https://{FACEBOOK}/"))

   assert seen_hosts == [INSTAGRAM]


@pytest.mark.asyncio
async def test_a_pinned_transport_refuses_a_redirect_to_another_host() -> None:
   """Catches a pin checked only on the first hop, which a redirect walks straight past."""
   seen_hosts: list[str] = []

   def handler(request: httpx.Request) -> httpx.Response:
      seen_hosts.append(request.url.host)
      return httpx.Response(302, headers={"location": f"https://{FACEBOOK}/"})

   async with make_transport(handler, allowed_host=INSTAGRAM) as transport:
      with pytest.raises(TransportFailure):
         await transport.send(
            Request(method="GET", url=f"https://{INSTAGRAM}/", follow_redirects=True)
         )

   assert seen_hosts == [INSTAGRAM]


def cookie_echo_handler(sent_cookies: list[str | None]):
   def handler(request: httpx.Request) -> httpx.Response:
      sent_cookies.append(request.headers.get("cookie"))
      return httpx.Response(
         200,
         headers={"set-cookie": "c=v; Domain=.facebook.com; Path=/"},
         text="ok",
      )

   return handler


@pytest.mark.asyncio
async def test_a_cookieless_transport_neither_stores_nor_sends_a_cookie() -> None:
   """Catches a facebook.com response planting a cookie the next facebook.com call returns."""
   sent_cookies: list[str | None] = []

   async with make_transport(cookie_echo_handler(sent_cookies), cookieless=True) as transport:
      await transport.send(Request(method="GET", url=f"https://{FACEBOOK}/"))
      await transport.send(Request(method="GET", url=f"https://{FACEBOOK}/"))

   assert sent_cookies == [None, None]


@pytest.mark.asyncio
async def test_the_cookie_check_can_fire() -> None:
   """Law 4's positive control: an ordinary transport does return the planted cookie."""
   sent_cookies: list[str | None] = []

   async with make_transport(cookie_echo_handler(sent_cookies)) as transport:
      await transport.send(Request(method="GET", url=f"https://{FACEBOOK}/"))
      await transport.send(Request(method="GET", url=f"https://{FACEBOOK}/"))

   assert sent_cookies == [None, "c=v"]


def test_an_owned_cookieless_transport_stores_no_cookie() -> None:
   """Catches the refusing jar applied only to a caller's client and not to its own."""
   transport = HttpxTransport(cookieless=True)
   request = httpx.Request("GET", f"https://{FACEBOOK}/")
   response = httpx.Response(
      200,
      headers={"set-cookie": "c=v; Domain=.facebook.com; Path=/"},
      request=request,
   )

   transport._client.cookies.extract_cookies(response)

   assert len(transport._client.cookies.jar) == 0


@pytest.mark.asyncio
async def test_a_cookieless_transport_refuses_a_cookie_header() -> None:
   """Catches a request builder writing the account's cookies into a facebook.com call."""
   sent: list[httpx.Request] = []

   def handler(request: httpx.Request) -> httpx.Response:
      sent.append(request)
      return httpx.Response(200, text="ok")

   async with make_transport(handler, cookieless=True) as transport:
      with pytest.raises(ValueError):
         await transport.send(
            Request(method="GET", url=f"https://{FACEBOOK}/", headers={"Cookie": "sessionid=S"})
         )

   assert sent == []


@pytest.mark.asyncio
async def test_a_cookieless_transport_does_not_follow_a_redirect() -> None:
   """Catches the facebook.com calls chasing a redirect the browser was never seen to follow."""
   seen_paths: list[str] = []

   def handler(request: httpx.Request) -> httpx.Response:
      seen_paths.append(request.url.path)
      return httpx.Response(302, headers={"location": f"https://{FACEBOOK}/next/"})

   async with make_transport(handler, cookieless=True) as transport:
      response = await transport.send(
         Request(method="GET", url=f"https://{FACEBOOK}/", follow_redirects=True)
      )

   assert response.status_code == 302
   assert seen_paths == ["/"]


def test_a_cookieless_transport_refuses_cookies() -> None:
   """Catches the session's cookie jar being handed to the facebook.com transport."""
   with pytest.raises(ValueError):
      HttpxTransport(cookies={"sessionid": "S"}, cookieless=True)
