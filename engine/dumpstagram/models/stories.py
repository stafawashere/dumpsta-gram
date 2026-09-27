"""Typed representations of the stories tray, one account's live stories, and one highlight.

Every field below was observed on the answers ``probes/e2_stories.py`` kept on 2026-09-27, run
``run-2026-09-27-014102``: the stories tray read once with 33 reels, the owner's one highlight
read twice with 18 items, and the owner's own reel, which answered no reel because he had no
live story. So no live story item has been read. A highlight's items are story items, and a
live reel's items are ASSUMED to share their shape, which the first live read will test.

The read queries mark nothing (INFERENCE: a browser sends a separate seen mutation for each item
it shows). Since E2 batch 12 the engine sends that mutation itself, for a reel's or a highlight's
first item after the read under the default behavior, and for any item through
``stories.mark_seen`` (W93, W94).

Nothing here parses. Construction is done by the mappers in ``_private/web/parse/stories.py``,
which read named keys and raise rather than filling a default, so an upstream rename is loud.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from dumpstagram.models.feed import MediaImage

__all__ = [
   "StoryItem",
   "StoryMention",
   "StoryMusic",
   "StoryOwner",
   "StoryReel",
   "StoryVideo",
   "TrayReel",
]


@dataclass(frozen=True)
class StoryOwner:
   """The account a reel belongs to, as much of it as the answer carries.

   ``id`` is the numeric account id, sent as ``pk`` and again as ``id``, identical on every
   reel read. A tray row carries a high resolution picture and neither flag, and a reel read on
   its own carries both flags and no high resolution picture, so each of the three is ``None``
   where the read does not carry it.
   """

   id: str
   username: str
   profile_pic_url: str
   is_verified: bool | None = None
   is_private: bool | None = None
   hd_profile_pic_url: str | None = None


@dataclass(frozen=True)
class StoryVideo:
   """One rendition of a story's video.

   A story's ``video_versions`` entries carried ``url`` and ``type`` and nothing else, on all
   51 read, where a post's carry a width and a height too, so this is not a
   :class:`~dumpstagram.models.VideoRendition` with dimensions guessed into it. ``version_type``
   is the upstream's own enumeration, ``101``, ``102`` and ``103`` on every video read, which
   the payload does not rank. ``url`` is signed and expires.
   """

   url: str
   version_type: int


@dataclass(frozen=True)
class StoryMention:
   """An account a story mentions with a sticker, as the sticker names it.

   The sticker carries the account's ``username`` and ``full_name`` and no account id. Its
   position and size were zero on all four read, so neither is modelled.
   """

   username: str
   full_name: str


@dataclass(frozen=True)
class StoryMusic:
   """A music sticker on a story: the track's title and the artist the story shows.

   ``should_mute`` is the upstream saying the audio must not play here.
   """

   title: str
   artist: str
   should_mute: bool


@dataclass(frozen=True)
class StoryItem:
   """One photo or video in a reel or a highlight.

   ``id`` is ``"<pk>_<owner id>"`` and ``pk`` the item's own number, as on a post. ``code`` is
   the item's shortcode. ``media_type`` is ``1`` for a photo and ``2`` for a video, and
   ``product_type`` was ``story`` on all 18 read. ``taken_at`` is when it was posted and
   ``expiring_at`` when it leaves the reel, 24 hours later on 17 of the 18; an item kept in a
   highlight stays readable there after that time.

   ``images`` are the crops the upstream offered, in its order, and on a video the cover
   frames. ``videos`` and ``video_duration`` are empty and ``None`` on a photo. ``has_audio``
   is ``None`` where the upstream sent null, which it did on the one photo.

   ``audience`` is the upstream's own word for who can see the item, ``besties`` for close
   friends on 2 of the 18, and ``None`` otherwise. ``mentions`` and ``music`` are the item's
   mention and music stickers in the upstream's order, empty when it sent null. Links,
   locations, hashtags, polls, questions, sliders and countdowns were null on every item read,
   so none of them is modelled.
   """

   id: str
   pk: str
   code: str
   owner_id: str
   media_type: int
   product_type: str
   taken_at: datetime
   expiring_at: datetime
   original_width: int
   original_height: int
   can_reply: bool
   can_reshare: bool
   is_paid_partnership: bool
   is_story_edited: bool
   images: tuple[MediaImage, ...] = ()
   videos: tuple[StoryVideo, ...] = ()
   video_duration: float | None = None
   has_audio: bool | None = None
   audience: str | None = None
   mentions: tuple[StoryMention, ...] = ()
   music: tuple[StoryMusic, ...] = ()


@dataclass(frozen=True)
class StoryReel:
   """One account's live stories, or one highlight, with every item in it.

   ``reel_type`` is the upstream's own, ``highlight_reel`` on the highlight read and, INFERENCE
   from the tray, ``user_reel`` on an account's live stories. ``id`` is the highlight's
   ``highlight:<number>`` on a highlight, the same id
   :attr:`Highlight.id <dumpstagram.models.Highlight.id>` carries. ``latest_item_at`` is the
   newest item's ``taken_at``.

   ``title`` and ``cover_url`` are a highlight's name and its cover picture. A live reel has not
   been read, so each is ``None`` where the reel does not carry it.
   """

   id: str
   reel_type: str
   owner: StoryOwner
   latest_item_at: datetime
   can_reshare: bool
   items: tuple[StoryItem, ...]
   title: str | None = None
   cover_url: str | None = None


@dataclass(frozen=True)
class TrayReel:
   """One account in the stories tray at the top of the home page, without its items.

   The tray lists whose stories there are and says nothing of what is in them, so reading an
   account's items is :meth:`~dumpstagram.namespaces.stories.AsyncStories.reel` with
   ``owner.id``. ``id`` was the owner's account id and ``reel_type`` ``user_reel`` on all 33
   rows read.

   ``latest_item_at`` is when the newest item was posted and ``expiring_at`` when that item
   leaves, 24 hours later on every row. ``seen_at`` is the upstream's ``seen``, ``None`` where
   it sent 0, which 23 of the 33 did; INFERENCE, the tray has an item the viewer has not seen
   when ``seen_at`` is ``None`` or earlier than ``latest_item_at``. ``ranked_position`` is the
   row's place in the tray, from 1. ``has_close_friends_items`` is the upstream's
   ``has_besties_media``.
   """

   id: str
   reel_type: str
   owner: StoryOwner
   latest_item_at: datetime
   expiring_at: datetime
   ranked_position: int
   muted: bool
   has_close_friends_items: bool
   seen_at: datetime | None = None
