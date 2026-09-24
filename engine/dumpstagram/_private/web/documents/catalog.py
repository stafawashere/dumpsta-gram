"""Every query in the registry, sorted by what sending it does.

The rotation canary reads this. A read backs a capability and is replayed. A companion is sent
because a page sends it and its answer is never read, and a write changes the account, so both
are checked against the compiled bundle only and never sent by the canary. A gate holds that
every ``PersistedQuery`` in the domain modules is listed here exactly once, so a query added
later cannot go unchecked by omission.
"""

from __future__ import annotations

from dumpstagram._private.web.documents.common import PersistedQuery
from dumpstagram._private.web.documents.direct import (
   DIRECT_INBOX,
   DIRECT_TEXT_SEND,
   DIRECT_UNSEND,
   THREAD_DETAIL,
   THREAD_MESSAGE_PAGE,
   THREAD_OLDER_PAGE,
)
from dumpstagram._private.web.documents.feed import HOME_TIMELINE_FEED
from dumpstagram._private.web.documents.media import (
   COMMENT_PAGE,
   CREATE_COMMENT,
   DELETE_COMMENT,
   LIKE_MEDIA,
   POST_BY_SHORTCODE,
   UNLIKE_MEDIA,
)
from dumpstagram._private.web.documents.notes import CREATE_NOTE, DELETE_NOTE, INBOX_TRAY
from dumpstagram._private.web.documents.page_load import (
   BADGE_COUNT,
   CHAT_TABS_JEWEL,
   GET_FR_COOKIE,
   OMNI_PICKER_NULL_STATE,
   QUICK_PROMOTION,
   STORIES_TRAY,
)
from dumpstagram._private.web.documents.profiles import (
   PROFILE_BY_ID,
   PROFILE_HIGHLIGHTS,
   PROFILE_NOTE_BUBBLE,
   PROFILE_POSTS,
   PROFILE_SCHOOL_BADGE,
   PROFILE_SUGGESTED_USERS,
)
from dumpstagram._private.web.documents.social import FOLLOW_USER, UNFOLLOW_USER

__all__ = [
   "COMPANION_QUERIES",
   "READ_QUERIES",
   "WRITE_QUERIES",
]

READ_QUERIES: tuple[PersistedQuery, ...] = (
   DIRECT_INBOX,
   INBOX_TRAY,
   THREAD_DETAIL,
   THREAD_OLDER_PAGE,
   THREAD_MESSAGE_PAGE,
   HOME_TIMELINE_FEED,
   POST_BY_SHORTCODE,
   COMMENT_PAGE,
   PROFILE_BY_ID,
   PROFILE_POSTS,
)
"""The queries whose answers a capability reads, in the order the canary replays them."""

COMPANION_QUERIES: tuple[PersistedQuery, ...] = (
   BADGE_COUNT,
   QUICK_PROMOTION,
   CHAT_TABS_JEWEL,
   OMNI_PICKER_NULL_STATE,
   STORIES_TRAY,
   GET_FR_COOKIE,
   PROFILE_NOTE_BUBBLE,
   PROFILE_HIGHLIGHTS,
   PROFILE_SUGGESTED_USERS,
   PROFILE_SCHOOL_BADGE,
)
"""The queries sent only because a page sends them, whose answers nothing reads."""

WRITE_QUERIES: tuple[PersistedQuery, ...] = (
   DIRECT_TEXT_SEND,
   DIRECT_UNSEND,
   LIKE_MEDIA,
   UNLIKE_MEDIA,
   CREATE_COMMENT,
   DELETE_COMMENT,
   CREATE_NOTE,
   DELETE_NOTE,
   FOLLOW_USER,
   UNFOLLOW_USER,
)
"""The mutations. The canary compares their ids with the bundle's and never builds one."""
