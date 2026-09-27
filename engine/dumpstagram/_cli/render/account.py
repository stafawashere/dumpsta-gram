"""The viewer's pending follow requests and activity feed, in both output forms."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from dumpstagram._cli.render.profiles import describe_profile_summary
from dumpstagram.models import ActivityFeed, ActivityItem, FollowRequests

__all__ = [
   "describe_activity_feed",
   "describe_follow_requests",
   "render_activity_feed",
   "render_follow_requests",
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
