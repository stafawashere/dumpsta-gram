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
   DIRECT_INBOX_NEXT_PAGE,
   DIRECT_TEXT_SEND,
   DIRECT_UNSEND,
   FOLDER_UNREAD_ROWS,
   MESSAGE_REQUESTS,
   THREAD_DETAIL,
   THREAD_MESSAGE_PAGE,
   THREAD_OLDER_PAGE,
)
from dumpstagram._private.web.documents.discovery import (
   LOCATION_INFO,
   LOCATION_POSTS,
   NEW_FEED_POSTS,
   REELS_FEED_FIRST_PAGE,
   REELS_FEED_NEXT_PAGE,
)
from dumpstagram._private.web.documents.feed import HOME_TIMELINE_FEED
from dumpstagram._private.web.documents.media import (
   COMMENT_PAGE,
   COMMENT_REPLIES,
   COMMENT_REPLIES_NEXT_PAGE,
   CREATE_COMMENT,
   DELETE_COMMENT,
   LIKE_MEDIA,
   MORE_FROM_AUTHOR,
   POST_BY_MEDIA_ID,
   POST_BY_SHORTCODE,
   POST_LIKERS,
   UNLIKE_MEDIA,
)
from dumpstagram._private.web.documents.notes import CREATE_NOTE, DELETE_NOTE, INBOX_TRAY
from dumpstagram._private.web.documents.page_load import (
   AUTOMATIC_PREVIEWS_SETTING,
   BADGE_COUNT,
   CHAT_TABS_JEWEL,
   FEATURE_LIMITS,
   GET_FR_COOKIE,
   INBOX_QP_INTERSTITIAL,
   OMNI_PICKER_NULL_STATE,
   PRESENCE_SETUP,
   QUICK_PROMOTION,
   STORIES_TRAY,
   THREAD_LIST_ACCOUNT_SWITCHER,
   VIEWER_SETTINGS,
)
from dumpstagram._private.web.documents.profiles import (
   PROFILE_BY_ID,
   PROFILE_HIGHLIGHTS,
   PROFILE_NOTE_BUBBLE,
   PROFILE_POSTS,
   PROFILE_POSTS_NEXT_PAGE,
   PROFILE_REELS,
   PROFILE_SCHOOL_BADGE,
   PROFILE_SUGGESTED_USERS,
   PROFILE_TAGGED,
   SUGGESTED_ACCOUNTS,
   SUGGESTED_BESIDE_PROFILE,
)
from dumpstagram._private.web.documents.search import (
   HASHTAG_HEADER,
   KEYWORD_RESULTS,
   NON_PERSONALISED_TYPEAHEAD,
   PERSONALISED_TYPEAHEAD,
   RECENT_SEARCHES,
)
from dumpstagram._private.web.documents.social import FOLLOW_USER, UNFOLLOW_USER
from dumpstagram._private.web.documents.stories import STORY_REEL, STORY_SEEN

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
   DIRECT_INBOX_NEXT_PAGE,
   MESSAGE_REQUESTS,
   FOLDER_UNREAD_ROWS,
   PROFILE_POSTS_NEXT_PAGE,
   PROFILE_HIGHLIGHTS,
   SUGGESTED_BESIDE_PROFILE,
   SUGGESTED_ACCOUNTS,
   COMMENT_REPLIES,
   COMMENT_REPLIES_NEXT_PAGE,
   POST_LIKERS,
   POST_BY_MEDIA_ID,
   MORE_FROM_AUTHOR,
   STORIES_TRAY,
   STORY_REEL,
   LOCATION_INFO,
   LOCATION_POSTS,
   NEW_FEED_POSTS,
   RECENT_SEARCHES,
   NON_PERSONALISED_TYPEAHEAD,
   HASHTAG_HEADER,
   PROFILE_REELS,
   PROFILE_TAGGED,
   REELS_FEED_FIRST_PAGE,
   REELS_FEED_NEXT_PAGE,
   PERSONALISED_TYPEAHEAD,
   KEYWORD_RESULTS,
)
"""The queries whose answers a capability reads, in the order the canary replays them."""

COMPANION_QUERIES: tuple[PersistedQuery, ...] = (
   BADGE_COUNT,
   QUICK_PROMOTION,
   CHAT_TABS_JEWEL,
   OMNI_PICKER_NULL_STATE,
   GET_FR_COOKIE,
   PROFILE_NOTE_BUBBLE,
   PROFILE_SUGGESTED_USERS,
   PROFILE_SCHOOL_BADGE,
   AUTOMATIC_PREVIEWS_SETTING,
   FEATURE_LIMITS,
   PRESENCE_SETUP,
   INBOX_QP_INTERSTITIAL,
   THREAD_LIST_ACCOUNT_SWITCHER,
   VIEWER_SETTINGS,
)
"""The queries sent only because a page sends them, whose answers nothing reads.

``PROFILE_HIGHLIGHTS`` left this list for :data:`READ_QUERIES` in E2 batch 2, when
``profiles.highlights`` started reading it. The profile page still sends it as one of its six
queries and still leaves that answer unread. ``STORIES_TRAY`` left it in E2 batch 5 the same
way, when ``stories.tray`` started reading it; every page load but the home page still sends it
and leaves its answer unread.
"""

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
   STORY_SEEN,
)
"""The mutations. The canary compares their ids with the bundle's and never builds one."""
