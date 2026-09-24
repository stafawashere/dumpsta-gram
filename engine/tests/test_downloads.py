"""Gates on ``client.media.download``, the one fetch this library makes outside Instagram's API.

A download can go wrong in ways a read cannot, because it writes to the caller's disk and it
talks to a host the account's cookies must never reach. Gated here: a partial file is never at
the destination, an existing file is never replaced unless the caller says so, a body shorter or
longer than the CDN declared is refused, no cookie goes to the CDN, the CDN transport refuses
every host outside the CDN's family, and a download takes no turn from the account's pacer.
Both surfaces are driven for the client-level gates.

Nothing touches the network. The download core is driven through a scripted streamer, and the
client through its own CDN transport with the socket replaced by ``httpx.MockTransport``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest

from dumpstagram._core.downloads import download_rendition
from dumpstagram._private.transport import HttpxTransport, Request, StreamedResponse
from dumpstagram.aio import AsyncClient
from dumpstagram.client import SyncClient
from dumpstagram.errors import NotFound, TransportFailure
from dumpstagram.models import MediaImage, VideoRendition
from dumpstagram.session import Session

SESSION_ID = "71234567%3AabcdefGHIJKL%3A17"
CDN_URL = "https://scontent-fixture-1.cdninstagram.com/v/fixture-1.mp4?signed=fixture"
BODY = b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 4
USER_AGENT = "fixture agent"


def a_session() -> Session:
   return Session(sessionid=SESSION_ID, ds_user_id="71234567", csrftoken="t")


class ScriptedStreamer:
   """Answers every stream with one scripted status, header set and body."""

   def __init__(
      self,
      *,
      status: int = 200,
      headers: dict[str, str] | None = None,
      chunks: Iterable[bytes] = (BODY[:100], BODY[100:]),
      before_each_chunk: Callable[[int], None] | None = None,
      failure_after: int | None = None,
   ) -> None:
      self.status = status
      self.headers = {"content-length": str(len(BODY))} if headers is None else headers
      self.chunks = list(chunks)
      self.before_each_chunk = before_each_chunk
      self.failure_after = failure_after
      self.requests: list[Request] = []

   @asynccontextmanager
   async def stream(self, request: Request) -> AsyncIterator[StreamedResponse]:
      self.requests.append(request)

      async def body() -> AsyncIterator[bytes]:
         for index, chunk in enumerate(self.chunks):
            if self.failure_after == index:
               raise TransportFailure("scripted stop")

            if self.before_each_chunk is not None:
               self.before_each_chunk(index)

            yield chunk

      yield StreamedResponse(
         status_code=self.status, headers=self.headers, final_url=request.url, body=body()
      )


async def download(streamer: ScriptedStreamer, path: Path, *, overwrite: bool = False) -> Path:
   return await download_rendition(
      streamer, CDN_URL, path, overwrite=overwrite, user_agent=USER_AGENT
   )


@pytest.mark.asyncio
async def test_a_download_writes_the_whole_body_and_leaves_nothing_beside_it(
   tmp_path: Path,
) -> None:
   """Catches a body written short, twice, or with its temporary file left behind."""

   destination = tmp_path / "reel.mp4"
   streamer = ScriptedStreamer()

   returned = await download(streamer, destination)

   assert returned == destination
   assert destination.read_bytes() == BODY
   assert sorted(path.name for path in tmp_path.iterdir()) == ["reel.mp4"]
   assert len(streamer.requests) == 1


@pytest.mark.asyncio
async def test_the_destination_does_not_exist_until_the_body_is_complete(tmp_path: Path) -> None:
   """Catches a download written straight onto the destination, which an interruption would
   leave there half written."""

   destination = tmp_path / "reel.mp4"
   seen_while_streaming: list[tuple[bool, list[str]]] = []

   def look(index: int) -> None:
      names = sorted(path.name for path in tmp_path.iterdir())
      seen_while_streaming.append((destination.exists(), names))

   await download(ScriptedStreamer(before_each_chunk=look), destination)

   assert [exists for exists, _ in seen_while_streaming] == [False, False]
   assert all(len(names) == 1 for _, names in seen_while_streaming)
   assert all(names[0].endswith(".part") for _, names in seen_while_streaming)
   assert destination.read_bytes() == BODY


@pytest.mark.asyncio
async def test_an_existing_file_is_refused_before_anything_is_sent(tmp_path: Path) -> None:
   """Catches a download that replaces the caller's file without being told to."""

   destination = tmp_path / "reel.mp4"
   destination.write_bytes(b"the caller's own file")
   streamer = ScriptedStreamer()

   with pytest.raises(FileExistsError):
      await download(streamer, destination)

   assert streamer.requests == []
   assert destination.read_bytes() == b"the caller's own file"


