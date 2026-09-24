"""Read only. One Instagram API request and one CDN fetch, capped at two and one.

The first run on 2026-09-23 wrote a 5804 byte file that did not start like a JPEG and recorded
neither the response's content type nor whether it declared a length, so the second run records
both and names the file's format from its first bytes.

E1 item 6 of the web parity plan, the live acceptance of ``client.media.download``. It reads the
first home timeline page the way a browser does, out of the home document, with the page load
companions and the cookie sync tail off so the document is the only API request, and so maps the
preloaded page through the extended media model. It then picks the smallest image rendition on
the page, a post's or a carousel slide's, and downloads it through the public
``client.media.download`` into a temporary directory, checks the file, asks for the same path
again without ``overwrite`` to see it refused before any fetch, and deletes the file.

Recorded: each API request's name, status and length; each CDN fetch's host, whether it carried
a cookie header, and the header names it sent; the page's item kinds and the media counts the
model mapped (videos, renditions, durations, audio kinds, carousel slides and their kinds); the
response's status, content type and declared length, the downloaded file's size and the format
its first bytes name, and the rendition's width and height. No
URL, caption, username or file content.

The CDN fetch is counted at a request hook on the client's own CDN pool, which also refuses a
second fetch.

Credentials come from the saved session, which ``adopt_and_save.py`` wrote from the root ``.env``.

Run it from `engine/` with:

   uv run python probes/media_download_live.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from collections import Counter
from dataclasses import replace
from pathlib import Path

import httpx
from _probe_support import SESSION_PATH, load_env, report_run

from dumpstagram import AsyncClient
from dumpstagram._private.transport import Request, Response, Sender
from dumpstagram.behavior import EXPORT, FeedFirstPage
from dumpstagram.errors import DumpstagramError
from dumpstagram.models import MediaImage, Post
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE")

API_REQUEST_CAP = 2
CDN_FETCH_CAP = 1
FORMAT_BY_START = ((b"\xff\xd8\xff", "jpeg"), (b"RIFF", "riff, webp when bytes 8 to 12 say so"))


class CappedTransport:
   def __init__(self, inner: Sender, cap: int) -> None:
      self.inner = inner
      self.cap = cap
      self.sent: list[dict[str, object]] = []

   async def send(self, request: Request) -> Response:
      if len(self.sent) >= self.cap:
         raise RuntimeError(f"refusing API request {len(self.sent) + 1}, the cap is {self.cap}")

      entry: dict[str, object] = {"name": request.headers.get("x-fb-friendly-name", "document")}
      self.sent.append(entry)
      response = await self.inner.send(request)
      entry["status"] = response.status_code
      entry["length"] = len(response.content)

      return response

   async def aclose(self) -> None:
      closer = getattr(self.inner, "aclose", None)

      if closer is not None:
         await closer()


def media_counts(posts: list[Post]) -> dict[str, object]:
   children = [child for post in posts for child in post.carousel_children]

   return {
      "posts": len(posts),
      "media_types": dict(Counter(str(post.media_type) for post in posts)),
      "videos": sum(bool(post.videos) for post in posts),
      "video_renditions": sum(len(post.videos) for post in posts),
      "video_durations_read": sum(post.video_duration is not None for post in posts),
      "audio_kinds": dict(Counter(post.audio.kind.name for post in posts if post.audio)),
      "has_audio_true": sum(post.has_audio is True for post in posts),
      "carousels": sum(bool(post.carousel_children) for post in posts),
      "carousel_children": len(children),
      "carousel_child_media_types": dict(Counter(str(child.media_type) for child in children)),
   }


def smallest_image(posts: list[Post]) -> MediaImage | None:
   images = [image for post in posts for image in post.images]
   images.extend(
      image for post in posts for child in post.carousel_children for image in child.images
   )

   if not images:
      return None

   return min(images, key=lambda image: image.width * image.height)


async def run() -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}
   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   kind = "media-download-live"
   report: dict[str, object] = {"api_request_cap": API_REQUEST_CAP, "cdn_fetch_cap": CDN_FETCH_CAP}

   if not session_path.exists():
      report["failed_with"] = "no session file, run probes/adopt_and_save.py first"
      report_run(f"{kind}-failed", report)

      return 2

   behavior = replace(
      EXPORT,
      feed_first_page=FeedFirstPage.DOCUMENT,
      page_load_companions=False,
      cookie_sync=False,
   )
   client = AsyncClient(
      Session.load(session_path), user_agent=environment.get("IG_USER_AGENT"), behavior=behavior
   )
   capped = CappedTransport(client._sender._sender, API_REQUEST_CAP)
   client._sender._sender = capped
   report["api_requests"] = capped.sent
   cdn_fetches: list[dict[str, object]] = []
   report["cdn_fetches"] = cdn_fetches

   async def count_cdn_fetch(request: httpx.Request) -> None:
      if len(cdn_fetches) >= CDN_FETCH_CAP:
         raise RuntimeError(
            f"refusing CDN fetch {len(cdn_fetches) + 1}, the cap is {CDN_FETCH_CAP}"
         )

      cdn_fetches.append(
         {
            "host": request.url.host,
            "cookie_header_sent": "cookie" in request.headers,
            "header_names": sorted(request.headers.keys()),
         }
      )

   async def record_cdn_answer(response: httpx.Response) -> None:
      cdn_fetches[-1].update(
         {
            "status": response.status_code,
            "content_type": response.headers.get("content-type"),
            "content_length": response.headers.get("content-length"),
            "content_encoding": response.headers.get("content-encoding"),
         }
      )

   cdn_client = client._cdn._client
   hooks = cdn_client.event_hooks
   hooks["request"] = [*hooks.get("request", []), count_cdn_fetch]
   hooks["response"] = [*hooks.get("response", []), record_cdn_answer]
   cdn_client.event_hooks = hooks

   try:
      with tempfile.TemporaryDirectory() as directory:
         page = await client.feeds.home()
         posts = [item.post for item in page.items if item.post is not None]
         report["item_kinds"] = dict(Counter(item.kind.name for item in page.items))
         report["mapped"] = media_counts(posts)
         target = smallest_image(posts)

         if target is None:
            report["failed_with"] = "no image rendition on the first page"
         else:
            destination = Path(directory) / "rendition.jpg"
            written = await client.media.download(target, destination)
            content = written.read_bytes()
            report["download"] = {
               "rendition_width": target.width,
               "rendition_height": target.height,
               "bytes_written": len(content),
               "format_by_first_bytes": next(
                  (name for start, name in FORMAT_BY_START if content.startswith(start)), "other"
               ),
               "bytes_8_to_12": content[8:12].decode("ascii", errors="replace"),
               "left_in_the_directory": sorted(path.name for path in Path(directory).iterdir()),
            }

            try:
               await client.media.download(target, destination)
               report["second_download_refused"] = False
            except FileExistsError:
               report["second_download_refused"] = True

            written.unlink()
   except (DumpstagramError, RuntimeError) as failure:
      report["failed_with"] = type(failure).__name__
      report["failure_text"] = str(failure)[:200]
   finally:
      await client.aclose()

   report["api_requests_spent"] = len(capped.sent)
   report["cdn_fetches_spent"] = len(cdn_fetches)
   failed = "failed_with" in report
   report_run(f"{kind}-failed" if failed else kind, report)

   return 3 if failed else 0


def main() -> int:
   return asyncio.run(run())


if __name__ == "__main__":
   sys.exit(main())
