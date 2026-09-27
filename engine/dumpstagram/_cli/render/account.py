"""The viewer's pending follow requests, activity feed, saved posts and collections, close
friends list and blocked accounts list, in both output forms."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from dumpstagram._cli.render.media import (
   _describe_collaborators,
   _describe_location,
   _describe_user_tags,
)
from dumpstagram._cli.render.profiles import describe_profile_summary
from dumpstagram.models import (
   ActivityFeed,
   ActivityItem,
   BlockedAccount,
   FollowRequests,
   ProfileSummary,
   SavedCollections,
   SavedPost,
   SavedPosts,
)

__all__ = [
   "describe_activity_feed",
   "describe_blocked_accounts",
   "describe_close_friends",
   "describe_follow_requests",
   "describe_saved_collections",
   "describe_saved_posts",
   "render_activity_feed",
   "render_blocked_accounts",
   "render_close_friends",
   "render_follow_requests",
   "render_saved_collections",
   "render_saved_posts",
]


def describe_follow_requests(requests: FollowRequests) -> dict[str, Any]:
   """The accounts in the upstream's order, how many, and whether more exist. Every key is part
   of the CLI's contract."""

   return {
      "account_count": len(requests.accounts),
      "more_available": requests.has_more,
      "accounts": [describe_profile_summary(account) for account in requests.accounts],
   }


def render_follow_requests(requests: FollowRequests) -> str:
   """One line per account in the upstream's order, then how many."""

   lines = [
      f"{account.id}  {account.username}  {account.full_name}".rstrip()
      for account in requests.accounts
   ]
   lines.append(f"accounts: {len(requests.accounts)}  more_available: {requests.has_more}")

   return "\n".join(lines)


def _describe_item(item: ActivityItem) -> dict[str, Any]:
   follow_account = item.follow_account

   return {
      "id": item.id,
      "kind": item.kind,
      "story_type": item.story_type,
      "created_at": item.created_at.isoformat(),
      "text": item.text,
      "links": [
         {
            "start": link.start,
            "end": link.end,
            "kind": link.kind,
            "id": link.id,
            "username": link.username,
         }
         for link in item.links
      ],
      "media": [
         {"id": entry.id, "shortcode": entry.shortcode, "image_url": entry.image_url}
         for entry in item.media
      ],
      "account_id": item.account_id,
      "account_username": item.account_username,
      "account_pic_url": item.account_pic_url,
      "second_account_id": item.second_account_id,
      "second_account_pic_url": item.second_account_pic_url,
      "follow_account": (
         describe_profile_summary(follow_account) if follow_account is not None else None
      ),
      "comment_id": item.comment_id,
      "destination": item.destination,
   }


def describe_activity_feed(feed: ActivityFeed) -> dict[str, Any]:
   """Each list in the upstream's order, with the counters, the sections and the last page flag.
   Every key is part of the CLI's contract."""

   return {
      "new_count": len(feed.new_items),
      "earlier_count": len(feed.earlier_items),
      "priority_count": len(feed.priority_items),
      "is_last_page": feed.is_last_page,
      "last_checked_at": feed.last_checked_at.isoformat(),
      "counts": asdict(feed.counts),
      "sections": [
         {"title": section.title, "first_index": section.first_index} for section in feed.sections
      ],
      "new_items": [_describe_item(item) for item in feed.new_items],
      "earlier_items": [_describe_item(item) for item in feed.earlier_items],
      "priority_items": [_describe_item(item) for item in feed.priority_items],
   }


def render_activity_feed(feed: ActivityFeed) -> str:
   """One line per item in the order ``ActivityFeed.items`` joins them, then how many of each
   and the last page flag."""

   lines = [f"{item.created_at.isoformat()}  {item.kind}  {item.text}" for item in feed.items]
   lines.append(
      f"new: {len(feed.new_items)}  earlier: {len(feed.earlier_items)}  "
      f"priority: {len(feed.priority_items)}  last_page: {feed.is_last_page}"
   )

   return "\n".join(lines)


