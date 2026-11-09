"""Read only. About four live requests: the profile by username, one posts page, one story reel.

Exports one account's newest post, every slide of it, and the first few videos of its current
story into a single zip. The story is read without marking anything seen. The newest post is
chosen by its timestamp across the first grid page, so a pinned older post does not win. The
account is named on the command line and never reaches the log, which records counts and sizes
only.

Run it from `engine/` with:

   uv run python probes/export_latest_post_and_story.py USERNAME --out ~/Downloads/export.zip
"""

from __future__ import annotations

import argparse
import sys
import time
import zipfile
from dataclasses import replace
from pathlib import Path

import httpx
from _probe_support import SESSION_PATH, report_run

from dumpstagram.behavior import PARITY
from dumpstagram.client import SyncClient
from dumpstagram.errors import DumpstagramError
from dumpstagram.session import Session

NO_STORY_SEEN = replace(PARITY, mark_stories_seen=False)


def best_media(item) -> tuple[str, str] | None:
   if item.videos:
      return item.videos[0].url, "mp4"

   if not item.images:
      return None

   largest_image = max(item.images, key=lambda image: image.width * image.height)

   return largest_image.url, "jpg"


def main() -> int:
   parser = argparse.ArgumentParser()
   parser.add_argument("username")
   parser.add_argument("--session", type=Path, default=SESSION_PATH)
   parser.add_argument("--out", type=Path, required=True)
   parser.add_argument("--story-videos", type=int, default=3)
   arguments = parser.parse_args()

   zip_path = arguments.out.expanduser()
   zip_path.parent.mkdir(parents=True, exist_ok=True)
   report: dict[str, object] = {}
   exit_code = 0
   started = time.monotonic()
   entries: list[tuple[str, str]] = []

   try:
      session = Session.load(arguments.session)

      with SyncClient(session, behavior=NO_STORY_SEEN) as client:
         profile = client.profile(arguments.username)
         first_page = client.profiles.posts(arguments.username)
         posts = list(first_page.items)
         report["grid_posts_read"] = len(posts)

         if posts:
            newest_post = max(posts, key=lambda post: post.taken_at)
            stamp = newest_post.taken_at.strftime("%Y-%m-%d_%H%M%S")
            slides = newest_post.carousel_children or (newest_post,)

            for slide_position, slide in enumerate(slides, start=1):
               media = best_media(slide)

               if media is None:
                  continue

               url, extension = media
               entries.append((url, f"post_{stamp}_{slide_position:02d}.{extension}"))

            report["post_slides"] = len(slides)

         reel = client.stories.reel(profile.id)
         story_items = reel.items if reel else ()
         story_videos = [item for item in story_items if item.videos]
         report["story_items"] = len(story_items)
         report["story_videos_available"] = len(story_videos)

         for video_position, item in enumerate(story_videos[: arguments.story_videos], start=1):
            stamp = item.taken_at.strftime("%Y-%m-%d_%H%M%S")
            entries.append((item.videos[0].url, f"story_{video_position:02d}_{stamp}.mp4"))

   except DumpstagramError as failure:
      report["failure"] = {"type": type(failure).__name__, "code": getattr(failure, "code", None)}
      exit_code = 1

   saved_bytes = 0
   failed_downloads = 0

   with httpx.Client(follow_redirects=True, timeout=120) as cdn:
      with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
         for url, name in entries:
            try:
               response = cdn.get(url)
               response.raise_for_status()
            except httpx.HTTPError:
               failed_downloads += 1
               continue

            archive.writestr(name, response.content)
            saved_bytes += len(response.content)

   report["files"] = len(entries) - failed_downloads
   report["failed_downloads"] = failed_downloads
   report["bytes"] = saved_bytes
   report["elapsed_s"] = round(time.monotonic() - started, 1)
   report_run("export-latest-post-and-story", report)
   print(f"saved {zip_path}")

   return exit_code


if __name__ == "__main__":
   sys.exit(main())
