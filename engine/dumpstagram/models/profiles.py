"""Typed representations of one account's profile.

Every field below was observed on one live `PolarisProfilePageContentQuery` response on
2026-09-21, recorded in `skills/reverse-engineer/knowledge/endpoints/read-a-user-profile.md`.
That response was the viewer's own profile. On 2026-09-23 six reads of another account's
profile added what the upstream fills only for someone else, the viewer's relationship to the
account, which :class:`FriendshipStatus` carries.

Fields the upstream sends and this model does not carry are named in
`dumpstagram/_private/web/parse.py` beside the mapping that drops them.

Nothing here parses. Construction is done by the mapper in `_private/web/parse.py`, which
reads named keys and raises rather than filling a default, so an upstream rename is loud.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["BioLink", "FriendshipStatus", "Profile"]


@dataclass(frozen=True)
class BioLink:
   """One link in the bio link tray.

   ``url`` is what the owner entered. ``lynx_url`` is the upstream's redirector wrapping the
   same destination, and opening it tells Instagram the link was followed, so the two are
   never collapsed into one field.
   """

   link_id: str
   url: str
   lynx_url: str
   title: str
   link_type: str
   is_pinned: bool


@dataclass(frozen=True)
class FriendshipStatus:
   """The viewer's relationship to one account, as that account's profile reports it.

   ``following`` is whether the viewer follows the account, and ``followed_by`` whether the
   account follows the viewer. ``outgoing_request`` is a follow request the viewer sent that the
   account has not answered, which is what following a private account produces, and
   ``following`` stays false while it is pending. ``incoming_request`` is the reverse.

   Every flag was a boolean on each of six reads of another account on 2026-09-23, across two
   follows and two unfollows, and ``following`` moved with each write. ``outgoing_request`` was
   false on all six, because that account is public, so a pending request has not been observed
   and its mapping rests on the name alone.
   """

   following: bool
   followed_by: bool
   outgoing_request: bool
   incoming_request: bool
   blocking: bool
   muting: bool
   is_muting_reel: bool
   is_restricted: bool
   is_bestie: bool
   is_feed_favorite: bool


@dataclass(frozen=True)
class Profile:
   """One account's profile, as the web profile page reads it.

   ``id`` is the numeric account identifier. The upstream sends it twice, as ``pk`` and as
   ``id``, holding the identical value on the measured response, so it is treated as one
   field under two names. It is the identifier
   :meth:`~dumpstagram.aio.AsyncClient.profile_by_id` takes, and it is not the ``fbid`` a
   direct thread's sender carries, which is a different number for the same account.

   ``biography`` is the raw text. ``external_url`` is what the owner entered in the website
   field and ``external_lynx_url`` is the upstream's redirector for it, kept apart for the
   same reason :class:`BioLink` keeps them apart.

   ``follower_count``, ``following_count``, ``media_count`` and ``total_clips_count`` are the
   upstream's own numbers. They are reported, not verified, and nothing here reconciles them
   against what a listing would return.

   ``friendship_status`` is the viewer's relationship to the account, and ``None`` on the
   viewer's own profile, where the upstream sends null. It is the read that confirms
   :meth:`~dumpstagram.aio.AsyncClient.follow` and
   :meth:`~dumpstagram.aio.AsyncClient.unfollow`.

   ``is_professional_account``, ``has_profile_pic`` and ``has_story_archive`` came back null
   rather than boolean on another account's profile, and a null is read as the field's default.

   ``mutual_followers_count`` is deliberately absent. It is null on the viewer's own profile
   and was a number on another's, and nothing yet says what it counts against.
   """

   id: str
   username: str
   full_name: str
   biography: str
   is_private: bool
   is_verified: bool
   follower_count: int
   following_count: int
   media_count: int
   total_clips_count: int
   profile_pic_url: str
   hd_profile_pic_url: str | None = None
   external_url: str | None = None
   external_lynx_url: str | None = None
   bio_links: tuple[BioLink, ...] = ()
   category: str | None = None
   account_type: int | None = None
   is_business: bool = False
   is_professional_account: bool = False
   is_memorialized: bool = False
   is_unpublished: bool = False
   is_embeds_disabled: bool = False
   has_profile_pic: bool = True
   has_story_archive: bool = False
   friendship_status: FriendshipStatus | None = None
