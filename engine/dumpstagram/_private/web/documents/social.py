"""Following and unfollowing an account."""

from __future__ import annotations

from dumpstagram._private.web.documents.common import PersistedQuery

__all__ = [
   "FOLLOW_USER",
   "UNFOLLOW_USER",
]

FOLLOW_USER = PersistedQuery(
   doc_id="27767812149509802",
   friendly_name="usePolarisFollowUserFollowMutation",
   finding_id="follow-a-user",
)
"""Follow one account, keyed on its numeric account id as ``target_user_id``, the one variable.

The answer carries ``friendship_status`` with ``following`` alone and the account's ``id``. On a
public account ``following`` came back true, and a profile read after it agreed. What it answers
for a private account, where the follow becomes a request, is unobserved, and ``outgoing_request``
is not in what it selects. Verified by two engine sends on 2026-09-23, under ruling 23, each
undone in the same run.
"""

UNFOLLOW_USER = PersistedQuery(
   doc_id="25174972798866458",
   friendly_name="usePolarisFollowUserUnfollowMutation",
   finding_id="unfollow-a-user",
)
"""Unfollow one account, the same variable as :data:`FOLLOW_USER` under its own id and root.

It answered ``following`` false with the id echoed, and a profile read after it found the
starting relationship back. Whether it withdraws a pending request to a private account is
unobserved. Verified by two engine sends on 2026-09-23, under ruling 23.
"""
