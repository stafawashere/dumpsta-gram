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

The location, the tagged accounts and the collaborators were added on 2026-09-27 for E2 batch 4,
from the 37 distinct posts of the home timeline and grid captures the E2 probes kept that day,
the one post read by its media pk, and the pseudonymised post query items of E1 item 6.

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

from dumpstagram.models.profiles import ProfileSummary

__all__ = [
   "AudioKind",
   "CarouselChild",
   "FeedItem",
   "FeedItemKind",
   "Location",
   "MediaAudio",
   "MediaImage",
   "Post",
   "PostAuthor",
   "TaggedPlace",
   "UserTag",
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
class UserTag:
   """One account tagged in a post or a slide, and where on the picture the tag sits.

   ``account`` is the tagged account as a list row reads it. Every tag read on 2026-09-27 carried
   its ``id``, ``username``, ``full_name``, ``is_verified`` and ``profile_pic_url``, and
   ``account.is_private`` is ``None`` where the tag does not say, which no post's tag did. A tag
   carries no relationship, so ``account.friendship_status`` is ``None``.

   ``position`` is the tag's ``x`` and ``y`` as fractions of the picture's width and height, the
   upstream's two numbers in its order. It is ``None`` where the read does not carry it, which the
   post read by media pk does not, on its post or on its slides.
   """

   account: ProfileSummary
   position: tuple[float, float] | None = None


@dataclass(frozen=True)
class Location:
   """The place a post is tagged at.

   ``id`` is the upstream's ``pk`` for the place, which arrived as a string on the home timeline
   and as a number on a profile's grid and in the post query, and is carried as a string either
   way. ``lat`` and ``lng`` are its coordinates. All four were present on all 39 locations the
   E2 probes kept on 2026-09-27. Some locations outside posts carried an address and a city as
   well; no post's location did, so neither is modelled.
   """

   id: str
   name: str
   lat: float
   lng: float


@dataclass(frozen=True)
class TaggedPlace:
   """The place a post is tagged at, as far as every read names it: its ``pk`` as ``id``, what
   :meth:`~dumpstagram.namespaces.feeds.AsyncFeeds.place` takes, and its ``name``.

   Every location read carried both. The reels feed sent a location with nothing else on all 3
   of its located reels read on 2026-09-27, so there :attr:`Post.location` is ``None`` and this is
   the post's place (W120).
   """

   id: str
   name: str


@dataclass(frozen=True)
class CarouselChild:
   """One slide of a carousel, with its own kind.

   ``media_type`` is the upstream's enumeration for the slide, ``1`` for a photo and ``2`` for a
   video, and ``product_type`` its own, ``carousel_item`` on every slide measured. ``id`` is
   ``"<pk>_<author id>"`` as on :class:`Post`. A slide has no shortcode of its own.

   ``user_tags`` are the accounts tagged on this slide, the same rule as :attr:`Post.user_tags`.

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
   user_tags: tuple[UserTag, ...] | None = None


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

   ``is_seen`` is whether the viewer has seen the post in the home timeline. A profile's grid
   returns the same model, and there the upstream sends null for it on every post, which reads
   as False and carries no information.

   ``location`` is the place the post is tagged at, ``None`` when it has none. ``user_tags`` are
   the accounts tagged on the post itself, in the upstream's order; a tag on one slide is on that
   slide's :attr:`CarouselChild.user_tags`. ``collaborators`` are the accounts that share the
   post with its author, each with the viewer's relationship to it, and the author is not among
   them. Each of the two tuples is empty when the upstream sends null or an empty list, and
   ``None`` only when the read does not carry the field at all, so ``None`` means unknown rather
   than none. Collaborators were seen on one of the 37 distinct timeline and grid posts read on
   2026-09-27.

   ``audio_id`` is the id of the track's audio page, the one
   :meth:`~dumpstagram.namespaces.feeds.AsyncFeeds.audio` takes: a song's ``audio_cluster_id`` or
   an original sound's ``audio_asset_id``. It is read wherever the node names its track, including
   a reel whose ``audio`` is ``None`` because the read leaves out a flag :class:`MediaAudio`
   requires, and it is ``None`` on a post that names no track (W118).

   ``tagged_place`` is the place's id and name wherever the node names a place, and ``None`` where
   it names none. ``location`` is the same place with its coordinates, and it is ``None`` also
   where the read sends the place without them, which the reels feed does (W120).
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
   location: Location | None = None
   user_tags: tuple[UserTag, ...] | None = None
   collaborators: tuple[ProfileSummary, ...] | None = None
   audio_id: str | None = None
   tagged_place: TaggedPlace | None = None


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
