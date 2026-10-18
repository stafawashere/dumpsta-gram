"""No requests. Builds labelled contact sheets of every media file's cover frame.

For each file in the folder, the cover is the image itself or a video's first frame. Each cover
is drawn into a grid tile with its index number, and a manifest maps index to filename. A later
step reads the sheets, decides which indices to move, and acts on the manifest.

   uv run python probes/build_cover_sheets.py ~/Movies/harembigboobs OUTDIR
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

MEDIA_SUFFIXES = {".mp4", ".jpg", ".jpeg", ".png", ".webp"}
TILE = 220
COLUMNS = 8
ROWS = 6
PER_SHEET = COLUMNS * ROWS
FONT = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 22)


def cover_image(path: Path, scratch: Path, index: int) -> Image.Image:
   if path.suffix.lower() == ".mp4":
      frame = scratch / f"{index}.jpg"
      subprocess.run(
         ["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1", "-q:v", "3", str(frame)],
         check=False,
      )
      source = Image.open(frame)
   else:
      source = Image.open(path)

   return source.convert("RGB")


def tile_for(path: Path, scratch: Path, index: int) -> Image.Image:
   cover = cover_image(path, scratch, index)
   cover.thumbnail((TILE, TILE))
   tile = Image.new("RGB", (TILE, TILE), (20, 20, 20))
   tile.paste(cover, ((TILE - cover.width) // 2, (TILE - cover.height) // 2))

   draw = ImageDraw.Draw(tile)
   label = str(index)
   box = draw.textbbox((0, 0), label, font=FONT)
   draw.rectangle((0, 0, box[2] + 10, box[3] + 10), fill=(0, 0, 0))
   draw.text((5, 2), label, fill=(0, 255, 120), font=FONT)

   return tile


def main() -> int:
   folder = Path(sys.argv[1]).expanduser()
   out = Path(sys.argv[2]).expanduser()
   out.mkdir(parents=True, exist_ok=True)

   files = sorted(path for path in folder.iterdir() if path.suffix.lower() in MEDIA_SUFFIXES)
   manifest = {index: path.name for index, path in enumerate(files)}
   (out / "manifest.json").write_text(json.dumps(manifest, indent=2))

   with tempfile.TemporaryDirectory() as scratch_name:
      scratch = Path(scratch_name)

      with ThreadPoolExecutor(max_workers=12) as pool:
         tiles = list(pool.map(lambda pair: tile_for(pair[1], scratch, pair[0]), enumerate(files)))

   sheet_count = 0

   for start in range(0, len(tiles), PER_SHEET):
      chunk = tiles[start : start + PER_SHEET]
      sheet = Image.new("RGB", (COLUMNS * TILE, ROWS * TILE), (10, 10, 10))

      for position, tile in enumerate(chunk):
         row, column = divmod(position, COLUMNS)
         sheet.paste(tile, (column * TILE, row * TILE))

      sheet_count += 1
      sheet.save(out / f"sheet_{sheet_count:02d}.jpg", quality=80)

   print(f"{len(files)} files, {sheet_count} sheets in {out}")

   return 0


if __name__ == "__main__":
   sys.exit(main())