@pytest.mark.asyncio
async def test_overwrite_replaces_an_existing_file(tmp_path: Path) -> None:
   """The positive control for the refusal: told to, a download does replace the file."""

   destination = tmp_path / "reel.mp4"
   destination.write_bytes(b"the caller's own file")

   await download(ScriptedStreamer(), destination, overwrite=True)

   assert destination.read_bytes() == BODY
   assert sorted(path.name for path in tmp_path.iterdir()) == ["reel.mp4"]


@pytest.mark.asyncio
async def test_a_file_that_appears_while_the_body_arrives_is_not_replaced(tmp_path: Path) -> None:
   """Catches a refusal checked only before the fetch, which a file created meanwhile walks
   past."""

   destination = tmp_path / "reel.mp4"

   def plant(index: int) -> None:
      if index == 1:
         destination.write_bytes(b"planted meanwhile")

   with pytest.raises(FileExistsError):
      await download(ScriptedStreamer(before_each_chunk=plant), destination)

   assert destination.read_bytes() == b"planted meanwhile"
   assert sorted(path.name for path in tmp_path.iterdir()) == ["reel.mp4"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
   ("declared", "sent"),
   [(len(BODY) + 10, BODY), (len(BODY) - 10, BODY), (len(BODY), BODY[:-1])],
)
async def test_a_body_that_is_not_the_declared_length_is_refused_and_leaves_nothing(
   tmp_path: Path, declared: int, sent: bytes
) -> None:
   """Catches a truncated download reported as complete."""

   destination = tmp_path / "reel.mp4"
   streamer = ScriptedStreamer(headers={"content-length": str(declared)}, chunks=[sent])

   with pytest.raises(TransportFailure, match="declared"):
      await download(streamer, destination)

   assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_a_body_with_no_declared_length_is_written_whole(tmp_path: Path) -> None:
   """Catches a download that demands a length the CDN does not always send: one live 150x150
   image on 2026-09-23 answered 200 with no content-length."""

   destination = tmp_path / "picture.jpg"

   await download(ScriptedStreamer(headers={"content-type": "image/jpeg"}), destination)

   assert destination.read_bytes() == BODY


@pytest.mark.asyncio
async def test_a_body_that_stops_midway_leaves_nothing(tmp_path: Path) -> None:
   """Catches a temporary file left behind when the connection drops."""

   destination = tmp_path / "reel.mp4"

   with pytest.raises(TransportFailure, match="scripted stop"):
      await download(ScriptedStreamer(failure_after=1), destination)

   assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_a_refused_url_raises_not_found_and_writes_nothing(tmp_path: Path) -> None:
   """Catches an error page from the CDN saved as the rendition."""

   destination = tmp_path / "reel.mp4"
   streamer = ScriptedStreamer(status=403, headers={"content-length": "9"}, chunks=[b"forbidden"])

   with pytest.raises(NotFound):
      await download(streamer, destination)

   assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_a_redirect_is_not_saved_as_the_rendition(tmp_path: Path) -> None:
   """Catches a 3xx body written to disk, since the CDN transport never follows one."""

   streamer = ScriptedStreamer(status=302, headers={"location": "https://elsewhere.invalid/"})

   with pytest.raises(TransportFailure, match="302"):
      await download(streamer, tmp_path / "reel.mp4")

   assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_an_encoded_body_is_refused(tmp_path: Path) -> None:
   """Catches compressed bytes saved as the media file."""

   streamer = ScriptedStreamer(headers={"content-encoding": "gzip"})

   with pytest.raises(TransportFailure, match="gzip"):
      await download(streamer, tmp_path / "reel.mp4")

   assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_a_url_that_is_not_https_is_refused_before_anything_is_sent(tmp_path: Path) -> None:
   """Catches a rendition fetched in the clear."""

   streamer = ScriptedStreamer()

   with pytest.raises(ValueError, match="https"):
      await download_rendition(
         streamer,
         CDN_URL.replace("https://", "http://"),
         tmp_path / "reel.mp4",
         overwrite=False,
         user_agent=USER_AGENT,
      )

   assert streamer.requests == []


