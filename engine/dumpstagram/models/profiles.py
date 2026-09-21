"""Typed representations of one account's profile.

Every field below was observed on one live `PolarisProfilePageContentQuery` response on
2026-09-21, recorded in `skills/reverse-engineer/knowledge/endpoints/read-a-user-profile.md`.
That response was the viewer's own profile, which is the one shape this model is measured
against, and the two fields the upstream fills only for someone else are named below rather
than modelled.

Fields the upstream sends and this model does not carry are named in
`dumpstagram/_private/web/parse.py` beside the mapping that drops them.

Nothing here parses. Construction is done by the mapper in `_private/web/parse.py`, which
reads named keys and raises rather than filling a default, so an upstream rename is loud.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["BioLink", "Profile"]


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

   Two fields the upstream sends are deliberately absent. ``friendship_status`` and
   ``mutual_followers_count`` were both null on the measured response, because it was the
   viewer reading the viewer, and neither has been observed populated, so there is no
   measured shape to model.
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
