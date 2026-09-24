"""What the engine checks about an image before it uploads one, and nothing more.

Only JPEG is accepted. The composer uploads a JPEG, measured on 2026-09-23 with two generated
files, and what the upload answers for another format is unobserved, so another format is
refused here rather than sent. Converting is the caller's to do, which keeps an image library
out of the package's dependencies.

The width and height travel in the upload's parameters, so they are read from the file's own
frame header rather than trusted from the caller.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

__all__ = ["JPEG_CONTENT_TYPE", "JpegImage", "read_jpeg"]

JPEG_CONTENT_TYPE = "image/jpeg"

_START_OF_IMAGE = b"\xff\xd8"

_FRAME_MARKERS = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
"""The start of frame markers, which carry the dimensions. C4, C8 and CC are not frames."""

_STANDALONE_MARKERS = frozenset({0x01, *range(0xD0, 0xD8)})


@dataclass(frozen=True)
class JpegImage:
   """A JPEG file's bytes and the dimensions its frame header declares."""

   content: bytes
   width: int
   height: int


def read_jpeg(image: bytes | str | os.PathLike[str]) -> JpegImage:
   """Take ``image`` as bytes or as a path to a file, and return it with its dimensions.

   Raises :class:`ValueError` for anything that is not a JPEG with a frame header, and the
   builtin ``OSError`` family when a path cannot be read.
   """

   content = image if isinstance(image, bytes) else Path(image).read_bytes()
   is_a_jpeg = content.startswith(_START_OF_IMAGE)

   if not is_a_jpeg:
      raise ValueError("only a JPEG can be posted, and this does not start like one")

   width, height = _frame_dimensions(content)

   return JpegImage(content=content, width=width, height=height)


def _frame_dimensions(content: bytes) -> tuple[int, int]:
   offset = len(_START_OF_IMAGE)

   while offset + 4 <= len(content):
      if content[offset] != 0xFF:
         raise ValueError("the JPEG's markers are malformed before its frame header")

      marker = content[offset + 1]

      if marker == 0xFF:
         offset += 1
         continue

      if marker in _STANDALONE_MARKERS:
         offset += 2
         continue

      segment_length = int.from_bytes(content[offset + 2 : offset + 4], "big")
      is_a_frame = marker in _FRAME_MARKERS
      has_room_for_dimensions = offset + 9 <= len(content)

      if is_a_frame and has_room_for_dimensions:
         height = int.from_bytes(content[offset + 5 : offset + 7], "big")
         width = int.from_bytes(content[offset + 7 : offset + 9], "big")
         has_area = width > 0 and height > 0

         if not has_area:
            raise ValueError("the JPEG's frame header declares no area")

         return width, height

      offset += 2 + segment_length

   raise ValueError("the JPEG has no frame header, so its dimensions are unknown")
