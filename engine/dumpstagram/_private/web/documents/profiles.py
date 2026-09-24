"""The profile queries: one account by id, a username resolved through its timeline, and the
companions a profile page sends.
"""

from __future__ import annotations

from dumpstagram._private.web.documents.common import GRAPHQL_QUERY_URL, PersistedQuery

__all__ = [
   "PROFILE_BY_ID",
   "PROFILE_HIGHLIGHTS",
   "PROFILE_NOTE_BUBBLE",
   "PROFILE_POSTS",
   "PROFILE_SCHOOL_BADGE",
   "PROFILE_SUGGESTED_USERS",
]

PROFILE_BY_ID = PersistedQuery(
   doc_id="28036671149327607",
   friendly_name="PolarisProfilePageContentQuery",
   finding_id="read-a-user-profile",
)
"""One account's profile, keyed on the numeric account id.

This query takes no username. Its compiled Relay artifact declares ``id`` as its only caller
argument and roots at ``fetch__XDTUserDict(id: $id)``, which is why a caller holding a
username reads it off the profile page first, or resolves it through :data:`PROFILE_POSTS`.

Observed live on 2026-09-21.
"""

PROFILE_POSTS = PersistedQuery(
   doc_id="28379418928391013",
   friendly_name="PolarisProfilePostsQuery",
   finding_id="resolve-a-username-to-a-user-id",
   url=GRAPHQL_QUERY_URL,
   root_field="xdt_api__v1__feed__user_timeline_graphql_connection",
)
"""The first posts on one account's timeline, keyed on the username.

A profile page sends it as one of its six queries. The engine also uses it for the one thing
it has that the profile query does not, a ``username`` argument, when a client departs from
the page route: the account id then comes off a post node, so an account with nothing visible
to the viewer resolves to nothing at all, and the capability reports that as
:class:`~dumpstagram.errors.NotFound`.

The obvious alternative, ``GET /api/v1/users/web_profile_info/?username=``, answered 429 with
an HTML body on its first and only attempt on 2026-09-21, so it is not used.

Observed live on 2026-09-21 on the other path under an older id. On 2026-09-23 both profile
cold loads sent the id before this one to
:data:`~dumpstagram._private.web.documents.common.GRAPHQL_QUERY_URL`. On 2026-09-24
`dumpsta doctor` found the bundles compiling this one while the old one still answered, and
the engine moved to it after two engine replays.
"""

PROFILE_NOTE_BUBBLE = PersistedQuery(
   doc_id="38260824646898178",
   friendly_name="PolarisProfileNoteBubbleQuery",
   finding_id="profile-page-note-bubble",
)
"""The note bubble over a profile picture. One of the six queries a profile page sends."""

PROFILE_HIGHLIGHTS = PersistedQuery(
   doc_id="26970053832668570",
   friendly_name="PolarisProfileStoryHighlightsTrayContentQuery",
   finding_id="profile-page-story-highlights",
)
"""The story highlights tray on a profile. One of the six queries a profile page sends."""

PROFILE_SUGGESTED_USERS = PersistedQuery(
   doc_id="27929823133325729",
   friendly_name="PolarisProfileSuggestedUsersWithPreloadableQuery",
   finding_id="profile-page-suggested-users",
)
"""Accounts suggested beside a profile. One of the six queries a profile page sends, and the
largest of the five companions, 30 kB and 117 kB in the two measured loads."""

PROFILE_SCHOOL_BADGE = PersistedQuery(
   doc_id="27862800913344283",
   friendly_name="PolarisSchoolPartnerProfileBadgeQuery",
   finding_id="profile-page-school-badge",
)
"""The school partner badge on a profile. One of the six queries a profile page sends."""