def describe_saved_post(post: SavedPost) -> dict[str, Any]:
   """The JSON form of one saved post, the keys of a post without ``comment_count`` and
   ``is_seen``, which the saved view does not carry. Every key is part of the CLI's contract."""

   return {
      "id": post.id,
      "pk": post.pk,
      "code": post.code,
      "taken_at": post.taken_at.isoformat(),
      "author": {
         "id": post.author.id,
         "username": post.author.username,
         "full_name": post.author.full_name,
         "is_private": post.author.is_private,
         "is_verified": post.author.is_verified,
         "profile_pic_url": post.author.profile_pic_url,
         "hd_profile_pic_url": post.author.hd_profile_pic_url,
         "is_following": post.author.is_following,
         "is_favorite": post.author.is_favorite,
      },
      "media_type": post.media_type,
      "product_type": post.product_type,
      "like_count": post.like_count,
      "has_liked": post.has_liked,
      "caption": post.caption,
      "accessibility_caption": post.accessibility_caption,
      "original_width": post.original_width,
      "original_height": post.original_height,
      "carousel_media_count": post.carousel_media_count,
      "images": [
         {"url": image.url, "width": image.width, "height": image.height} for image in post.images
      ],
      "is_paid_partnership": post.is_paid_partnership,
      "like_and_view_counts_disabled": post.like_and_view_counts_disabled,
      "location": _describe_location(post.location),
      "user_tags": _describe_user_tags(post.user_tags),
      "collaborators": _describe_collaborators(post.collaborators),
   }


def describe_saved_posts(saved: SavedPosts) -> dict[str, Any]:
   """The posts in the upstream's order, how many, and whether more exist. Every key is part of
   the CLI's contract."""

   return {
      "post_count": len(saved.posts),
      "more_available": saved.has_more,
      "posts": [describe_saved_post(post) for post in saved.posts],
   }


def render_saved_posts(saved: SavedPosts) -> str:
   """One line per post in the upstream's order, its author first, then the trailer."""

   lines = []

   for post in saved.posts:
      caption = post.caption.splitlines()[0] if post.caption else ""
      lines.append(
         f"{post.code}  {post.author.username}  {post.product_type}  likes {post.like_count}  "
         f"{caption}".rstrip()
      )

   lines.append(f"posts: {len(saved.posts)}  more_available: {saved.has_more}")

   return "\n".join(lines)


def describe_saved_collections(saved: SavedCollections) -> dict[str, Any]:
   """The collections in the upstream's order and whether more exist. Every key is part of the
   CLI's contract."""

   return {
      "collection_count": len(saved.collections),
      "more_available": saved.has_more,
      "collections": [
         {
            "id": collection.id,
            "name": collection.name,
            "kind": collection.kind.name.lower(),
            "media_count": collection.media_count,
            "covers": [
               {"media_id": cover.media_id, "image_urls": list(cover.image_urls)}
               for cover in collection.covers
            ],
         }
         for collection in saved.collections
      ],
   }


def render_saved_collections(saved: SavedCollections) -> str:
   """One line per collection in the upstream's order, then the trailer."""

   lines = [
      f"{collection.id}  {collection.name}  {collection.kind.name.lower()}  "
      f"posts {collection.media_count}"
      for collection in saved.collections
   ]
   lines.append(f"collections: {len(saved.collections)}  more_available: {saved.has_more}")

   return "\n".join(lines)


def describe_close_friends(accounts: tuple[ProfileSummary, ...]) -> dict[str, Any]:
   """The close friends in the settings screen's order and how many. Every key is part of the
   CLI's contract."""

   return {
      "account_count": len(accounts),
      "accounts": [describe_profile_summary(account) for account in accounts],
   }


def render_close_friends(accounts: tuple[ProfileSummary, ...]) -> str:
   """One line per account in the settings screen's order, then how many."""

   lines = [
      f"{account.id}  {account.username}  {account.full_name}".rstrip() for account in accounts
   ]
   lines.append(f"close friends: {len(accounts)}")

   return "\n".join(lines)


def describe_blocked_accounts(blocked: tuple[BlockedAccount, ...]) -> dict[str, Any]:
   """The blocked accounts in the settings screen's order and how many. Every key is part of the
   CLI's contract."""

   return {
      "account_count": len(blocked),
      "accounts": [
         {
            "id": entry.id,
            "username": entry.username,
            "secondary_text": entry.secondary_text,
            "is_verified": entry.is_verified,
            "profile_pic_url": entry.profile_pic_url,
            "is_auto_blocked": entry.is_auto_blocked,
         }
         for entry in blocked
      ],
   }


def render_blocked_accounts(blocked: tuple[BlockedAccount, ...]) -> str:
   """One line per account in the settings screen's order, ``auto`` after one whose block was
   extended automatically, then how many. The secondary text is left out of this form, since on
   an automatic row it is the screen's own line and not the account's."""

   lines = []

   for entry in blocked:
      marker = "  auto" if entry.is_auto_blocked else ""
      lines.append(f"{entry.id}  {entry.username}{marker}")

   lines.append(f"blocked: {len(blocked)}")

   return "\n".join(lines)