def family_pinned(handler: Callable[[httpx.Request], httpx.Response]) -> HttpxTransport:
   client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)

   return HttpxTransport(client=client, allowed_host_family="cdninstagram.com", cookieless=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
   "url",
   [
      "https://www.instagram.com/v/fixture.mp4",
      "https://cdninstagram.com.fixture.invalid/v/fixture.mp4",
      "https://fixturecdninstagram.com/v/fixture.mp4",
      "https://cdninstagram.com/v/fixture.mp4",
      "http://scontent-fixture-1.cdninstagram.com/v/fixture.mp4",
   ],
)
async def test_the_family_pin_refuses_a_host_outside_the_cdn(url: str) -> None:
   """Catches a CDN transport that would fetch from any host an upstream URL names, including a
   look-alike domain, the bare domain, and the right host in the clear. The first request, to a
   host inside the family, is the positive control."""

   seen: list[str] = []

   def handler(request: httpx.Request) -> httpx.Response:
      seen.append(str(request.url))
      return httpx.Response(200, content=b"ok")

   async with family_pinned(handler) as transport:
      async with transport.stream(Request(method="GET", url=CDN_URL)) as response:
         assert response.status_code == 200

      with pytest.raises(TransportFailure, match="cdninstagram.com"):
         async with transport.stream(Request(method="GET", url=url)):
            pass

   assert seen == [CDN_URL]


@pytest.mark.asyncio
async def test_the_cdn_transport_never_follows_a_redirect() -> None:
   """Catches a stream that follows a redirect to a host the signed URL did not name."""

   seen: list[str] = []

   def handler(request: httpx.Request) -> httpx.Response:
      seen.append(request.url.host)
      return httpx.Response(302, headers={"location": "https://scontent-other-1.cdninstagram.com/"})

   async with family_pinned(handler) as transport:
      async with transport.stream(Request(method="GET", url=CDN_URL)) as response:
         assert response.status_code == 302

   assert seen == ["scontent-fixture-1.cdninstagram.com"]


@pytest.mark.asyncio
async def test_a_cookieless_stream_refuses_a_cookie_header() -> None:
   """Catches a request builder's cookie header going out on the CDN stream, which the cookieless
   jar alone would not stop."""

   seen: list[str] = []

   def handler(request: httpx.Request) -> httpx.Response:
      seen.append(request.url.host)
      return httpx.Response(200, content=b"ok")

   carrying = Request(method="GET", url=CDN_URL, headers={"cookie": f"sessionid={SESSION_ID}"})

   async with family_pinned(handler) as transport:
      with pytest.raises(ValueError, match="cookie"):
         async with transport.stream(carrying):
            pass

   assert seen == []


def test_a_transport_takes_one_pin_or_the_other() -> None:
   """Catches a transport given both pins that silently honours only one of them."""

   with pytest.raises(ValueError, match="not both"):
      HttpxTransport(allowed_host="www.instagram.com", allowed_host_family="cdninstagram.com")


class ArrivingBody(httpx.AsyncByteStream):
   """A body that arrives in two chunks, as a socket's would, rather than already read."""

   async def __aiter__(self) -> AsyncIterator[bytes]:
      yield BODY[:100]
      yield BODY[100:]


class RecordingCdn:
   """Stands in for the CDN's socket under the client's own CDN transport."""

   def __init__(self) -> None:
      self.requests: list[httpx.Request] = []

   def __call__(self, request: httpx.Request) -> httpx.Response:
      self.requests.append(request)
      headers = {"content-type": "video/mp4", "content-length": str(len(BODY))}

      return httpx.Response(200, headers=headers, stream=ArrivingBody())


def rendition(url: str = CDN_URL) -> VideoRendition:
   return VideoRendition(url=url, width=720, height=1280, version_type=101)


def wire(client: AsyncClient, cdn: RecordingCdn) -> None:
   client._cdn._client._transport = httpx.MockTransport(cdn)


