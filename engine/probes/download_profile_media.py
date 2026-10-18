"""Read only. Three live requests, plus one per highlight and one per twelve timeline posts.

Downloads every highlight item and every video on one account's post timeline into a single
folder. The API reads stay serial and paced by the engine, and the CDN fetches, which are not
API calls, run on a thread pool. The account is named on the command line and never reaches the
log, which records counts and sizes only.

Run it from `engine/` with:

   uv run python probes/download_profile_media.py USERNAME --session state/session-b.json
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from _probe_support import SESSION_PATH, report_run

from dumpstagram.behavior import FAST
from dumpstagram.client import SyncClient
from dumpstagram.errors import DumpstagramError
from dumpstagram.session import Session

CDN_WORKERS = 24


def best_media(item) -> tuple[str, str] | None:
   if item.videos:
      return item.videos[0].url, "mp4"

   if not item.images:
      return None

   largest_image = max(item.images, key=lambda image: image.width * image.height)

   return largest_image.url, "jpg"


def fetch(cdn: httpx.Client, url: str, destination: Path) -> int:
   if destination.exists():
      return 0

   response = cdn.get(url)
   response.raise_for_status()
   destination.write_bytes(response.content)

   return len(response.content)


def main() -> int:
   parser = argparse.ArgumentParser()
   parser.add_argument("username")
   parser.add_argument("--session", type=Path, default=SESSION_PATH)
   parser.add_argument("--out", type=Path, default=None)
   arguments = parser.parse_args()

   output_root = (arguments.out or Path.home() / "Movies" / arguments.username).expanduser()
   output_root.mkdir(parents=True, exist_ok=True)
   report: dict[str, object] = {}
   exit_code = 0
   started = time.monotonic()
   downloads: list[tuple[str, Path]] = []

   cdn = httpx.Client(
      follow_redirects=True, timeout=120, limits=httpx.Limits(max_connections=CDN_WORKERS)
   )
   pool = ThreadPoolExecutor(max_workers=CDN_WORKERS)
   futures = []

   def enqueue(url: str, destination: Path) -> None:
      downloads.append((url, destination))
      futures.append(pool.submit(fetch, cdn, url, destination))

   try:
      session = Session.load(arguments.session)

      with SyncClient(session, behavior=FAST) as client:
         profile = client.profile(arguments.username)
         tray = client.profiles.highlights(profile.id)
         report["highlights"] = len(tray.highlights)
         report["tray_has_more"] = tray.has_more

         for position, highlight in enumerate(tray.highlights, start=1):
            reel = client.stories.highlight(highlight.id)

            for item_position, item in enumerate(reel.items, start=1):
               media = best_media(item)

               if media is None:
                  continue

               url, extension = media
               stamp = item.taken_at.strftime("%Y-%m-%d_%H%M%S")
               enqueue(
                  url,
                  output_root
                  / f"hl{position:02d}_{item_position:03d}_{stamp}_{item.pk}.{extension}",
               )

         post_count = 0
         video_count = 0

         for post in client.profiles.iter_posts(arguments.username, limit=None):
            post_count += 1
            stamp = post.taken_at.strftime("%Y-%m-%d_%H%M%S")
            slides = post.carousel_children or (post,)

            for slide_position, slide in enumerate(slides, start=1):
               if not slide.videos:
                  continue

               video_count += 1
               enqueue(
                  slide.videos[0].url,
                  output_root / f"post_{stamp}_{post.pk}_{slide_position:02d}.mp4",
               )

         report["posts"] = post_count
         report["post_videos"] = video_count

   except DumpstagramError as failure:
      report["failure"] = {"type": type(failure).__name__, "code": getattr(failure, "code", None)}
      exit_code = 1

   saved_bytes = 0
   failed_downloads = 0

   for future in futures:
      try:
         saved_bytes += future.result()
      except httpx.HTTPError:
         failed_downloads += 1

   pool.shutdown()
   cdn.close()

   report["files"] = len(downloads)
   report["failed_downloads"] = failed_downloads
   report["bytes"] = saved_bytes
   report["elapsed_s"] = round(time.monotonic() - started, 1)
   report_run("download-profile-media", report)
   print(report)
   print(f"saved under {output_root}")

   return exit_code


if __name__ == "__main__":
   sys.exit(main())
