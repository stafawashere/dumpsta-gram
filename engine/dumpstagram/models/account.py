"""Typed representations of the viewer's own account: the follow requests waiting on it, its
activity feed, what it saved, its close friends list and the accounts it blocked.

Every field below was observed on the answers ``probes/e2_own_account.py`` kept on 2026-09-27,
run ``run-2026-09-27-014102``: the pending follow requests read twice with one account each,
and the activity feed read twice with no new item and 69 earlier ones. No new or priority item
has been read, so those two lists are ASSUMED to carry the earlier items' shape, which the first
read that has one will test.

Reading either through the engine marks nothing seen (W73, W74).

The saved posts, the saved collections and the close friends list were read in E2 batch 11c from
the answers ``probes/e2_capture_replays.py`` kept on 2026-09-27, run ``run-2026-09-27-151121``,
two of each, and the browser capture of ``run-2026-09-27-131354`` (W105 to W108). The blocked list
was read in E2 batch 11d from the two answers ``probes/e2_blocked_list_replay.py`` kept on
2026-09-27 and the two browser loads of ``run-2026-09-27-135628`` (W110).

Nothing here parses. Construction is done by the mappers in ``_private/web/parse/account.py``,
which read named keys and raise rather than filling a default, so an upstream rename is loud.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

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

__all__ = [
   "ActivityCounts",
   "ActivityFeed",
   "ActivityItem",
   "ActivityLink",
   "ActivityMedia",
   "ActivitySection",
   "BlockedAccount",
   "CollectionCover",
   "FollowRequests",
   "SavedCollection",
   "SavedCollectionKind",
   "SavedCollections",
   "SavedPost",
   "SavedPosts",
]


@dataclass(frozen=True)
class FollowRequests:
   """The accounts asking to follow the viewer, the first page of them.

   ``has_more`` is true when the answer carries a ``next_max_id``, which says the list goes on
   past this page. Both answers read carried it null with one account on the page, so no next
   page has been read and nothing here reads one.
   """

   accounts: tuple[ProfileSummary, ...]
   has_more: bool


@dataclass(frozen=True)
class ActivityCounts:
   """The upstream's unread counters for the activity feed, one per kind, as sent.

   All fifteen were zero on both answers read, so which event moves which counter is not
   observed. ``activity_feed_dot_badge`` and ``activity_feed_dot_badge_only`` are ASSUMED to
   drive the dot on the notifications icon, by their names.
   """

   likes: int
   comments: int
   comment_likes: int
   relationships: int
   requests: int
   usertags: int
   photos_of_you: int
   new_posts: int
   media_to_approve: int
   fundraiser: int
   promotional: int
   shopping_notification: int
   campaign_notification: int
   activity_feed_dot_badge: int
   activity_feed_dot_badge_only: int


@dataclass(frozen=True)
class ActivityLink:
   """A span of an item's ``text`` that names an account, as the upstream marks it.

   ``text[start:end]`` is ``username`` on every link read, 116 of them, and ``kind`` was
   ``user`` on every one, with ``id`` the account's numeric id.
   """

   start: int
   end: int
   kind: str
   id: str
   username: str


@dataclass(frozen=True)
class ActivityMedia:
   """A post or story an item refers to, as its thumbnail shows it.

   ``id`` is the upstream's ``<pk>_<owner id>`` form and ``image_url`` a signed thumbnail that
   expires. An item carried one entry or none, never more, on all 69 read.
   """

   id: str
   shortcode: str
   image_url: str


@dataclass(frozen=True)
class ActivityItem:
   """One line of the activity feed.

   ``kind`` is the upstream's own name for it, such as ``story_like``, ``post_like``,
   ``user_followed``, ``comment_like`` or ``private_user_follow_request``, and ``story_type`` its
   number for the same thing; nine kinds were read, each with one number. ``text`` is the line
   as the website shows it, in English, and ``links`` the accounts it names inside it. The text
   can quote a comment, so it is content.

   ``account_id``, ``account_username`` and ``account_pic_url`` are the account the line is
   mainly about, carried on 67 of 69 items, and ``second_account_id`` and
   ``second_account_pic_url`` a second one, carried on 50; each is ``None`` where the item does
   not carry it. ``follow_account`` is the account a follow button beside the line acts on, with
   the viewer's relationship to it, carried on 9. ``comment_id`` was carried on one item, a
   mention in a comment. ``destination`` is the upstream's own link for opening the item, in the
   app's route form rather than a URL, carried on 68.
   """

   id: str
   kind: str
   story_type: int
   created_at: datetime
   text: str
   links: tuple[ActivityLink, ...]
   media: tuple[ActivityMedia, ...]
   account_id: str | None = None
   account_username: str | None = None
   account_pic_url: str | None = None
   second_account_id: str | None = None
   second_account_pic_url: str | None = None
   follow_account: ProfileSummary | None = None
   comment_id: str | None = None
   destination: str | None = None


@dataclass(frozen=True)
class ActivitySection:
   """A heading the website puts above part of the feed, such as ``Today`` or ``Earlier``.

   ``first_index`` is where the section starts in :attr:`ActivityFeed.items`. INFERENCE: with
   no new item read, an index into the earlier items alone cannot be told apart from one into
   the whole feed.
   """

   title: str
   first_index: int


@dataclass(frozen=True)
class ActivityFeed:
   """The activity feed as one read of it answers.

   ``new_items`` are the lines the viewer has not seen and ``earlier_items`` the rest, each
   newest first, which all 69 earlier items read were. ``priority_items`` is a third list the
   answer carries, empty on both reads. ``items`` is the three joined, priority, then new, then
   earlier, an ASSUMPTION about the page's order, since only earlier items have been read.

   ``is_last_page`` is the upstream's own flag, true on both reads. Nothing reads a next page,
   because none has been observed, so where it is false the feed holds only the first page.
   ``last_checked_at`` is when the upstream last recorded the viewer checking the feed.
   """

   new_items: tuple[ActivityItem, ...]
   earlier_items: tuple[ActivityItem, ...]
   priority_items: tuple[ActivityItem, ...]
   counts: ActivityCounts
   sections: tuple[ActivitySection, ...]
   last_checked_at: datetime
   is_last_page: bool

   @property
   def items(self) -> tuple[ActivityItem, ...]:
      return self.priority_items + self.new_items + self.earlier_items


@dataclass(frozen=True)
class SavedPost:
   """One post of the viewer's saved "All posts" view, as that view carries it.

   The view answers with the same REST media object the explore grid does, but without
   ``comment_count`` on any of the 42 items read, so it is its own model rather than a
   :class:`~dumpstagram.models.Post` with a guessed count, and it carries no ``is_seen`` either.
   Every other field means what it means on ``Post``.
   :meth:`~dumpstagram.namespaces.media.AsyncMedia.by_code` with its ``code`` reads the whole
   post, the comment count included.

   ``like_and_view_counts_disabled`` is ``None`` where the item does not carry it, which the one
   saved advertisement read did not (``product_type`` ``ad``, 1 of 21 on each answer). Every item
   read was a video, so the photo and carousel fields follow the explore grid's REST reading
   (W77) without having been seen here.
   """

   id: str
   pk: str
   code: str
   taken_at: datetime
   author: PostAuthor
   media_type: int
   product_type: str
   like_count: int
   has_liked: bool
   caption: str | None = None
   accessibility_caption: str | None = None
   original_width: int | None = None
   original_height: int | None = None
   carousel_media_count: int | None = None
   images: tuple[MediaImage, ...] = ()
   is_paid_partnership: bool = False
   like_and_view_counts_disabled: bool | None = None
   videos: tuple[VideoRendition, ...] = ()
   video_duration: float | None = None
   has_audio: bool | None = None
   audio: MediaAudio | None = None
   carousel_children: tuple[CarouselChild, ...] = ()
   location: Location | None = None
   user_tags: tuple[UserTag, ...] | None = None
   collaborators: tuple[ProfileSummary, ...] | None = None


@dataclass(frozen=True)
class SavedPosts:
   """The first page of the viewer's saved "All posts" view, in the upstream's order.

   ``has_more`` is the upstream's ``more_available``, true on both answers read with 21 posts
   each. No later page has been read, so nothing here hands out a cursor (W105).
   """

   posts: tuple[SavedPost, ...]
   has_more: bool


class SavedCollectionKind(StrEnum):
   """What one row of the saved tab is, named by the upstream's ``__typename``.

   The two automatic collections were read. A collection the viewer made and named was not,
   since the account read had none, so its type name is unknown and any row of an unread type is
   :attr:`OTHER`, carrying only what every row carried (W106).
   """

   ALL_POSTS = "IGAllMediaAutoCollection"
   AUDIO = "XDTAudioAutoCollection"
   OTHER = "other"


@dataclass(frozen=True)
class CollectionCover:
   """One picture a saved collection shows as its cover.

   A post's cover carries its ``media_id``, ``"<pk>_<author id>"``, and every rendition's URL in
   the upstream's order; the renditions carry no size, so none is picked here. An audio cover
   carries one thumbnail URL and no ``media_id``.
   """

   media_id: str | None
   image_urls: tuple[str, ...]


@dataclass(frozen=True)
class SavedCollection:
   """One row of the viewer's saved tab.

   ``id`` is the upstream's ``collection_id``, which on the two automatic collections is the
   constant ``ALL_MEDIA_AUTO_COLLECTION`` or ``AUDIO_AUTO_COLLECTION`` rather than a number.
   ``media_count`` is the number of posts the "All posts" collection holds; the audio
   collection sent null, so it is ``None`` there.
   """

   id: str
   name: str
   kind: SavedCollectionKind
   media_count: int | None = None
   covers: tuple[CollectionCover, ...] = ()


@dataclass(frozen=True)
class SavedCollections:
   """The first page of the viewer's saved tab, in the upstream's order.

   ``has_more`` is the page's own ``has_next_page``, false on both answers read. No query that
   reads past the first page has been observed, so nothing here hands out a cursor.
   """

   collections: tuple[SavedCollection, ...]
   has_more: bool


@dataclass(frozen=True)
class BlockedAccount:
   """One account the viewer has blocked, as the blocked accounts settings screen lists it.

   ``id`` is the numeric account id, sent as a string, and ``username``, ``is_verified`` and
   ``profile_pic_url`` are the row's own.

   ``secondary_text`` is the grey line the screen shows under the username, and it is not
   always a name. On the 11 rows of 52 read with ``is_auto_blocked`` false it differed on every
   row, and on the one row whose account's full name another read carried, it was that full name;
   one of the 11 was empty. On the 41 rows with ``is_auto_blocked`` true it was one interface line
   saying the block includes other accounts the person may have or create, the same on every row.
   So it is kept as the screen's text and not read as a full name.

   ``is_auto_blocked`` is the row's own flag. That it marks a block extended to the person's
   other accounts, present and future, is INFERENCE from the line the screen shows beside it.
   """

   id: str
   username: str
   secondary_text: str
   is_verified: bool
   profile_pic_url: str
   is_auto_blocked: bool
