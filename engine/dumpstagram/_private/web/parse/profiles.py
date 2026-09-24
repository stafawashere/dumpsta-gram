"""Map a profile payload, and the account id read off a timeline's first post."""

from __future__ import annotations

from typing import Any

from dumpstagram._private.web.parse.common import (
   _hd_profile_pic_url,
   _object_at,
   _optional_string,
   _required,
   _required_flag,
   _required_integer,
   _required_string,
)
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import (
   BioLink,
   FriendshipStatus,
   Profile,
)

__all__ = [
   "PROFILE_PATH",
   "TIMELINE_PATH",
   "parse_profile",
   "parse_user_id",
]

PROFILE_PATH = ("data", "user")
"""The path to the profile object in a ``PolarisProfilePageContentQuery`` payload."""

TIMELINE_PATH = ("data", "xdt_api__v1__feed__user_timeline_graphql_connection")
"""The path to the timeline connection the username resolution reads an author id off."""


def _flag_or_default(node: Any, key: str, path: str, default: bool) -> bool:
   """A flag the upstream sends as null on some accounts, read as ``default`` when it does.

   The key must still be there, and anything but a boolean or null still raises.
   """

   value = _required(node, key, path)

   if value is None:
      return default

   if not isinstance(value, bool):
      raise SchemaChanged(f"{path}.{key} is not a boolean or null", path=f"{path}.{key}")

   return value


def _bio_links(node: dict[str, Any], path: str) -> tuple[BioLink, ...]:
   """Map the bio link tray.

   The upstream also sends ``image_url``, ``media_type``, ``media_accent_color_hex`` and
   ``creation_source`` on each entry. ``image_url`` was empty and the other three carried
   values whose meaning nothing here has observed, so they are dropped rather than guessed at.
   """

   raw = _required(node, "bio_links", path)

   if raw is None:
      return ()

   if not isinstance(raw, list):
      raise SchemaChanged(f"{path}.bio_links is not a list", path=f"{path}.bio_links")

   built: list[BioLink] = []

   for index, entry in enumerate(raw):
      entry_path = f"{path}.bio_links[{index}]"

      built.append(
         BioLink(
            link_id=_required_string(entry, "link_id", entry_path),
            url=_required_string(entry, "url", entry_path),
            lynx_url=_required_string(entry, "lynx_url", entry_path),
            title=_required_string(entry, "title", entry_path),
            link_type=_required_string(entry, "link_type", entry_path),
            is_pinned=_required_flag(entry, "is_pinned", entry_path),
         )
      )

   return tuple(built)


