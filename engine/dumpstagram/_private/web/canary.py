"""How the rotation canary replays each read query once, and what each replay hands the next.

Every read in :data:`~dumpstagram._private.web.documents.catalog.READ_QUERIES` has one step
here, built with the request builder its capability uses and read with the mapper its capability
uses, so a replay that passes is a query the capability would still get an answer from. A replay
that needs an argument takes it from an earlier one: a thread from the inbox listing, a post from
the timeline, a username from the viewer's own profile. Nothing is supplied by the caller, and a
step whose argument never turned up is skipped rather than sent with a guess.

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
   THREAD_DETAIL,
   THREAD_MESSAGE_PAGE,
   THREAD_OLDER_PAGE,
)
from dumpstagram._private.web.documents.feed import HOME_TIMELINE_FEED
from dumpstagram._private.web.documents.media import COMMENT_PAGE, POST_BY_SHORTCODE
from dumpstagram._private.web.documents.notes import INBOX_TRAY
from dumpstagram._private.web.documents.profiles import PROFILE_BY_ID, PROFILE_POSTS
from dumpstagram._private.web.parse.direct import (
   parse_inbox_listing,
   parse_thread_detail,
   parse_thread_message_page,
)
from dumpstagram._private.web.parse.feed import parse_feed_page
from dumpstagram._private.web.parse.media import parse_comment_page, parse_post_detail
from dumpstagram._private.web.parse.notes import parse_inbox_tray
from dumpstagram._private.web.parse.profiles import parse_profile, parse_user_id
from dumpstagram._private.web.requests.direct import (
   build_inbox_listing_request,
   build_thread_detail_request,
   build_thread_older_page_request,
   build_thread_page_request,
)
from dumpstagram._private.web.requests.feed import build_feed_page_request
from dumpstagram._private.web.requests.media import build_comment_page_request, build_post_request
from dumpstagram._private.web.requests.notes import build_inbox_tray_request
from dumpstagram._private.web.requests.profiles import (
   build_profile_request,
   build_username_resolution_request,
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
   ``viewer_id`` is the session's ``ds_user_id``. The rest start empty and are filled by the
   step that reads them.
   """

   device_id: str
   viewer_id: str
   thread_fbid: str | None = None
   post_code: str | None = None
   post_pk: str | None = None
   username: str | None = None


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


def _learn_first_post(payload: Any, arguments: ReplayArguments) -> None:
   page = parse_feed_page(payload)

   for item in page.items:
      if item.post is not None:
         arguments.post_code = item.post.code
         arguments.post_pk = item.post.pk

         return


def _learn_username(payload: Any, arguments: ReplayArguments) -> None:
   arguments.username = parse_profile(payload).username


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
      read=_mapped_by(parse_comment_page),
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
      build=lambda session, arguments, user_agent: build_username_resolution_request(
         session, _required(arguments.username), user_agent=user_agent
      ),
      read=_mapped_by(parse_user_id),
   ),
)
"""The reads in replay order, the order of ``READ_QUERIES``, each arguments' source first."""
