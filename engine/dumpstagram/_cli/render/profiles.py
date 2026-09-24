"""A profile and the viewer's relationship to it, in both output forms."""

from __future__ import annotations

from typing import Any

from dumpstagram.models import (
   FriendshipStatus,
   Profile,
)

__all__ = [
   "describe_friendship_status",
   "describe_profile",
   "render_profile",
]


def describe_profile(profile: Profile) -> dict[str, Any]:
   """The JSON form of one profile. Every key here is part of the CLI's contract."""

   return {
      "id": profile.id,
      "username": profile.username,
      "full_name": profile.full_name,
      "biography": profile.biography,
      "is_private": profile.is_private,
      "is_verified": profile.is_verified,
      "follower_count": profile.follower_count,
      "following_count": profile.following_count,
      "media_count": profile.media_count,
      "total_clips_count": profile.total_clips_count,
      "profile_pic_url": profile.profile_pic_url,
      "hd_profile_pic_url": profile.hd_profile_pic_url,
      "external_url": profile.external_url,
      "external_lynx_url": profile.external_lynx_url,
      "bio_links": [
         {
            "link_id": link.link_id,
            "url": link.url,
            "lynx_url": link.lynx_url,
            "title": link.title,
            "link_type": link.link_type,
            "is_pinned": link.is_pinned,
         }
         for link in profile.bio_links
      ],
      "category": profile.category,
      "account_type": profile.account_type,
      "is_business": profile.is_business,
      "is_professional_account": profile.is_professional_account,
      "is_memorialized": profile.is_memorialized,
      "is_unpublished": profile.is_unpublished,
      "is_embeds_disabled": profile.is_embeds_disabled,
      "has_profile_pic": profile.has_profile_pic,
      "has_story_archive": profile.has_story_archive,
      "friendship_status": describe_friendship_status(profile.friendship_status),
   }


def describe_friendship_status(status: FriendshipStatus | None) -> dict[str, bool] | None:
   """The viewer's relationship to the account, null on the viewer's own profile."""

   if status is None:
      return None

   return {
      "following": status.following,
      "followed_by": status.followed_by,
      "outgoing_request": status.outgoing_request,
      "incoming_request": status.incoming_request,
      "blocking": status.blocking,
      "muting": status.muting,
      "is_muting_reel": status.is_muting_reel,
      "is_restricted": status.is_restricted,
      "is_bestie": status.is_bestie,
      "is_feed_favorite": status.is_feed_favorite,
   }


def render_profile(profile: Profile) -> str:
   """The human form: the identity, the counts, then the bio and the links.

   The biography is printed as the owner wrote it, newlines included, which is why it comes
   last apart from the links rather than in the middle of the field list.
   """

   lines = [
      f"{profile.username}  ({profile.id})",
      f"name: {profile.full_name}",
      f"private: {profile.is_private}  verified: {profile.is_verified}",
      f"followers: {profile.follower_count}  following: {profile.following_count}  "
      f"posts: {profile.media_count}  clips: {profile.total_clips_count}",
   ]

   status = profile.friendship_status

   if status is not None:
      lines.append(
         f"you follow: {status.following}  requested: {status.outgoing_request}  "
         f"follows you: {status.followed_by}"
      )

   if profile.category:
      lines.append(f"category: {profile.category}")

   if profile.external_url:
      lines.append(f"website: {profile.external_url}")

   for link in profile.bio_links:
      lines.append(f"link: {link.url}  ({link.title or link.link_type})")

   if profile.biography:
      lines.append("")
      lines.append(profile.biography)

   return "\n".join(lines)
