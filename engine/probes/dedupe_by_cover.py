"""No requests. Deletes files in one folder whose cover frame repeats another file's.

The cover is the first frame of a video or the image itself, scaled by ffmpeg to 9x8 grey and
reduced to a 64 bit difference hash. Files whose hashes differ in at most THRESHOLD bits count
as one, and the largest of them is kept.

   uv run python probes/dedupe_by_cover.py ~/Movies/someone
   uv run python probes/dedupe_by_cover.py ~/Movies/someone --dry-run
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from _probe_support import report_run

THRESHOLD = 4
MEDIA_SUFFIXES = {".mp4", ".jpg", ".jpeg", ".png", ".webp"}


def cover_hash(path: Path) -> int | None:
   command = [
      "ffmpeg",
      "-v",
      "error",
      "-i",
      str(path),
      "-frames:v",
      "1",
      "-vf",
      "scale=9:8,format=gray",
      "-f",
      "rawvideo",
      "-",
   ]
   pixels = subprocess.run(command, capture_output=True).stdout

   if len(pixels) != 72:
      return None

   bits = 0

   for row in range(8):
      for column in range(8):
         left = pixels[row * 9 + column]
         right = pixels[row * 9 + column + 1]
         bits = (bits << 1) | int(left > right)

   return bits


def main() -> int:
   parser = argparse.ArgumentParser()
   parser.add_argument("folder", type=Path)
   parser.add_argument("--dry-run", action="store_true")
   arguments = parser.parse_args()

   started = time.monotonic()
   files = sorted(
      (
         path
         for path in arguments.folder.expanduser().iterdir()
         if path.suffix.lower() in MEDIA_SUFFIXES
      ),
      key=lambda path: path.stat().st_size,
      reverse=True,
   )

   with ThreadPoolExecutor(max_workers=12) as pool:
      hashes = list(pool.map(cover_hash, files))

   kept: list[int] = []
   duplicates: list[Path] = []
   unreadable = 0

   for path, file_hash in zip(files, hashes, strict=True):
      if file_hash is None:
         unreadable += 1
         continue

      is_duplicate = any(bin(file_hash ^ kept_hash).count("1") <= THRESHOLD for kept_hash in kept)

      if is_duplicate:
         duplicates.append(path)
      else:
         kept.append(file_hash)

   freed_bytes = sum(path.stat().st_size for path in duplicates)

   if not arguments.dry_run:
      for path in duplicates:
         path.unlink()

   report = {
      "files": len(files),
      "kept": len(kept),
      "duplicates": len(duplicates),
      "unreadable": unreadable,
      "freed_bytes": freed_bytes,
      "dry_run": arguments.dry_run,
      "elapsed_s": round(time.monotonic() - started, 1),
   }
   report_run("dedupe-by-cover", report)
   print(report)

   return 0


if __name__ == "__main__":
   sys.exit(main())
