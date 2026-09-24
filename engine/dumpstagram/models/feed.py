"""Typed representations of one page of the home timeline.

Every field below was observed on live `PolarisFeedRootPaginationCachedQuery_subscribe`
responses on 2026-09-21, recorded in
`skills/reverse-engineer/knowledge/endpoints/home-timeline-feed-page.md` and in
`engine/logs/feed-node-shape-2026-09-21-*.json`. The measured sample is six media nodes
across one page, plus three ads and six explore stories, so the counts below say how wide the
evidence is as well as what it showed.

The video, carousel and audio fields were added on 2026-09-23 for E1 item 6 of the web parity
plan, from `engine/probes/media_shape.py`: eleven reels, seven carousels and thirty-one carousel
children across seven feed pages, plus one reel and one carousel read again through the post
query, logged in `engine/logs/media-shape-2026-09-23-*.json`. No carousel child that was a video
was seen, so a video child is mapped by the same rules as a reel and that mapping is unmeasured.

Fields the upstream sends and these models do not carry are named in
`dumpstagram/_private/web/parse/feed.py` and `parse/media.py` beside the mapping that drops
them.

Nothing here parses. Construction is done by the mappers in `_private/web/parse/feed.py` and
`parse/media.py`, which read named keys and raise rather than filling a default, so an upstream
rename is loud.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

__all__ = [
   "AudioKind",
   "CarouselChild",
   "FeedItem",
   "FeedItemKind",
   "MediaAudio",
   "MediaImage",
   "Post",
   "PostAuthor",
   "VideoRendition",
]


class FeedItemKind(StrEnum):
   """Which of the timeline's nine slots one feed item filled.

   The upstream sends every item as one object with nine sibling slots, of which exactly one
   was non-null on all fifteen items measured. The slot names are the vocabulary, so they are
   reproduced rather than renamed, and every one the upstream declares is listed here even
   though only three have ever been seen filled. A tenth slot arriving later is a
   :class:`~dumpstagram.errors.SchemaChanged`, not a new member invented at runtime.
   """

   POST = "media"
   AD = "ad"
   EXPLORE_STORY = "explore_story"
   END_OF_FEED = "end_of_feed_demarcator"
   STORIES_TRAY = "stories_netego"
   SUGGESTED_USERS = "suggested_users"
   BLOKS_UNIT = "bloks_netego"
   ICEBREAKERS = "abra_icebreakers_in_feed_unit"
   AD_FOR_AD = "ad4ad_in_webfeed"


@dataclass(frozen=True)
class MediaImage:
   """One rendition of a post's image.

   The upstream sends thirteen of these per post at several aspect ratios, which are crops
   rather than a single image at descending sizes, so none of them is the picture and picking
   one is the caller's decision. They arrive in the upstream's order and nothing here sorts
   them.
   """

   url: str
   width: int
   height: int


@dataclass(frozen=True)
class VideoRendition:
   """One rendition of a video, which :meth:`AsyncMedia.download
   <dumpstagram.namespaces.media.AsyncMedia.download>` fetches.

   Three arrived per reel on every one measured, in the upstream's order and at the same width
   and height, told apart only by ``version_type``, the upstream's own enumeration passed
   through as sent (``101``, ``102`` and ``103`` were seen). Which is the better picture is not
   said by the payload, so nothing here sorts them or picks one. ``url`` is signed and expires,
   so a rendition read long ago may no longer download.
   """

   url: str
   width: int
   height: int
   version_type: int


class AudioKind(StrEnum):
   """Where a reel's audio comes from, named by the upstream slot that carried it.

   A reel carried exactly one of the two on every one measured, eleven in all.
   """

   MUSIC = "music_info"
   ORIGINAL_SOUND = "original_sound_info"


@dataclass(frozen=True)
class MediaAudio:
   """The audio a reel plays, as its payload describes it.

   ``audio_id`` is the upstream's id for the track, ``audio_cluster_id`` on a licensed song
   and ``audio_asset_id`` on an original sound. ``title`` and ``artist`` are the text the web
   client shows: a song's title and display artist, or an original sound's title and the
   username of the account that made it. ``artist_id`` is that account's numeric id, which only
   an original sound carries, so it is ``None`` on a song.

   ``should_mute`` is the upstream saying the audio must not play here, and ``is_explicit`` its
   explicit content flag. The audio itself is not a separate download: it is inside the video
   renditions.
   """

   kind: AudioKind
   audio_id: str
   title: str
   artist: str
   is_explicit: bool
   should_mute: bool
   artist_id: str | None = None


@dataclass(frozen=True)
class CarouselChild:
   """One slide of a carousel, with its own kind.

   ``media_type`` is the upstream's enumeration for the slide, ``1`` for a photo and ``2`` for a
   video, and ``product_type`` its own, ``carousel_item`` on every slide measured. ``id`` is
   ``"<pk>_<author id>"`` as on :class:`Post`. A slide has no shortcode of its own.

   ``images`` holds the slide's crops, and on a video slide its cover frames. ``videos`` and
   ``video_duration`` are empty and ``None`` on a photo. Every one of the thirty-one slides
   measured was a photo, so a video slide is mapped by the same rules as a reel but has not been
   seen.
   """

   id: str
   pk: str
   media_type: int
   product_type: str
   original_width: int | None = None
   original_height: int | None = None
   accessibility_caption: str | None = None
   images: tuple[MediaImage, ...] = ()
   videos: tuple[VideoRendition, ...] = ()
   video_duration: float | None = None


@dataclass(frozen=True)
class PostAuthor:
   """The account that posted, as the timeline carries it.

   ``id`` is the numeric account identifier, sent twice as ``pk`` and ``id`` holding the
   identical value on all six measured nodes. It is the same identifier
   :attr:`~dumpstagram.models.Profile.id` carries, so it is what
   :meth:`~dumpstagram.aio.AsyncClient.profile_by_id` takes.

   ``is_following`` and ``is_favorite`` come from the viewer's relationship with this account
   rather than from the account, which is why they live here under viewer-relative names.
   """

   id: str
   username: str
   full_name: str
   is_private: bool
   is_verified: bool
   profile_pic_url: str
   hd_profile_pic_url: str | None = None
   is_following: bool | None = None
   is_favorite: bool | None = None


@dataclass(frozen=True)
class Post:
   """One post on the timeline.

   ``id`` and ``pk`` are two different identifiers here, unlike everywhere else on this
   surface. ``pk`` is the media's own 19 digit number and ``id`` is ``"<pk>_<author id>"``,
   which held on all six measured nodes. Both are carried because a caller passing the wrong
   one to a future capability would get an error rather than a wrong post, and guessing which
   one a surface wants is what this boundary exists to stop.

   ``code`` is the eleven character shortcode that appears in a post's web address.

   ``media_type`` and ``product_type`` are the upstream's own enumerations and are passed
   through as sent. ``1``, ``2`` and ``8`` were seen for the first, a photo, a video and a
   carousel, and ``feed``, ``clips`` and ``carousel_container`` for the second, which is too
   narrow to model as an enum, so a caller comparing them is comparing upstream values
   knowingly.

   ``caption`` is the poster's text, and ``None`` means the upstream sent no caption object at
   all rather than an empty one.

   ``like_count`` and ``comment_count`` are the upstream's numbers, reported rather than
   verified. ``like_and_view_counts_disabled`` says the poster hid them, in which case the
   numbers are still sent and still meaningless.

   ``carousel_media_count`` is the number of slides, and it is ``None`` on a post that is not
   a carousel. ``carousel_children`` holds the slides themselves in the upstream's order, each
   with its own kind, and is empty on a post that is not a carousel.

   ``images`` is every rendition the upstream offered, in its order. See :class:`MediaImage`.
   On a video they are its cover frames.

   ``videos`` holds a video's renditions, see :class:`VideoRendition`, and is empty on anything
   else. ``video_duration`` is its length in seconds, read from the ``mediaPresentationDuration``
   of the DASH manifest the payload carries beside the renditions, because the web payload has no
   duration field of its own. It is ``None`` when the post is not a video.

   ``has_audio`` is the upstream's flag, set on a video and ``None`` on a photo or a carousel,
   which the upstream sends as null. ``audio`` describes the track a reel plays, see
   :class:`MediaAudio`, and is ``None`` on a post that is not a reel.
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
   is_seen: bool
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
class FeedItem:
   """One item on the timeline, which is usually not a post.

   Of fifteen measured items, six were posts, six were explore stories and three were ads.
   That is why the timeline is modelled as items carrying an optional post rather than as a
   list of posts: dropping the rest here would make a page's length unexplainable, and it
   would hide from the caller that most of a feed is not what they asked for.

   ``post`` is set when and only when :attr:`kind` is :attr:`FeedItemKind.POST`. The other
   eight kinds are reported by name and carry no payload, because none of their shapes has
   been measured and modelling an unmeasured shape is the guessing this boundary forbids.
   """

   kind: FeedItemKind
   post: Post | None = None