def assert_sent_without_cookies(cdn: RecordingCdn, user_agent: str) -> None:
   assert len(cdn.requests) == 1

   sent = cdn.requests[0]
   header_names = {name.lower() for name in sent.headers}

   assert "cookie" not in header_names
   assert SESSION_ID not in str(sent.headers)
   assert sent.headers["user-agent"] == user_agent
   assert sent.headers["referer"] == "https://www.instagram.com/"
   assert sent.headers["accept"] == "*/*"


@pytest.mark.asyncio
async def test_an_async_download_sends_no_cookie_to_the_cdn(tmp_path: Path) -> None:
   """Catches the account's cookies, or a cookie header, reaching the CDN from the awaitable
   surface. The control below shows the same client's instagram requests do carry them."""

   cdn = RecordingCdn()

   async with AsyncClient(a_session()) as client:
      wire(client, cdn)
      written = await client.media.download(rendition(), tmp_path / "reel.mp4")
      instagram = client._sender._sender._client.build_request("GET", "https://www.instagram.com/")

   assert SESSION_ID in instagram.headers["cookie"]
   assert_sent_without_cookies(cdn, client.user_agent)
   assert written.read_bytes() == BODY


def test_a_blocking_download_sends_no_cookie_and_writes_the_same_file(tmp_path: Path) -> None:
   """Catches the blocking surface reaching the CDN another way than the awaitable one does."""

   cdn = RecordingCdn()

   with SyncClient(a_session()) as client:
      wire(client._impl, cdn)
      written = client.media.download(rendition(), tmp_path / "reel.mp4")

      with pytest.raises(FileExistsError):
         client.media.download(rendition(), tmp_path / "reel.mp4")

      client.media.download(rendition(), tmp_path / "reel.mp4", overwrite=True)

   assert len(cdn.requests) == 2
   assert all("cookie" not in request.headers for request in cdn.requests)
   assert written == tmp_path / "reel.mp4"
   assert written.read_bytes() == BODY


@pytest.mark.asyncio
@pytest.mark.parametrize(
   "url",
   [
      "https://www.instagram.com/v/fixture.jpg",
      "https://scontent-fixture-1.fbcdn.net/v/fixture.jpg",
   ],
)
async def test_the_client_refuses_a_rendition_outside_the_cdn(tmp_path: Path, url: str) -> None:
   """Catches a client whose CDN pool is not pinned, so an image URL naming instagram.com or an
   unmeasured CDN family would be fetched."""

   cdn = RecordingCdn()
   image = MediaImage(url=url, width=150, height=150)

   async with AsyncClient(a_session()) as client:
      wire(client, cdn)

      with pytest.raises(TransportFailure):
         await client.media.download(image, tmp_path / "picture.jpg")

   assert cdn.requests == []
   assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_a_download_takes_no_turn_from_the_account_pacer(tmp_path: Path) -> None:
   """Catches a CDN fetch put through the API pacer, which would spend the account's request
   spacing on a static file and serialize downloads behind reads."""

   cdn = RecordingCdn()

   async with AsyncClient(a_session()) as client:
      wire(client, cdn)

      def refuse(*args: Any, **kwargs: Any) -> Any:
         raise AssertionError("a download asked the pacer for a slot")

      client._sender.pacer.slot = refuse  # type: ignore[method-assign]
      await client.media.download(rendition(), tmp_path / "reel.mp4")

   assert len(cdn.requests) == 1


@pytest.mark.asyncio
async def test_the_client_cdn_pool_is_cookieless_pinned_and_bounded() -> None:
   """Catches the client building its CDN pool with the account's jar, unpinned, or unbounded."""

   async with AsyncClient(a_session()) as client:
      cdn = client._cdn
      built = cdn._client.build_request("GET", CDN_URL)
      pool = cdn._client._transport._pool  # type: ignore[attr-defined]

      assert cdn.cookieless
      assert cdn.allowed_host_family == "cdninstagram.com"
      assert "cookie" not in built.headers
      assert pool._max_connections == 4


@pytest.mark.asyncio
async def test_closing_the_client_closes_the_cdn_pool() -> None:
   """Catches a third pool the client creates and never releases."""

   client = AsyncClient(a_session())
   await client.aclose()

   assert client._cdn._client.is_closed


@pytest.mark.asyncio
async def test_a_scoped_client_downloads_through_the_same_cdn_pool() -> None:
   """Catches ``with_behavior`` building a pool of its own that nothing closes."""

   async with AsyncClient(a_session()) as client:
      assert client.with_behavior(client.behavior)._cdn is client._cdn
