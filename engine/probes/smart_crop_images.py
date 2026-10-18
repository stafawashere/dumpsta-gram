"""No requests. Crops each image to the bounding box of the person in it.

The person is segmented with rembg's U2Net model, the mask's bounding box is taken with thin
speckle ignored, a margin is added, and the image is cropped to that box and written to a
subfolder. Originals are left untouched. An image whose person already fills the frame is copied
unchanged. Videos are ignored.

   uv run --with rembg --with pillow --with numpy python probes/smart_crop_images.py ~/Movies/harembigboobs
   uv run --with rembg --with pillow --with numpy python probes/smart_crop_images.py ~/Movies/harembigboobs --only 3,170,363
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from rembg import new_session, remove

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif"}
MARGIN = 0.04
PROJECTION_FLOOR = 0.02
FILLS_FRAME = 0.92


def body_box(mask: np.ndarray) -> tuple[int, int, int, int] | None:
   solid = mask > 128
   columns = solid.sum(axis=0)
   rows = solid.sum(axis=1)

   if columns.max() == 0 or rows.max() == 0:
      return None

   wide_columns = np.where(columns > columns.max() * PROJECTION_FLOOR)[0]
   tall_rows = np.where(rows > rows.max() * PROJECTION_FLOOR)[0]

   return int(wide_columns[0]), int(tall_rows[0]), int(wide_columns[-1]), int(tall_rows[-1])


def grown_box(box: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
   left, top, right, bottom = box
   margin_x = int((right - left) * MARGIN)
   margin_y = int((bottom - top) * MARGIN)

   return (
      max(0, left - margin_x),
      max(0, top - margin_y),
      min(width, right + margin_x),
      min(height, bottom + margin_y),
   )


def main() -> int:
   parser = argparse.ArgumentParser()
   parser.add_argument("folder", type=Path)
   parser.add_argument(
      "--only", default=None, help="comma separated sorted-index subset, for tests"
   )
   parser.add_argument("--recursive", action="store_true", help="descend into subfolders")
   parser.add_argument("--inplace", action="store_true", help="overwrite each original in place")
   arguments = parser.parse_args()

   folder = arguments.folder.expanduser()
   out = folder / "cropped"

   if not arguments.inplace:
      out.mkdir(exist_ok=True)

   candidates = folder.rglob("*") if arguments.recursive else folder.iterdir()
   files = sorted(
      path
      for path in candidates
      if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES and out not in path.parents
   )

   if arguments.only:
      wanted = {int(token) for token in arguments.only.split(",")}
      files = [path for index, path in enumerate(files) if index in wanted]

   session = new_session("u2net")
   started = time.monotonic()
   report = {"cropped": 0, "unchanged": 0, "no_person": 0}

   for path in files:
      image = Image.open(path).convert("RGB")
      cutout = remove(image, session=session)
      mask = np.array(cutout.split()[-1])
      box = body_box(mask)

      if box is None:
         report["no_person"] += 1
         continue

      left, top, right, bottom = box
      coverage = ((right - left) * (bottom - top)) / (image.width * image.height)

      if arguments.inplace:
         if coverage < FILLS_FRAME:
            image.crop(grown_box(box, image.width, image.height)).save(path)
            report["cropped"] += 1
         else:
            report["unchanged"] += 1
         continue

      destination = out / f"{path.stem}.jpg"

      if coverage >= FILLS_FRAME:
         image.save(destination, quality=92)
         report["unchanged"] += 1
         continue

      image.crop(grown_box(box, image.width, image.height)).save(destination, quality=92)
      report["cropped"] += 1

   report["elapsed_s"] = round(time.monotonic() - started, 1)
   print(report)

   return 0


if __name__ == "__main__":
   sys.exit(main())
