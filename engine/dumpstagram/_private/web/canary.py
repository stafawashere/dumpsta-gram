"""How the rotation canary replays each read query once, and what each replay hands the next.

Every read in :data:`~dumpstagram._private.web.documents.catalog.READ_QUERIES` has one step
here, built with the request builder its capability uses and read with the mapper its capability
uses, so a replay that passes is a query the capability would still get an answer from. A replay
that needs an argument takes it from an earlier one: a thread from the inbox listing, a post from
the timeline, a username from the viewer's own profile, a grid cursor from the viewer's grid, a
comment with replies from the post's comments, a highlight from the viewer's highlights tray.
Nothing is supplied by the caller, and a step whose argument never turned up is skipped rather
than sent with a guess.

Only ``_core`` sends. This module builds and reads.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dumpstagram._private.transport import Request
from dumpstagram._private.web.documents.common import PersistedQuery
from dumpstagram._private.web.documents.direct import (
   DIRECT_INBOX,
   DIRECT_INBOX_NEXT_PAGE,
   FOLDER_UNREAD_ROWS,
   MESSAGE_REQUESTS,
   THREAD_DETAIL,
   THREAD_MESSAGE_PAGE,
   THREAD_OLDER_PAGE,
)
from dumpstagram._private.web.documents.feed import HOME_TIMELINE_FEED
from dumpstagram._private.web.documents.media import (
   COMMENT_PAGE,
   COMMENT_REPLIES,
   COMMENT_REPLIES_NEXT_PAGE,
   MORE_FROM_AUTHOR,
   POST_BY_MEDIA_ID,
   POST_BY_SHORTCODE,
   POST_LIKERS,
)
from dumpstagram._private.web.documents.notes import INBOX_TRAY
from dumpstagram._private.web.documents.page_load import STORIES_TRAY
from dumpstagram._private.web.documents.profiles import (
   PROFILE_BY_ID,
   PROFILE_HIGHLIGHTS,
   PROFILE_POSTS,
   PROFILE_POSTS_NEXT_PAGE,
   SUGGESTED_ACCOUNTS,
   SUGGESTED_BESIDE_PROFILE,
)
from dumpstagram._private.web.documents.stories import STORY_REEL
from dumpstagram._private.web.parse.direct import (
   parse_folder_unread_rows,
   parse_inbox_continuation,
   parse_inbox_listing,
   parse_inbox_next_page,
   parse_message_requests,
   parse_thread_detail,
   parse_thread_message_page,
)
from dumpstagram._private.web.parse.feed import parse_feed_page
from dumpstagram._private.web.parse.media import (
   parse_comment_page,
   parse_likers,
   parse_more_from_author,
   parse_post_by_media_id,
   parse_post_detail,
   parse_reply_page,
)
from dumpstagram._private.web.parse.notes import parse_inbox_tray
from dumpstagram._private.web.parse.profiles import (
   parse_highlight_tray,
   parse_profile,
   parse_profile_posts_page,
   parse_suggested_accounts,
   parse_suggested_beside_profile,
   parse_user_id,
)
from dumpstagram._private.web.parse.stories import parse_highlight_reel, parse_stories_tray
from dumpstagram._private.web.requests.direct import (
   INBOX_FOLDER,
   build_folder_unread_rows_request,
   build_inbox_listing_request,
   build_inbox_next_page_request,
   build_message_requests_request,
   build_thread_detail_request,
   build_thread_older_page_request,
   build_thread_page_request,
)
from dumpstagram._private.web.requests.feed import build_feed_page_request
from dumpstagram._private.web.requests.media import (
   build_comment_page_request,
   build_likers_request,
   build_more_from_author_request,
   build_post_by_id_request,
   build_post_request,
   build_replies_request,
)
from dumpstagram._private.web.requests.notes import build_inbox_tray_request
from dumpstagram._private.web.requests.profiles import (
   build_highlight_tray_request,
   build_profile_posts_request,
   build_profile_request,
   build_suggested_accounts_request,
   build_suggested_beside_profile_request,
)
from dumpstagram._private.web.requests.stories import (
   build_highlight_request,
   build_stories_tray_request,
)
from dumpstagram.session import Session

__all__ = [
   "REPLAY_STEPS",
   "ReplayArguments",
   "ReplayStep",
]


@dataclass
class ReplayArguments:
   """What the replays so far have learned, which later replays are keyed on.

   ``device_id`` is the inbox document's own iris device id, as the poller sends it, and
   ``viewer_id`` is the session's ``ds_user_id``. ``now_ms`` is the run's clock, which the
   requests and unread reads count 30 days back from. The rest start empty and are filled by the
   step that reads them.
   """

   device_id: str
   viewer_id: str
   now_ms: int = 0
   thread_fbid: str | None = None
   mailbox_id: str | None = None
   inbox_cursor: str | None = None
   post_code: str | None = None
   post_pk: str | None = None
   username: str | None = None
   posts_cursor: str | None = None
   author_id: str | None = None
   parent_comment_id: str | None = None
   replies_cursor: str | None = None
   highlight_id: str | None = None


@dataclass(frozen=True)
class ReplayStep:
   """One read replayed once.

   ``requires`` names the :class:`ReplayArguments` field the request is keyed on, or is
   ``None`` for a request keyed on nothing learned. ``read`` maps the classified payload with
   the capability's own mapper and records what later steps need, raising what the mapper raises.
   """

   query: PersistedQuery
   requires: str | None
   build: Callable[[Session, ReplayArguments, str], Request]
   read: Callable[[Any, ReplayArguments], None]


def _learn_first_thread(payload: Any, arguments: ReplayArguments) -> None:
   listing = parse_inbox_listing(payload)

   if listing.items:
      arguments.thread_fbid = listing.items[0].thread_fbid

   mailbox_id, end_cursor = parse_inbox_continuation(payload)

   if end_cursor is not None:
      arguments.mailbox_id = mailbox_id
      arguments.inbox_cursor = end_cursor


def _learn_first_post(payload: Any, arguments: ReplayArguments) -> None:
   page = parse_feed_page(payload)

   for item in page.items:
      if item.post is not None:
         arguments.post_code = item.post.code
         arguments.post_pk = item.post.pk
         arguments.author_id = item.post.author.id

         return


def _learn_username(payload: Any, arguments: ReplayArguments) -> None:
   arguments.username = parse_profile(payload).username


def _learn_grid_cursor(payload: Any, arguments: ReplayArguments) -> None:
   """The grid's first page, read by both mappers its query feeds: the page and the account id
   the username resolution reads off it. A cursor is kept only when the page says more exist."""

   page = parse_profile_posts_page(payload)
   parse_user_id(payload)

   if page.has_next_page:
      arguments.posts_cursor = page.end_cursor


def _learn_comment_with_replies(payload: Any, arguments: ReplayArguments) -> None:
   """The post's first comment page, and the first comment on it that has replies."""

   for comment in parse_comment_page(payload).items:
      has_replies = (comment.reply_count or 0) > 0

      if has_replies:
         arguments.parent_comment_id = comment.id

         return


