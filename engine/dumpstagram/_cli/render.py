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

from dumpstagram.models import (
   Comment,
   Event,
   EventsDropped,
   FeedItem,
   FeedItemKind,
   Message,
   NewMessage,
   Note,
   Page,
   Post,
   PostDetail,
   Profile,
)
from dumpstagram.session import Session

__all__ = [
   "describe_comment",
   "describe_comment_page",
   "describe_event",
   "describe_feed_item",
   "describe_feed_pages",
   "describe_message",
   "describe_note",
   "describe_pages",
   "describe_post",
   "describe_post_detail",
   "describe_profile",
   "render_comment_page",
   "render_event",
   "render_feed",
   "describe_session",
   "render_messages",
   "render_notes",
   "render_post_detail",
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


def describe_post(post: Post) -> dict[str, Any]:
   """The JSON form of one post. Every key here is part of the CLI's contract.

   ``id`` and ``pk`` are both present because they are different identifiers on this surface,
   which is unusual enough that dropping either would make a harness guess.

   ``images`` carries every rendition the upstream offered rather than one chosen here, since
   they are crops at several aspect ratios rather than one picture at several sizes.
   """

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
      "comment_count": post.comment_count,
      "has_liked": post.has_liked,
      "is_seen": post.is_seen,
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
   }


def describe_feed_item(item: FeedItem) -> dict[str, Any]:
   return {
      "kind": item.kind.value,
      "post": describe_post(item.post) if item.post is not None else None,
   }


def describe_feed_pages(pages: list[Page[FeedItem]]) -> dict[str, Any]:
   """What was read, including the terminator and the split between posts and everything else.

   ``more_available`` comes from the last page's own `has_next_page`, never from the number of
   items that arrived. ``item_count`` and ``post_count`` are both reported because they differ
   on every page measured, and reporting only one of them would make the other a guess.
   """

   last = pages[-1] if pages else None
   items = [item for page in pages for item in page.items]
   kinds: dict[str, int] = {}

   for item in items:
      kinds[item.kind.value] = kinds.get(item.kind.value, 0) + 1

   return {
      "pages_read": len(pages),
      "item_count": len(items),
      "post_count": sum(1 for item in items if item.kind is FeedItemKind.POST),
      "kinds": dict(sorted(kinds.items())),
      "more_available": last.has_next_page if last is not None else False,
      "end_cursor": last.end_cursor if last is not None else None,
   }


def render_feed(pages: list[Page[FeedItem]], *, posts_only: bool = False) -> str:
   """The human form: one line per item, in the order the upstream sent them.

   An item that is not a post is printed as its kind alone, so the shape of a real timeline
   stays visible instead of a filtered list that never explains its own length.

   ``posts_only`` drops those lines on request. The trailer still counts every item that
   arrived, so a filtered listing says how much it hid rather than looking like a short page.
   """

   lines = []

   for page in pages:
      for item in page.items:
         post = item.post

         if post is None:
            if not posts_only:
               lines.append(f"{item.kind.value}")

            continue

         caption = post.caption.splitlines()[0] if post.caption else ""
         lines.append(
            f"{post.taken_at.isoformat()}  {post.author.username}  "
            f"likes {post.like_count}  comments {post.comment_count}  {post.code}  {caption}"
         )

   trailer = describe_feed_pages(pages)
   lines.append(
      f"pages_read: {trailer['pages_read']}  items: {trailer['item_count']}  "
      f"posts: {trailer['post_count']}  more_available: {trailer['more_available']}"
   )

   if trailer["end_cursor"]:
      lines.append(f"next_cursor: {trailer['end_cursor']}")

   return "\n".join(lines)


def describe_note(note: Note, *, viewer_id: str) -> dict[str, Any]:
   """The JSON form of one note. Every key here is part of the CLI's contract."""

   return {
      "id": note.id,
      "author_id": note.author_id,
      "author_username": note.author_username,
      "is_own": note.author_id == viewer_id,
      "text": note.text,
      "audience": note.audience.name.lower(),
      "created_at": note.created_at.isoformat(),
      "is_emoji_only": note.is_emoji_only,
   }


def render_notes(notes: tuple[Note, ...], *, viewer_id: str) -> str:
   """The human form: one line per note, the viewer's own marked, then a count."""

   lines = []

   for note in notes:
      marker = "*" if note.author_id == viewer_id else " "
      author = note.author_username or note.author_id
      audience = note.audience.name.lower()
      lines.append(f"{marker} {note.id}  {author}  [{audience}]  {note.text}")

   has_own_note = any(note.author_id == viewer_id for note in notes)
   own_summary = "your note is marked *" if has_own_note else "you have no note"
   lines.append(f"{len(notes)} notes, {own_summary}")

   return "\n".join(lines)


