"""Publish a photo or a carousel, and delete the viewer's own post, each write sent once.

A publish is two kinds of write. Every image is uploaded first, one write each to the upload
host, and then one publish names the uploads. The upload alone shows nobody anything, but it is
still a write: it stores a file on the account's behalf, so it is spaced, counted against the
budget and never sent twice, like every other write.

When an upload succeeds and a later write fails, the uploads that applied are orphaned: stored,
published nowhere, and never retried or reused here. The error raised is the original one, as
it came from the write that failed, with a note naming which half failed and every upload id
that applied, so a caller can tell a publish that never started from one that stopped half way.

A delete sets a state. It names the post by the ``<pk>_<owner id>`` form the web client sends,
built from the post ``pk`` and the viewer's own id, because only the viewer's own post can be
deleted.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable, Sequence

from dumpstagram._core.images import JPEG_CONTENT_TYPE, JpegImage, read_jpeg
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.writing import send_write
from dumpstagram._private.transport import WriteRequest
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.parse.posting import (
   check_upload_answer,
   parse_published_post,
   post_was_deleted,
)
from dumpstagram._private.web.requests.media import is_a_media_pk
from dumpstagram._private.web.requests.posting import (
   UploadedImage,
   build_carousel_publish_request,
   build_delete_post_request,
   build_photo_publish_request,
   build_photo_upload_request,
)
from dumpstagram.errors import UpstreamRejected
from dumpstagram.models import PublishedPost
from dumpstagram.session import Session

__all__ = ["MIN_CAROUSEL_IMAGES", "delete_post", "publish_carousel", "publish_photo"]

MIN_CAROUSEL_IMAGES = 2
"""A carousel of one image is a photo, which :func:`publish_photo` publishes."""

NOTHING_DELETED = "post_not_deleted"
"""The code raised when a delete's answer says no post was deleted."""

ImageSource = bytes | str | os.PathLike[str]

Clock = Callable[[], float]


async def publish_photo(
   sender: PacedSender,
   upload_sender: PacedSender,
   session: Session,
   image: ImageSource,
   *,
   caption: str = "",
   user_agent: str = DEFAULT_USER_AGENT,
   clock: Clock = time.time,
) -> PublishedPost:
   """Upload ``image`` and publish it as a post with ``caption``.

   Two writes, the upload through ``upload_sender`` and the publish through ``sender``, and
   one bootstrap first when the session carries no page token.
   """

   _refuse_what_is_not_a_caption(caption)
   jpeg = await asyncio.to_thread(read_jpeg, image)

   if not session.fb_dtsg:
      await bootstrap(sender, session, user_agent=user_agent)

   (upload_id,) = _upload_ids(1, clock)
   uploaded = await _upload_all(upload_sender, session, [jpeg], [upload_id], user_agent)

   request = build_photo_publish_request(session, upload_id, caption, user_agent=user_agent)

   return await _publish(sender, session, WriteRequest(request, "publish_photo"), uploaded)


async def publish_carousel(
   sender: PacedSender,
   upload_sender: PacedSender,
   session: Session,
   images: Sequence[ImageSource],
   *,
   caption: str = "",
   user_agent: str = DEFAULT_USER_AGENT,
   clock: Clock = time.time,
) -> PublishedPost:
   """Upload every image in ``images`` and publish them as one carousel, in that order.

   One write per image and one publish, and one bootstrap first when the session carries no
   page token. Every image is read and checked before the first upload leaves.
   """

   _refuse_what_is_not_a_caption(caption)

   is_a_single_image = isinstance(images, (bytes, str, os.PathLike))

   if is_a_single_image:
      raise TypeError("a carousel takes a sequence of images, not one image")

   too_few_images = len(images) < MIN_CAROUSEL_IMAGES

   if too_few_images:
      raise ValueError(
         f"a carousel needs at least {MIN_CAROUSEL_IMAGES} images, publish_photo takes one"
      )

   jpegs = [await asyncio.to_thread(read_jpeg, image) for image in images]

   if not session.fb_dtsg:
      await bootstrap(sender, session, user_agent=user_agent)

   upload_ids = _upload_ids(len(jpegs), clock)
   uploaded = await _upload_all(upload_sender, session, jpegs, upload_ids, user_agent)

   (client_sidecar_id,) = _upload_ids(1, clock)
   request = build_carousel_publish_request(
      session,
      list(uploaded),
      caption,
      client_sidecar_id=client_sidecar_id,
      user_agent=user_agent,
   )

   return await _publish(sender, session, WriteRequest(request, "publish_carousel"), uploaded)


