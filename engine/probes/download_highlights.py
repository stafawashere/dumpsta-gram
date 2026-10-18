"""Read only. Three live requests plus one per highlight, and one CDN fetch per item.

Downloads every highlight on one account's profile into a folder per highlight. The account is
named on the command line and never reaches the log, which records counts and sizes only.

   1-2  the profile by username, for the numeric id
   3    the highlights tray, first page only, since tray paging is still a hypothesis
   4+   each highlight's reel, which marks its first item seen as the browser does

Each item is saved once, as its largest image crop for a photo and its first video rendition
for a video. The media URLs are signed CDN links fetched with a plain `httpx` client.

Run it from `engine/` with:

   uv run python probes/download_highlights.py USERNAME
   uv run python probes/download_highlights.py USERNAME --out ~/Downloads/somewhere
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import httpx
from _probe_support import SESSION_PATH, report_run

from dumpstagram.client import SyncClient
from dumpstagram.errors import DumpstagramError
from dumpstagram.models import StoryItem
from dumpstagram.session import Session

PACE_SECONDS = 2.85
UNSAFE_PATH_CHARACTERS = re.compile(r"[/\\:\x00-\x1f]")


def safe_folder_name(position: int, title: str) -> str:
   cleaned_title = UNSAFE_PATH_CHARACTERS.sub("_", title).strip(" .") or "untitled"

   return f"{position:02d} {cleaned_title}"


def media_url_for(item: StoryItem) -> tuple[str, str] | None:
   is_video = item.media_type == 2 and bool(item.videos)

   if is_video:
      return item.videos[0].url, "mp4"

   if not item.images:
      return None

   largest_image = max(item.images, key=lambda image: image.width * image.height)

   return largest_image.url, "jpg"


def download(cdn: httpx.Client, url: str, destination: Path) -> int:
   response = cdn.get(url)
   response.raise_for_status()
   destination.write_bytes(response.content)

   return len(response.content)


def main() -> int:
   parser = argparse.ArgumentParser()
   parser.add_argument("username")
   parser.add_argument("--out", type=Path, default=None)
   arguments = parser.parse_args()

   output_root = arguments.out or Path.home() / "Downloads" / f"{arguments.username}-highlights"
   output_root = output_root.expanduser()
   report: dict[str, object] = {"highlights": []}
   exit_code = 0
   started = time.monotonic()

   try:
      session = Session.load(SESSION_PATH)

      with SyncClient(session) as client, httpx.Client(follow_redirects=True, timeout=60) as cdn:
         profile = client.profile(arguments.username)
         tray = client.profiles.highlights(profile.id)
         report["tray_has_more"] = tray.has_more

         for position, highlight in enumerate(tray.highlights, start=1):
            reel = client.stories.highlight(highlight.id)
            folder = output_root / safe_folder_name(position, highlight.title)
            folder.mkdir(parents=True, exist_ok=True)

            saved_items = 0
            saved_bytes = 0
            skipped_items = 0

            for item_position, item in enumerate(reel.items, start=1):
               media = media_url_for(item)

               if media is None:
                  skipped_items += 1
                  continue

               url, extension = media
               stamp = item.taken_at.strftime("%Y-%m-%d_%H%M%S")
               destination = folder / f"{item_position:03d}_{stamp}_{item.pk}.{extension}"

               if not destination.exists():
                  saved_bytes += download(cdn, url, destination)

               saved_items += 1

            report["highlights"].append(
               {
                  "position": position,
                  "items": len(reel.items),
                  "saved": saved_items,
                  "skipped": skipped_items,
                  "bytes": saved_bytes,
               }
            )
            time.sleep(PACE_SECONDS)

   except DumpstagramError as failure:
      report["failure"] = {"type": type(failure).__name__, "code": getattr(failure, "code", None)}
      exit_code = 1

   report["elapsed_s"] = round(time.monotonic() - started, 1)
   report_run("download-highlights", report)
   print(f"saved under {output_root}")

   return exit_code


if __name__ == "__main__":
   sys.exit(main())
