"""A profile and the viewer's relationship to it, a profile's posts grid, its highlights tray, and
the suggested accounts, in both output forms."""

from __future__ import annotations

from typing import Any

from dumpstagram._cli.render.media import describe_post
from dumpstagram.models import (
   FriendshipStatus,
   HighlightTray,
   ListFriendshipStatus,
   Page,
   Post,
   Profile,
   ProfileSummary,
   SuggestedAccount,
)

__all__ = [
   "describe_friendship_status",
   "describe_grid_pages",
   "describe_highlight_tray",
   "describe_profile",
   "describe_profile_summary",
   "describe_suggested_account",
   "render_grid",
   "render_highlight_tray",
   "render_profile",
   "render_profile_summaries",
   "render_suggested_accounts",
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


def describe_grid_pages(pages: list[Page[Post]]) -> dict[str, Any]:
   """What was read, with the last page's own terminator and cursor, never a count of posts."""

   last = pages[-1] if pages else None

   return {
      "pages_read": len(pages),
      "post_count": sum(len(page.items) for page in pages),
      "more_available": last.has_next_page if last is not None else False,
      "end_cursor": last.end_cursor if last is not None else None,
      "posts": [describe_post(post) for page in pages for post in page.items],
   }


def render_grid(pages: list[Page[Post]]) -> str:
   """One line per post in the grid's order, then the trailer."""

   lines = []

   for page in pages:
      for post in page.items:
         caption = post.caption.splitlines()[0] if post.caption else ""
         lines.append(
            f"{post.taken_at.isoformat()}  {post.code}  likes {post.like_count}  "
            f"comments {post.comment_count}  {caption}"
         )

   trailer = describe_grid_pages(pages)
   lines.append(
      f"pages_read: {trailer['pages_read']}  posts: {trailer['post_count']}  "
      f"more_available: {trailer['more_available']}"
   )

   if trailer["end_cursor"]:
      lines.append(f"next_cursor: {trailer['end_cursor']}")

   return "\n".join(lines)


def describe_highlight_tray(tray: HighlightTray) -> dict[str, Any]:
   return {
      "highlights": [
         {
            "id": highlight.id,
            "title": highlight.title,
            "cover_url": highlight.cover_url,
            "owner_id": highlight.owner_id,
            "owner_username": highlight.owner_username,
         }
         for highlight in tray.highlights
      ],
      "has_more": tray.has_more,
   }


def render_highlight_tray(tray: HighlightTray) -> str:
   """One line per highlight, then how many, marked when the tray has more than its first page."""

   lines = [f"{highlight.id}  {highlight.title}" for highlight in tray.highlights]
   more = "  more_available: True" if tray.has_more else ""
   lines.append(f"highlights: {len(tray.highlights)}{more}")

   return "\n".join(lines)


def _describe_list_friendship(status: ListFriendshipStatus | None) -> dict[str, Any] | None:
   if status is None:
      return None

   return {
      "following": status.following,
      "followed_by": status.followed_by,
      "outgoing_request": status.outgoing_request,
      "incoming_request": status.incoming_request,
      "blocking": status.blocking,
      "is_restricted": status.is_restricted,
      "is_bestie": status.is_bestie,
      "is_feed_favorite": status.is_feed_favorite,
   }


def describe_profile_summary(summary: ProfileSummary) -> dict[str, Any]:
   """The JSON form of one account row. Every key here is part of the CLI's contract."""

   return {
      "id": summary.id,
      "username": summary.username,
      "full_name": summary.full_name,
      "is_verified": summary.is_verified,
      "is_private": summary.is_private,
      "profile_pic_url": summary.profile_pic_url,
      "hd_profile_pic_url": summary.hd_profile_pic_url,
      "friendship_status": _describe_list_friendship(summary.friendship_status),
   }


def describe_suggested_account(suggestion: SuggestedAccount) -> dict[str, Any]:
   return {"account": describe_profile_summary(suggestion.account), "reason": suggestion.reason}


def _summary_line(summary: ProfileSummary) -> str:
   status = summary.friendship_status
   following = status.following if status is not None else None

   return f"{summary.id}  {summary.username}  {summary.full_name}  you follow: {following}"


def render_profile_summaries(summaries: tuple[ProfileSummary, ...]) -> str:
   """One line per account in the upstream's order, then how many."""

   lines = [_summary_line(summary) for summary in summaries]
   lines.append(f"accounts: {len(summaries)}")

   return "\n".join(lines)


def render_suggested_accounts(suggestions: tuple[SuggestedAccount, ...]) -> str:
   """One entry per account with the reason the website shows under it, then how many."""

   lines = [
      f"{_summary_line(suggestion.account)}\n   {suggestion.reason}" for suggestion in suggestions
   ]
   lines.append(f"accounts: {len(suggestions)}")

   return "\n".join(lines)
