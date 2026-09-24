"""A post read on its own, by its shortcode.

Every field below was present on the ``PolarisPostRootQuery`` item the engine read four times on
2026-09-23, recorded in `skills/reverse-engineer/knowledge/endpoints/read-a-post-by-shortcode.md`
and in `engine/logs/like-discovery-2026-09-23-051806.json`. The sample is one single image post
of the viewer's own, read around a like and an unlike, which is narrow.

It is not :class:`~dumpstagram.models.Post`. That model requires ``is_seen``, which the
timeline's media node carries and this item does not, and making the field optional would have
changed a line of the public contract. So the two share their parts and differ in that one field.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from dumpstagram.models.feed import (
   CarouselChild,
   MediaAudio,
   MediaImage,
   PostAuthor,
   VideoRendition,
)

__all__ = ["PostDetail", "PublishedPost"]


@dataclass(frozen=True)
class PostDetail:
   """One post as its own page reads it.

   ``pk`` is the media's own number and the identifier
   :meth:`~dumpstagram.aio.AsyncClient.like` and
   :meth:`~dumpstagram.aio.AsyncClient.unlike` take. ``id`` is ``"<pk>_<author id>"``, which
   those two refuse. ``code`` is the shortcode in the post's web address, which
   :meth:`~dumpstagram.aio.AsyncClient.post` takes.

   ``has_liked`` is whether the viewer likes the post, and ``like_count`` the upstream's count,
   which is the pair a like or an unlike is confirmed by. Both moved by exactly one across the
   measured like and unlike, and neither moved on a repeat of either.

   The other fields mean what they mean on :class:`~dumpstagram.models.Post`, the video,
   audio and carousel ones included: the post query's item carried the same keys for them as the
   timeline's node on the one reel and the one carousel read through both on 2026-09-23, except
   that its slides carry no ``has_audio``, which is why :class:`~dumpstagram.models.CarouselChild`
   has none.
   """

   id: str
   pk: str
   code: str
   taken_at: datetime
   author: PostAuthor
   media_type: int
   product_type: str
   like_count: int
   comment_count: int
   has_liked: bool
   caption: str | None = None
   accessibility_caption: str | None = None
   original_width: int | None = None
   original_height: int | None = None
   carousel_media_count: int | None = None
   images: tuple[MediaImage, ...] = ()
   is_paid_partnership: bool = False
   like_and_view_counts_disabled: bool = False
   videos: tuple[VideoRendition, ...] = ()
   video_duration: float | None = None
   has_audio: bool | None = None
   audio: MediaAudio | None = None
   carousel_children: tuple[CarouselChild, ...] = ()


@dataclass(frozen=True)
class PublishedPost:
   """What the upstream answers about a post just published.

   ``pk`` is what :meth:`~dumpstagram.namespaces.media.AsyncMedia.delete_post`,
   :meth:`~dumpstagram.namespaces.media.AsyncMedia.like` and the comment calls take, ``id`` is
   ``"<pk>_<owner id>"``, and ``code`` is the shortcode
   :meth:`~dumpstagram.namespaces.media.AsyncMedia.by_code` reads the post back by.
   ``media_type`` is 1 for a photo and 8 for a carousel, the values the answer and the post read
   both carry. ``upload_ids`` are the uploads the post was published from, in slide order.

   It is not a :class:`PostDetail`. The publish answers with the private API's media object,
   a different shape from the post read's, so the post is read back with ``by_code`` for the
   rest, which is also the read that confirms the post is up.
   """

   pk: str
   id: str
   code: str
   taken_at: datetime
   media_type: int
   upload_ids: tuple[str, ...]
