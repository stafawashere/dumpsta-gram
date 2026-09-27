"""Typed representations of the viewer's own account: the follow requests waiting on it and its
activity feed.

Every field below was observed on the answers ``probes/e2_own_account.py`` kept on 2026-09-27,
run ``run-2026-09-27-014102``: the pending follow requests read twice with one account each,
and the activity feed read twice with no new item and 69 earlier ones. No new or priority item
has been read, so those two lists are ASSUMED to carry the earlier items' shape, which the first
read that has one will test.

Reading either through the engine marks nothing seen (W73, W74).

Nothing here parses. Construction is done by the mappers in ``_private/web/parse/account.py``,
which read named keys and raise rather than filling a default, so an upstream rename is loud.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from dumpstagram.models.profiles import ProfileSummary

__all__ = [
   "ActivityCounts",
   "ActivityFeed",
   "ActivityItem",
   "ActivityLink",
   "ActivityMedia",
   "ActivitySection",
   "FollowRequests",
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
