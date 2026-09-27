"""A post read on its own, by its shortcode or its media pk, and a post as the "more posts from"
strip under a post shows it.

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
   Location,
   MediaAudio,
   MediaImage,
   PostAuthor,
   UserTag,
   VideoRendition,
)
from dumpstagram.models.profiles import ProfileSummary

__all__ = ["PostDetail", "PostThumbnail", "PublishedPost"]


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
   has none. ``location``, ``user_tags`` and ``collaborators`` follow the rule on ``Post``:
   ``None`` means the read does not carry the field.

   Read by media pk rather than by shortcode, the post's item carries less, and what it lacks is
   left empty rather than guessed: its slides carry neither ``media_type`` nor ``product_type``,
   so ``carousel_children`` is empty while ``carousel_media_count`` still counts them; it carries
   no ``accessibility_caption``, no author's high resolution picture and no collaborators, so
   those are ``None``; and its tags carry no position. Read the post by its ``code`` for those.
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
   location: Location | None = None
   user_tags: tuple[UserTag, ...] | None = None
   collaborators: tuple[ProfileSummary, ...] | None = None


@dataclass(frozen=True)
class PostThumbnail:
   """One post as a strip of thumbnails shows it: what it is and how to open it, and no more.

   The "more posts from" strip under a post answers with a thinner item than any other read of a
   post: no time, no viewer state, no video renditions, no slides, and of its author only the
   ``pk`` and ``username``. So it is its own model rather than a :class:`Post` with guesses in
   it. Every field below was present on all six items of the two answers read on 2026-09-27.

   ``pk``, ``id`` and ``code`` mean what they mean on :class:`Post`, so ``pk`` is what
   :meth:`~dumpstagram.namespaces.media.AsyncMedia.by_id` takes and ``code`` what
   :meth:`~dumpstagram.namespaces.media.AsyncMedia.by_code` takes. ``author_id`` and
   ``author_username`` are the posting account's. ``images`` are the thumbnail's renditions in
   the upstream's order, the cover frames on a video. ``carousel_media_count`` is ``None`` on a
   post that is not a carousel, and ``caption`` ``None`` on one without a caption.
   """

   id: str
   pk: str
   code: str
   author_id: str
   author_username: str
   media_type: int
   product_type: str
   like_count: int
   comment_count: int
   like_and_view_counts_disabled: bool
   caption: str | None = None
   carousel_media_count: int | None = None
   images: tuple[MediaImage, ...] = ()


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
