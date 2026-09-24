"""One media rendition fetched from the CDN and written to a file.

A CDN fetch is not an Instagram API request, so it takes no pacer slot, per the media and CDN
exception of ADR-0001: the API pacer spaces the account's requests to the upstream's gateway, and
a rendition is a static file on a content network that a browser fetches alongside, many at a
time. One download is one fetch. Downloads may run concurrently, bounded by the CDN transport's
pool.

The body is streamed to a temporary file beside the destination and renamed onto it only once
every byte the CDN declared has arrived, so an interrupted or short download never leaves a
file at the destination. The file is created owner-only, as ``tempfile.mkstemp`` makes it.
"""

from __future__ import annotations

import asyncio
import errno
import os
import tempfile
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import BinaryIO

from dumpstagram._private.transport import StreamSender
from dumpstagram._private.web.cdn import build_rendition_request
from dumpstagram.errors import NotFound, TransportFailure

__all__ = ["MAX_DOWNLOAD_BYTES", "download_rendition"]

MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024
"""The largest body a download accepts. The largest rendition measured was 23.5 MB."""

SUCCESS_STATUS = 200
"""The only status a rendition answered with on every measured fetch."""

UNENCODED = (None, "identity")

LINKLESS_ERRNOS = frozenset(
   {errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EMLINK, errno.EXDEV}
)
"""What a file system without hard links answers ``os.link`` with."""


def _refuse_an_existing_file(destination: Path, overwrite: bool) -> None:
   is_taken = destination.exists() or destination.is_symlink()
   refuses = is_taken and not overwrite

   if refuses:
      raise FileExistsError(errno.EEXIST, "a file is already at the destination", str(destination))


def _refuse_the_status(status_code: int) -> None:
   if status_code == SUCCESS_STATUS:
      return

   is_client_error = 400 <= status_code < 500

   if is_client_error:
      raise NotFound(
         f"the CDN answered {status_code}; a rendition URL is signed and expires, "
         "so read the post again for a fresh one"
      )

   raise TransportFailure(f"the CDN answered {status_code} rather than the rendition")


def _declared_length(headers: Mapping[str, str]) -> int | None:
   raw = headers.get("content-length")

   if raw is None:
      return None

   try:
      declared = int(raw)
   except ValueError as failure:
      raise TransportFailure("the CDN declared a length that is not a number") from failure

   if declared < 0:
      raise TransportFailure("the CDN declared a negative length")

   return declared


def _open_temporary(destination: Path) -> tuple[BinaryIO, Path]:
   descriptor, name = tempfile.mkstemp(
      dir=destination.parent, prefix=f".{destination.name}.", suffix=".part"
   )

   return os.fdopen(descriptor, "wb"), Path(name)


def _flush_to_disk(handle: BinaryIO) -> None:
   handle.flush()
   os.fsync(handle.fileno())


def _place(temporary: Path, destination: Path, overwrite: bool) -> None:
   """Rename the finished file onto the destination, refusing to replace one unless told.

   Without ``overwrite`` the file is hard linked into place, which fails if anything took the
   name while the body arrived. A file system without hard links falls back to checking the
   name and renaming, which leaves that window open.
   """

   if overwrite:
      os.replace(temporary, destination)

      return

   try:
      os.link(temporary, destination)
   except FileExistsError:
      raise
   except OSError as failure:
      if failure.errno not in LINKLESS_ERRNOS:
         raise

      _refuse_an_existing_file(destination, overwrite)
      os.replace(temporary, destination)

      return

   os.unlink(temporary)


def _discard(temporary: Path) -> None:
   try:
      temporary.unlink()
   except FileNotFoundError:
      return


async def _write_body(body: AsyncIterator[bytes], handle: BinaryIO) -> int:
   received = 0

   async for chunk in body:
      received += len(chunk)

      if received > MAX_DOWNLOAD_BYTES:
         raise TransportFailure(f"the rendition exceeded {MAX_DOWNLOAD_BYTES} bytes")

      await asyncio.to_thread(handle.write, chunk)

   return received


async def download_rendition(
   streamer: StreamSender,
   url: str,
   path: str | os.PathLike[str],
   *,
   overwrite: bool,
   user_agent: str,
) -> Path:
   """Fetch the rendition at ``url`` into ``path`` and return the path written.

   Raises :class:`FileExistsError` before anything is sent when ``path`` exists and
   ``overwrite`` is false. Raises :class:`~dumpstagram.errors.TransportFailure` when the body
   is shorter or longer than the ``content-length`` the CDN declared, arrives encoded, or
   exceeds :data:`MAX_DOWNLOAD_BYTES`, and :class:`~dumpstagram.errors.NotFound` on a 4xx, which
   an expired signed URL is expected to answer. On any failure, cancellation included, nothing is
   left at ``path`` or beside it.

   File writes run on a worker thread, one chunk at a time. A cancelled download stops reading
   at once, and the chunk already handed to the thread finishes into a temporary file that is
   then removed.
   """

   destination = Path(os.fspath(path))
   _refuse_an_existing_file(destination, overwrite)
   request = build_rendition_request(url, user_agent=user_agent)
   temporary: Path | None = None
   placed = False

   try:
      async with streamer.stream(request) as response:
         _refuse_the_status(response.status_code)
         encoding = response.headers.get("content-encoding")

         if encoding not in UNENCODED:
            raise TransportFailure(f"the CDN sent the rendition encoded as {encoding}")

         declared = _declared_length(response.headers)
         handle, part = await asyncio.to_thread(_open_temporary, destination)
         temporary = part

         try:
            received = await _write_body(response.body, handle)
            await asyncio.to_thread(_flush_to_disk, handle)
         finally:
            handle.close()

      is_short_or_long = declared is not None and received != declared

      if is_short_or_long:
         raise TransportFailure(f"the CDN declared {declared} bytes and sent {received}")

      await asyncio.to_thread(_place, part, destination, overwrite)
      placed = True
   finally:
      if not placed:
         if temporary is not None:
            _discard(temporary)

   return destination
