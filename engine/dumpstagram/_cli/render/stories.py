"""The stories tray, one account's live stories and one highlight, in both output forms."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from dumpstagram.models import StoryItem, StoryOwner, StoryReel, TrayReel

__all__ = [
   "describe_story_reel",
   "describe_tray",
   "render_story_reel",
   "render_tray",
]


def _time(moment: datetime | None) -> str | None:
   return moment.isoformat() if moment is not None else None


def _describe_owner(owner: StoryOwner) -> dict[str, Any]:
   return {
      "id": owner.id,
      "username": owner.username,
      "profile_pic_url": owner.profile_pic_url,
      "hd_profile_pic_url": owner.hd_profile_pic_url,
      "is_verified": owner.is_verified,
      "is_private": owner.is_private,
   }


def _describe_tray_reel(reel: TrayReel) -> dict[str, Any]:
   return {
      "id": reel.id,
      "reel_type": reel.reel_type,
      "owner": _describe_owner(reel.owner),
      "latest_item_at": _time(reel.latest_item_at),
      "expiring_at": _time(reel.expiring_at),
      "seen_at": _time(reel.seen_at),
      "ranked_position": reel.ranked_position,
      "muted": reel.muted,
      "has_close_friends_items": reel.has_close_friends_items,
   }


def describe_tray(tray: tuple[TrayReel, ...]) -> dict[str, Any]:
   """The tray's rows in its order, and how many. Every key is part of the CLI's contract."""

   return {"reel_count": len(tray), "reels": [_describe_tray_reel(reel) for reel in tray]}


def render_tray(tray: tuple[TrayReel, ...]) -> str:
   """One line per account in the tray's order, then how many."""

   lines = []

   for reel in tray:
      seen = _time(reel.seen_at) or "never"
      lines.append(
         f"{reel.ranked_position}  {reel.owner.id}  {reel.owner.username}  "
         f"latest {reel.latest_item_at.isoformat()}  seen {seen}"
      )

   lines.append(f"reels: {len(tray)}")

   return "\n".join(lines)


def _describe_item(item: StoryItem) -> dict[str, Any]:
   return {
      "id": item.id,
      "pk": item.pk,
      "code": item.code,
      "owner_id": item.owner_id,
      "media_type": item.media_type,
      "product_type": item.product_type,
      "taken_at": _time(item.taken_at),
      "expiring_at": _time(item.expiring_at),
      "original_width": item.original_width,
      "original_height": item.original_height,
      "audience": item.audience,
      "can_reply": item.can_reply,
      "can_reshare": item.can_reshare,
      "is_paid_partnership": item.is_paid_partnership,
      "is_story_edited": item.is_story_edited,
      "has_audio": item.has_audio,
      "video_duration": item.video_duration,
      "images": [
         {"url": image.url, "width": image.width, "height": image.height} for image in item.images
      ],
      "videos": [{"url": video.url, "version_type": video.version_type} for video in item.videos],
      "mentions": [
         {"username": mention.username, "full_name": mention.full_name} for mention in item.mentions
      ],
      "music": [
         {"title": track.title, "artist": track.artist, "should_mute": track.should_mute}
         for track in item.music
      ],
   }


def describe_story_reel(reel: StoryReel | None) -> dict[str, Any]:
   """A reel with every item, or ``reel`` null when the account has no live story."""

   if reel is None:
      return {"reel": None, "item_count": 0}

   return {
      "reel": {
         "id": reel.id,
         "reel_type": reel.reel_type,
         "title": reel.title,
         "cover_url": reel.cover_url,
         "owner": _describe_owner(reel.owner),
         "latest_item_at": _time(reel.latest_item_at),
         "can_reshare": reel.can_reshare,
         "items": [_describe_item(item) for item in reel.items],
      },
      "item_count": len(reel.items),
   }


def render_story_reel(reel: StoryReel | None) -> str:
   """One line per item in the upstream's order, oldest first on the highlight read, then how
   many."""

   if reel is None:
      return "no live story\nitems: 0"

   kinds = {1: "photo", 2: "video"}
   lines = [f"{reel.id}  {reel.owner.username}  {reel.title or ''}".rstrip()]

   for item in reel.items:
      kind = kinds.get(item.media_type, str(item.media_type))
      lines.append(f"{item.taken_at.isoformat()}  {item.pk}  {kind}")

   lines.append(f"items: {len(reel.items)}")

   return "\n".join(lines)
