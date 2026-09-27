"""The stories requests: the tray, one account's live stories, one highlight, and the mutation
that marks one item seen.

The three reads mark nothing seen. The seen mutation is the one write here, built since E2 batch
12 (W93).
"""

from __future__ import annotations

import re

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, ORIGIN
from dumpstagram._private.web.documents.page_load import STORIES_TRAY
from dumpstagram._private.web.documents.stories import STORY_REEL, STORY_SEEN
from dumpstagram._private.web.requests.common import build_graphql_request
from dumpstagram.session import Session

__all__ = [
   "build_highlight_request",
   "build_stories_tray_request",
   "build_story_reel_request",
   "build_story_seen_request",
   "refuse_what_is_not_a_highlight_id",
]

COMMUNITY_NOTE_PROVIDER = (
   "__relay_internal__pv__PolarisCommunityNoteStoriesLabelEnabledrelayprovider"
)
"""The one provider flag both reel reads carry, true, as the recorded browse sent it."""

STORIES_TRAY_VARIABLES = {
   "data": {"is_following_feed": False},
   "suggestedUsersData": {
      "max_id": "",
      "max_number_to_display": 0,
      "module": "stories_tray",
      "paginate": False,
   },
}
"""The tray's variables, the ones every captured page load sent and the replays sent."""

_HIGHLIGHT_ID = re.compile(r"highlight:[0-9]+")


def refuse_what_is_not_a_highlight_id(highlight_id: str) -> None:
   """Raise :class:`ValueError` for anything but ``highlight:`` and digits, before anything is
   built or sent.

   The form is the one the highlights tray hands out and the one the replays sent. What the
   upstream answers for a bare number is unobserved.
   """

   is_a_highlight_id = _HIGHLIGHT_ID.fullmatch(highlight_id) is not None

   if not is_a_highlight_id:
      raise ValueError(
         f"{highlight_id!r} is not a highlight id; pass the highlight:<number> form "
         "Highlight.id carries"
      )


def build_stories_tray_request(
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The stories tray, sent alone with the site root as referer.

   Finding: ``page-load-stories-tray``.
   """

   return build_graphql_request(
      session,
      STORIES_TRAY,
      STORIES_TRAY_VARIABLES,
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )


def build_story_reel_request(
   session: Session,
   user_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The live stories of the account whose numeric id is ``user_id``.

   Finding: ``read-one-account-s-stories-or-a-highlight``.
   """

   return build_graphql_request(
      session,
      STORY_REEL,
      {"reel_ids_arr": [user_id], COMMUNITY_NOTE_PROVIDER: True},
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )


def build_highlight_request(
   session: Session,
   highlight_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The highlight whose id is ``highlight_id``, in the ``highlight:<number>`` form.

   Finding: ``read-one-account-s-stories-or-a-highlight``.
   """

   return build_graphql_request(
      session,
      STORY_REEL,
      {"reel_ids_arr": [highlight_id], "is_highlight": True, COMMUNITY_NOTE_PROVIDER: True},
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )


def build_story_seen_request(
   session: Session,
   *,
   reel_id: str,
   item_pk: str,
   owner_id: str,
   taken_at: int,
   viewed_at: int,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Mark the item ``item_pk`` of the reel ``reel_id`` seen, as viewing it does.

   ``reel_id`` is the reel's own id, ``highlight:<number>`` for a highlight and the owner's
   account id for a live reel. ``owner_id`` is the item's owner, and ``taken_at`` and
   ``viewed_at`` are whole seconds. The five variables are the ones the browser sent, in its
   order. On a highlight the referer is the highlight's page, as the browser and the engine
   replay sent it; on a live reel, whose page was never recorded around this mutation, it is the
   site root, as the reel read's is.

   Finding: ``mark-a-story-seen``.
   """

   is_a_highlight = _HIGHLIGHT_ID.fullmatch(reel_id) is not None
   highlight_number = reel_id.removeprefix("highlight:")
   referer = f"{ORIGIN}/stories/highlights/{highlight_number}/" if is_a_highlight else f"{ORIGIN}/"

   return build_graphql_request(
      session,
      STORY_SEEN,
      {
         "reelId": reel_id,
         "reelMediaId": item_pk,
         "reelMediaOwnerId": owner_id,
         "reelMediaTakenAt": taken_at,
         "viewSeenAt": viewed_at,
      },
      referer=referer,
      user_agent=user_agent,
   )