async def delete_post(
   sender: PacedSender,
   session: Session,
   post_pk: str,
   code: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> None:
   """Delete the viewer's own post whose media ``pk`` is ``post_pk`` and shortcode ``code``.

   One write, and one bootstrap first when the session carries no page token. Raises
   :class:`~dumpstagram.errors.UpstreamRejected` with code ``post_not_deleted`` when the
   answer says nothing was deleted.
   """

   if not is_a_media_pk(post_pk):
      raise ValueError(
         f"{post_pk!r} is not a media pk. Pass PublishedPost.pk or PostDetail.pk, not the id form"
      )

   if not session.fb_dtsg:
      await bootstrap(sender, session, user_agent=user_agent)

   media_id = f"{post_pk}_{session.ds_user_id}"
   request = build_delete_post_request(session, media_id, code, user_agent=user_agent)
   payload = await send_write(sender, session, WriteRequest(request, "delete_post"))

   if not post_was_deleted(payload):
      raise UpstreamRejected(
         "the delete was answered without an error but reported no post deleted",
         code=NOTHING_DELETED,
      )


async def _upload_all(
   upload_sender: PacedSender,
   session: Session,
   jpegs: Sequence[JpegImage],
   upload_ids: Sequence[str],
   user_agent: str,
) -> tuple[str, ...]:
   applied: list[str] = []

   for position, (jpeg, upload_id) in enumerate(zip(jpegs, upload_ids, strict=True), start=1):
      image = UploadedImage(
         upload_id=upload_id,
         content=jpeg.content,
         content_type=JPEG_CONTENT_TYPE,
         width=jpeg.width,
         height=jpeg.height,
      )
      request = build_photo_upload_request(session, image, user_agent=user_agent)

      try:
         payload = await send_write(upload_sender, session, WriteRequest(request, "upload_photo"))
         check_upload_answer(payload, upload_id)
      except Exception as failure:
         failure.add_note(_upload_failed_note(position, len(jpegs), applied))
         raise

      applied.append(upload_id)

   return tuple(applied)


async def _publish(
   sender: PacedSender,
   session: Session,
   write: WriteRequest,
   uploaded: tuple[str, ...],
) -> PublishedPost:
   try:
      payload = await send_write(sender, session, write)

      return parse_published_post(payload, uploaded)
   except Exception as failure:
      failure.add_note(
         "posting: every upload applied and the publish failed, so uploads "
         f"{', '.join(uploaded)} are orphaned unless the publish applied. Neither half was "
         "retried. The post may be up when the outcome is unknown or the answer could not be "
         "read, so read the profile's media_count before publishing again"
      )
      raise


def _upload_failed_note(position: int, total: int, applied: list[str]) -> str:
   orphaned = (
      f"uploads {', '.join(applied)} applied before it and are orphaned"
      if applied
      else "no upload had applied before it"
   )

   return (
      f"posting: upload {position} of {total} failed, so nothing was published and {orphaned}. "
      "Neither half was retried"
   )


def _upload_ids(count: int, clock: Clock) -> list[str]:
   """Upload ids the way the composer draws them, the millisecond clock, one apart per image."""

   base = int(clock() * 1000)

   return [str(base + offset) for offset in range(count)]


def _refuse_what_is_not_a_caption(caption: str) -> None:
   if not isinstance(caption, str):
      raise TypeError("a caption is text")
