"""Turning models into the two output forms the CLI offers.

Human text is for a person reading one thread. JSON is the harness form, and it is a
contract: a key that moves breaks whatever scripts this command. Both forms are built from
the typed models, never from an upstream payload, because the CLI sits above the boundary
that stops upstream churn.

No renderer prints a credential. The session summary reports what `Session.__repr__` reports
and nothing more, which is the account id, the token presence and the flags.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dumpstagram.models import Message, Page, Profile
from dumpstagram.session import Session

__all__ = [
   "describe_message",
   "describe_pages",
   "describe_profile",
   "describe_session",
   "render_messages",
   "render_profile",
   "render_session",
]


def describe_session(session: Session, path: Path) -> dict[str, Any]:
   """The session summary both output forms are built from."""

   return {
      "session_path": str(path),
      "ds_user_id": session.ds_user_id,
      "app_id": session.app_id,
      "bootstrapped": session.fb_dtsg is not None and session.lsd is not None,
      "checkpoint_active": session.checkpoint_active,
      "proxied": session.proxy is not None,
      "requests_spent": 0,
   }


def render_session(summary: Mapping[str, Any]) -> str:
   """The human form of a session summary, one field per line."""

   return "\n".join(f"{key}: {summary[key]}" for key in summary)


def describe_message(message: Message) -> dict[str, Any]:
   return {
      "id": message.id,
      "thread_fbid": message.thread_fbid,
      "sender_fbid": message.sender.fbid,
      "sender_igid": message.sender.igid,
      "sender_name": message.sender.name,
      "sent_at": message.sent_at.isoformat(),
      "text": message.text,
      "content_type": message.content_type,
      "reactions": [
         {"emoji": reaction.emoji, "sender_fbid": reaction.sender_fbid}
         for reaction in message.reactions
      ],
      "replied_to_message_id": message.replied_to_message_id,
      "is_forwarded": message.is_forwarded,
      "is_pinned": message.is_pinned,
      "is_ai_generated": message.is_ai_generated,
   }


def describe_pages(pages: list[Page[Message]]) -> dict[str, Any]:
   """What was read, including the terminator, which is the only thing that says there is more.

   ``more_available`` comes from the last page's own `has_next_page`, never from the number of
   messages that arrived. A short page is not the end of a thread.
   """

   last = pages[-1] if pages else None

   return {
      "pages_read": len(pages),
      "message_count": sum(len(page.items) for page in pages),
      "more_available": last.has_next_page if last is not None else False,
      "end_cursor": last.end_cursor if last is not None else None,
   }


def render_messages(pages: list[Page[Message]]) -> str:
   """The human form: one line per message, oldest first as the upstream ordered them.

   The order is the upstream's. Nothing here sorts, because a client that reorders a thread
   invents a chronology the server did not state.
   """

   lines = []

   for page in pages:
      for message in page.items:
         text = message.text if message.text is not None else f"<{message.content_type}>"
         lines.append(f"{message.sent_at.isoformat()}  {message.sender.fbid}  {text}")

   trailer = describe_pages(pages)
   lines.append(
      f"pages_read: {trailer['pages_read']}  messages: {trailer['message_count']}  "
      f"more_available: {trailer['more_available']}"
   )

   if trailer["end_cursor"]:
      lines.append(f"next_cursor: {trailer['end_cursor']}")

   return "\n".join(lines)


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