def parse_profile(payload: Any) -> Profile:
   """One ``PolarisProfilePageContentQuery`` payload, mapped field by field.

   ``pk`` and ``id`` held the identical value on the measured response. ``id`` is the one
   read, and ``pk`` is not compared against it, because a mapper that raises on two upstream
   names disagreeing would turn a cosmetic upstream change into a dead capability.

   What the upstream sends and this mapper drops, from the response recorded on 2026-09-21:

   - ``pk``, a second name for ``id``.
   - ``mutual_followers_count``, null on the viewer's own profile and a number on another's.
   - ``pronouns``, ``account_badges``, ``regulated_news_in_locations``,
     ``profile_pic_genai_tool_info`` and ``biography_with_entities.entities``, all empty
     lists, so their element shape is unmeasured.
   - ``meta_verified_benefits_info``, ``supervision_info``, ``linked_fb_info``,
     ``ring_creator_metadata``, ``aigm_account_label_info`` and ``gating``, which belong to
     capabilities that do not exist yet.
   - ``should_show_category``, ``address_street``, ``city_name``, ``zip``,
     ``transparency_label``, ``transparency_product``, ``ai_agent_type`` and
     ``profile_context_links_with_user_ids``, all null on the measured response.
   - ``data.viewer``, which repeats the viewer id the session already holds.

   Another account's profile, read six times on 2026-09-23, carried ``friendship_status`` as an
   object of ten flags and ``is_professional_account``, ``has_profile_pic`` and
   ``has_story_archive`` as null, so those three read null as the model's default.

   Finding: `skills/reverse-engineer/knowledge/endpoints/read-a-user-profile.md`.
   """

   user = _object_at(payload, PROFILE_PATH)
   path = ".".join(PROFILE_PATH)

   return Profile(
      id=_required_string(user, "id", path),
      username=_required_string(user, "username", path),
      full_name=_required_string(user, "full_name", path),
      biography=_required_string(user, "biography", path),
      is_private=_required_flag(user, "is_private", path),
      is_verified=_required_flag(user, "is_verified", path),
      follower_count=_required_integer(user, "follower_count", path),
      following_count=_required_integer(user, "following_count", path),
      media_count=_required_integer(user, "media_count", path),
      total_clips_count=_required_integer(user, "total_clips_count", path),
      profile_pic_url=_required_string(user, "profile_pic_url", path),
      hd_profile_pic_url=_hd_profile_pic_url(user, path),
      external_url=_optional_string(user, "external_url", path),
      external_lynx_url=_optional_string(user, "external_lynx_url", path),
      bio_links=_bio_links(user, path),
      category=_optional_string(user, "category", path),
      account_type=_required_integer(user, "account_type", path),
      is_business=_required_flag(user, "is_business", path),
      is_professional_account=_flag_or_default(
         user, "is_professional_account", path, default=False
      ),
      is_memorialized=_required_flag(user, "is_memorialized", path),
      is_unpublished=_required_flag(user, "is_unpublished", path),
      is_embeds_disabled=_required_flag(user, "is_embeds_disabled", path),
      has_profile_pic=_flag_or_default(user, "has_profile_pic", path, default=True),
      has_story_archive=_flag_or_default(user, "has_story_archive", path, default=False),
      friendship_status=_friendship_status(user, path),
   )


def _friendship_status(user: dict[str, Any], path: str) -> FriendshipStatus | None:
   """The viewer's relationship to the account, ``None`` on the viewer's own profile.

   The key must be there either way. Null is the viewer's own profile, and an object is someone
   else's, whose every flag is read by name.
   """

   raw = _required(user, "friendship_status", path)

   if raw is None:
      return None

   status_path = f"{path}.friendship_status"

   if not isinstance(raw, dict):
      raise SchemaChanged(f"{status_path} is not an object or null", path=status_path)

   return FriendshipStatus(
      following=_required_flag(raw, "following", status_path),
      followed_by=_required_flag(raw, "followed_by", status_path),
      outgoing_request=_required_flag(raw, "outgoing_request", status_path),
      incoming_request=_required_flag(raw, "incoming_request", status_path),
      blocking=_required_flag(raw, "blocking", status_path),
      muting=_required_flag(raw, "muting", status_path),
      is_muting_reel=_required_flag(raw, "is_muting_reel", status_path),
      is_restricted=_required_flag(raw, "is_restricted", status_path),
      is_bestie=_required_flag(raw, "is_bestie", status_path),
      is_feed_favorite=_required_flag(raw, "is_feed_favorite", status_path),
   )


def parse_user_id(payload: Any) -> str | None:
   """The account id behind a username, read off the first post's author stub.

   Returns ``None`` when the timeline carries no posts, which is what the upstream answers
   for an account with nothing visible to the viewer. That is an answer rather than a
   failure at this layer, so the capability above decides what it means.

   The author stub carries ``pk`` and ``id`` the same way the profile does. ``pk`` is the one
   read here because it is the field the stub is keyed on.

   Finding: `skills/reverse-engineer/knowledge/endpoints/resolve-a-username-to-a-user-id.md`.
   """

   connection = _object_at(payload, TIMELINE_PATH)
   connection_path = ".".join(TIMELINE_PATH)

   edges = _required(connection, "edges", connection_path)

   if not isinstance(edges, list):
      raise SchemaChanged(f"{connection_path}.edges is not a list", path=f"{connection_path}.edges")

   if not edges:
      return None

   node_path = f"{connection_path}.edges[0].node"
   node = _required(edges[0], "node", f"{connection_path}.edges[0]")
   author = _required(node, "user", node_path)

   return _required_string(author, "pk", f"{node_path}.user")