def _learn_replies_cursor(payload: Any, arguments: ReplayArguments) -> None:
   page = parse_reply_page(payload)

   if page.has_next_page:
      arguments.replies_cursor = page.end_cursor


def _learn_first_highlight(payload: Any, arguments: ReplayArguments) -> None:
   """The viewer's own highlights tray, and its first highlight, which the story reel step reads,
   so the canary never reads another account's story."""

   tray = parse_highlight_tray(payload)

   if tray.highlights:
      arguments.highlight_id = tray.highlights[0].id


def _mapped_by(mapper: Callable[[Any], object]) -> Callable[[Any, ReplayArguments], None]:
   """A read that maps the payload with ``mapper`` and learns nothing from it."""

   def read(payload: Any, arguments: ReplayArguments) -> None:
      mapper(payload)

   return read


def _required(value: str | None) -> str:
   if value is None:
      raise ValueError("a replay step was built without the argument it requires")

   return value


REPLAY_STEPS: tuple[ReplayStep, ...] = (
   ReplayStep(
      query=DIRECT_INBOX,
      requires=None,
      build=lambda session, arguments, user_agent: build_inbox_listing_request(
         session, device_id=arguments.device_id, user_agent=user_agent
      ),
      read=_learn_first_thread,
   ),
   ReplayStep(
      query=INBOX_TRAY,
      requires=None,
      build=lambda session, arguments, user_agent: build_inbox_tray_request(
         session, user_agent=user_agent
      ),
      read=_mapped_by(parse_inbox_tray),
   ),
   ReplayStep(
      query=THREAD_DETAIL,
      requires="thread_fbid",
      build=lambda session, arguments, user_agent: build_thread_detail_request(
         session, _required(arguments.thread_fbid), user_agent=user_agent
      ),
      read=_mapped_by(parse_thread_detail),
   ),
   ReplayStep(
      query=THREAD_OLDER_PAGE,
      requires="thread_fbid",
      build=lambda session, arguments, user_agent: build_thread_older_page_request(
         session, _required(arguments.thread_fbid), user_agent=user_agent
      ),
      read=_mapped_by(parse_thread_message_page),
   ),
   ReplayStep(
      query=THREAD_MESSAGE_PAGE,
      requires="thread_fbid",
      build=lambda session, arguments, user_agent: build_thread_page_request(
         session, _required(arguments.thread_fbid), user_agent=user_agent
      ),
      read=_mapped_by(parse_thread_message_page),
   ),
   ReplayStep(
      query=HOME_TIMELINE_FEED,
      requires=None,
      build=lambda session, arguments, user_agent: build_feed_page_request(
         session, user_agent=user_agent
      ),
      read=_learn_first_post,
   ),
   ReplayStep(
      query=POST_BY_SHORTCODE,
      requires="post_code",
      build=lambda session, arguments, user_agent: build_post_request(
         session, _required(arguments.post_code), user_agent=user_agent
      ),
      read=_mapped_by(parse_post_detail),
   ),
   ReplayStep(
      query=COMMENT_PAGE,
      requires="post_pk",
      build=lambda session, arguments, user_agent: build_comment_page_request(
         session, _required(arguments.post_pk), user_agent=user_agent
      ),
      read=_learn_comment_with_replies,
   ),
   ReplayStep(
      query=PROFILE_BY_ID,
      requires="viewer_id",
      build=lambda session, arguments, user_agent: build_profile_request(
         session, arguments.viewer_id, user_agent=user_agent
      ),
      read=_learn_username,
   ),
   ReplayStep(
      query=PROFILE_POSTS,
      requires="username",
      build=lambda session, arguments, user_agent: build_profile_posts_request(
         session, _required(arguments.username), user_agent=user_agent
      ),
      read=_learn_grid_cursor,
   ),
   ReplayStep(
      query=DIRECT_INBOX_NEXT_PAGE,
      requires="inbox_cursor",
      build=lambda session, arguments, user_agent: build_inbox_next_page_request(
         session,
         mailbox_id=_required(arguments.mailbox_id),
         cursor=_required(arguments.inbox_cursor),
         user_agent=user_agent,
      ),
      read=_mapped_by(parse_inbox_next_page),
   ),
   ReplayStep(
      query=MESSAGE_REQUESTS,
      requires=None,
      build=lambda session, arguments, user_agent: build_message_requests_request(
         session, iris_device_id=arguments.device_id, now_ms=arguments.now_ms, user_agent=user_agent
      ),
      read=_mapped_by(parse_message_requests),
   ),
   ReplayStep(
      query=FOLDER_UNREAD_ROWS,
      requires=None,
      build=lambda session, arguments, user_agent: build_folder_unread_rows_request(
         session,
         iris_device_id=arguments.device_id,
         folder=INBOX_FOLDER,
         now_ms=arguments.now_ms,
         user_agent=user_agent,
      ),
      read=_mapped_by(parse_folder_unread_rows),
   ),
   ReplayStep(
      query=PROFILE_POSTS_NEXT_PAGE,
      requires="posts_cursor",
      build=lambda session, arguments, user_agent: build_profile_posts_request(
         session,
         _required(arguments.username),
         after=_required(arguments.posts_cursor),
         user_agent=user_agent,
      ),
      read=_mapped_by(parse_profile_posts_page),
   ),
   ReplayStep(
      query=PROFILE_HIGHLIGHTS,
      requires="viewer_id",
      build=lambda session, arguments, user_agent: build_highlight_tray_request(
         session, arguments.viewer_id, user_agent=user_agent
      ),
      read=_learn_first_highlight,
   ),
   ReplayStep(
      query=SUGGESTED_BESIDE_PROFILE,
      requires="viewer_id",
      build=lambda session, arguments, user_agent: build_suggested_beside_profile_request(
         session, arguments.viewer_id, user_agent=user_agent
      ),
      read=_mapped_by(parse_suggested_beside_profile),
   ),
   ReplayStep(
      query=SUGGESTED_ACCOUNTS,
      requires=None,
      build=lambda session, arguments, user_agent: build_suggested_accounts_request(
         session, user_agent=user_agent
      ),
      read=_mapped_by(parse_suggested_accounts),
   ),
   ReplayStep(
      query=COMMENT_REPLIES,
      requires="parent_comment_id",
      build=lambda session, arguments, user_agent: build_replies_request(
         session,
         _required(arguments.post_pk),
         _required(arguments.parent_comment_id),
         user_agent=user_agent,
      ),
      read=_learn_replies_cursor,
   ),
   ReplayStep(
      query=COMMENT_REPLIES_NEXT_PAGE,
      requires="replies_cursor",
      build=lambda session, arguments, user_agent: build_replies_request(
         session,
         _required(arguments.post_pk),
         _required(arguments.parent_comment_id),
         after=_required(arguments.replies_cursor),
         user_agent=user_agent,
      ),
      read=_mapped_by(parse_reply_page),
   ),
   ReplayStep(
      query=POST_LIKERS,
      requires="post_pk",
      build=lambda session, arguments, user_agent: build_likers_request(
         session, _required(arguments.post_pk), user_agent=user_agent
      ),
      read=_mapped_by(parse_likers),
   ),
   ReplayStep(
      query=POST_BY_MEDIA_ID,
      requires="post_pk",
      build=lambda session, arguments, user_agent: build_post_by_id_request(
         session, _required(arguments.post_pk), user_agent=user_agent
      ),
      read=_mapped_by(parse_post_by_media_id),
   ),
   ReplayStep(
      query=MORE_FROM_AUTHOR,
      requires="author_id",
      build=lambda session, arguments, user_agent: build_more_from_author_request(
         session, _required(arguments.author_id), user_agent=user_agent
      ),
      read=_mapped_by(parse_more_from_author),
   ),
   ReplayStep(
      query=STORIES_TRAY,
      requires=None,
      build=lambda session, arguments, user_agent: build_stories_tray_request(
         session, user_agent=user_agent
      ),
      read=_mapped_by(parse_stories_tray),
   ),
   ReplayStep(
      query=STORY_REEL,
      requires="highlight_id",
      build=lambda session, arguments, user_agent: build_highlight_request(
         session, _required(arguments.highlight_id), user_agent=user_agent
      ),
      read=_mapped_by(parse_highlight_reel),
   ),
)
"""The reads in replay order, the order of ``READ_QUERIES``, each arguments' source first."""