def describe_post_detail(post: PostDetail) -> dict[str, Any]:
   """The JSON form of one post read on its own. Every key here is part of the CLI's contract.

   The same keys as :func:`describe_post` without ``is_seen``, which this read does not carry.
   """

   described = describe_post(
      Post(
         id=post.id,
         pk=post.pk,
         code=post.code,
         taken_at=post.taken_at,
         author=post.author,
         media_type=post.media_type,
         product_type=post.product_type,
         like_count=post.like_count,
         comment_count=post.comment_count,
         has_liked=post.has_liked,
         is_seen=False,
         caption=post.caption,
         accessibility_caption=post.accessibility_caption,
         original_width=post.original_width,
         original_height=post.original_height,
         carousel_media_count=post.carousel_media_count,
         images=post.images,
         is_paid_partnership=post.is_paid_partnership,
         like_and_view_counts_disabled=post.like_and_view_counts_disabled,
      )
   )
   del described["is_seen"]

   return described


def render_post_detail(post: PostDetail) -> str:
   """The human form: the post's identifiers, then the viewer's like state and the counts."""

   caption = post.caption.splitlines()[0] if post.caption else ""

   return "\n".join(
      [
         f"{post.code}  pk {post.pk}  {post.author.username}  {post.taken_at.isoformat()}",
         f"has_liked: {post.has_liked}  likes: {post.like_count}  comments: {post.comment_count}",
         caption,
      ]
   ).rstrip("\n")


def describe_comment(comment: Comment) -> dict[str, Any]:
   """The JSON form of one comment. Every key here is part of the CLI's contract.

   The last four keys are null on a comment ``comment`` just created, because the answer to a
   new comment does not carry them.
   """

   return {
      "id": comment.id,
      "text": comment.text,
      "created_at": comment.created_at.isoformat(),
      "author": {
         "id": comment.author.id,
         "username": comment.author.username,
         "is_verified": comment.author.is_verified,
      },
      "like_count": comment.like_count,
      "reply_count": comment.reply_count,
      "parent_comment_id": comment.parent_comment_id,
      "has_liked": comment.has_liked,
   }


def describe_comment_page(page: Page[Comment]) -> dict[str, Any]:
   """One page of comments with its terminator, which is the only thing that says there is more.

   ``more_available`` is the page's own ``has_next_page``, never a guess from how many
   comments arrived.
   """

   return {
      "comment_count": len(page.items),
      "more_available": page.has_next_page,
      "end_cursor": page.end_cursor,
      "comments": [describe_comment(comment) for comment in page.items],
   }


def render_comment_page(page: Page[Comment]) -> str:
   """The human form: one line per comment in the upstream's order, then the terminator."""

   lines = [
      f"{comment.created_at.isoformat()}  {comment.id}  {comment.author.username}  {comment.text}"
      for comment in page.items
   ]
   more = f"more after {page.end_cursor}" if page.has_next_page else "no more comments"
   lines.append(f"{len(page.items)} comments, {more}")

   return "\n".join(lines)


def describe_event(event: Event, *, ids_only: bool) -> dict[str, Any]:
   """The JSON form of one listener event, one object per line of output.

   ``ids_only`` keeps a message's identifiers and time and drops its text, its sender's name
   and its reactions, for a run whose output lands in a log.
   """

   if isinstance(event, NewMessage):
      message = event.message

      if not ids_only:
         return {"event": "new_message", "message": describe_message(message)}

      return {
         "event": "new_message",
         "message": {
            "id": message.id,
            "thread_fbid": message.thread_fbid,
            "sender_fbid": message.sender.fbid,
            "sent_at": message.sent_at.isoformat(),
            "content_type": message.content_type,
         },
      }

   if isinstance(event, EventsDropped):
      return {"event": "events_dropped", "count": event.count, "thread_fbid": event.thread_fbid}

   return {"event": type(event).__name__}


def render_event(event: Event, *, ids_only: bool) -> str:
   """The human form of one listener event, one line."""

   if isinstance(event, NewMessage):
      message = event.message
      line = (
         f"new_message  {message.sent_at.isoformat()}  {message.thread_fbid}  "
         f"{message.sender.fbid}  {message.id}"
      )

      if ids_only:
         return line

      text = message.text if message.text is not None else f"<{message.content_type}>"

      return f"{line}  {text}"

   if isinstance(event, EventsDropped):
      count = "unknown" if event.count is None else str(event.count)
      thread = event.thread_fbid or "any"

      return f"events_dropped  count: {count}  thread: {thread}"

   return type(event).__name__
