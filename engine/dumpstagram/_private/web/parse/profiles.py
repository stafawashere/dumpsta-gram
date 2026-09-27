"""Map a profile payload, the account id read off a timeline's first post, a page of a profile's
posts grid, its highlights tray, the two lists of suggested accounts, and a page of an account's
followers with the viewer's relationship to each."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from dumpstagram._private.web.parse.common import (
   _hd_profile_pic_url,
   _object_at,
   _optional_flag,
   _optional_integer,
   _optional_string,
   _required,
   _required_flag,
   _required_integer,
   _required_string,
)
from dumpstagram._private.web.parse.media import parse_post
from dumpstagram._private.web.parse.posting import _raise_unless_ok
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import (
   BioLink,
   FriendshipStatus,
   Highlight,
   HighlightTray,
   ListFriendshipStatus,
   Page,
   Post,
   Profile,
   ProfileSummary,
   SuggestedAccount,
)

__all__ = [
   "HIGHLIGHT_TRAY_PATH",
   "PROFILE_PATH",
   "SUGGESTED_ACCOUNTS_PATH",
   "SUGGESTED_BESIDE_PROFILE_PATH",
   "TIMELINE_PATH",
   "attach_friendship_statuses",
   "parse_followers_page",
   "parse_friendship_statuses",
   "parse_highlight_tray",
   "parse_profile",
   "parse_profile_posts_page",
   "parse_profile_summary",
   "parse_suggested_accounts",
   "parse_suggested_beside_profile",
   "parse_user_id",
]

PROFILE_PATH = ("data", "user")
"""The path to the profile object in a ``PolarisProfilePageContentQuery`` payload."""

TIMELINE_PATH = ("data", "xdt_api__v1__feed__user_timeline_graphql_connection")
"""The path to the timeline connection: the posts grid's pages, first and next, both answer under
it, and the username resolution reads an author id off its first post."""

HIGHLIGHT_TRAY_PATH = ("data", "highlights")
"""The path to the highlights connection in a ``PolarisProfileStoryHighlightsTrayContentQuery``
payload."""

SUGGESTED_BESIDE_PROFILE_PATH = ("data", "xdt_api__v1__discover__chaining")
"""The path to the accounts suggested beside a profile, which carries ``users`` and nothing else."""

SUGGESTED_ACCOUNTS_PATH = ("data", "ayml")
"""The path to the suggested accounts list, which carries ``groups`` and nothing else."""


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

   Account B read by the owner on 2026-09-27, an account with no posts and no reels, carried
   ``total_clips_count`` as something other than an integer, INFERENCE null (W92). Null reads
   as 0 on the frozen ``total_clips_count`` and as ``None`` on ``reported_clips_count``, and an
   absent key or any other type still raises.

   Finding: `skills/reverse-engineer/knowledge/endpoints/read-a-user-profile.md`.
   """

   user = _object_at(payload, PROFILE_PATH)
   path = ".".join(PROFILE_PATH)
   reported_clips_count = _optional_integer(user, "total_clips_count", path)
   total_clips_count = 0 if reported_clips_count is None else reported_clips_count

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
      total_clips_count=total_clips_count,
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
      reported_clips_count=reported_clips_count,
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


def _list_of(node: dict[str, Any], key: str, path: str) -> list[Any]:
   value = _required(node, key, path)

   if not isinstance(value, list):
      raise SchemaChanged(f"{path}.{key} is not a list", path=f"{path}.{key}")

   return value


def _page_info(connection: dict[str, Any], path: str) -> tuple[bool, str | None]:
   page_info_path = f"{path}.page_info"
   page_info = _required(connection, "page_info", path)

   if not isinstance(page_info, dict):
      raise SchemaChanged(f"{page_info_path} is not an object", path=page_info_path)

   has_next_page = _required_flag(page_info, "has_next_page", page_info_path)
   end_cursor = _optional_string(page_info, "end_cursor", page_info_path)

   return has_next_page, end_cursor


def parse_profile_posts_page(payload: Any) -> Page[Post]:
   """One page of a profile's posts grid, first or next, mapped into posts.

   Both queries answer under :data:`TIMELINE_PATH` beside ``xdt_viewer``, which is dropped. A
   grid node is the home timeline's media node key for key, with ten keys more that are dropped
   (``__typename``, ``group``, ``longform_title``, ``media_cropping_info``, ``photo_of_you``,
   ``profile_grid_thumbnail_fitting_style``, ``thumbnails``, ``timeline_pinned_user_ids``,
   ``title`` and ``upcoming_event``) and ``is_seen`` null on all 32 nodes read, which reads as
   False (W53). The per-edge ``cursor`` was null on every edge, as on the home timeline, so
   ``page_info`` is the only cursor.

   A post whose location picture failed arrives whole with that one field null beside a field
   error, and is mapped like any other, since nothing here reads the location (W52).

   Findings: ``resolve-a-username-to-a-user-id`` for the first page and
   ``profile-posts-grid-next-page`` for the rest.
   """

   connection = _object_at(payload, TIMELINE_PATH)
   connection_path = ".".join(TIMELINE_PATH)
   edges = _list_of(connection, "edges", connection_path)

   posts = tuple(
      parse_post(
         _required(edge, "node", f"{connection_path}.edges[{index}]"),
         f"{connection_path}.edges[{index}].node",
         null_is_unseen=True,
      )
      for index, edge in enumerate(edges)
   )
   has_next_page, end_cursor = _page_info(connection, connection_path)

   return Page(items=posts, has_next_page=has_next_page, end_cursor=end_cursor)


def _highlight(node: Any, path: str) -> Highlight:
   if not isinstance(node, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

   cover = _object_at(node, ("cover_media", "cropped_image_version"))
   owner = _object_at(node, ("user",))

   return Highlight(
      id=_required_string(node, "id", path),
      title=_required_string(node, "title", path),
      cover_url=_required_string(cover, "url", f"{path}.cover_media.cropped_image_version"),
      owner_id=_required_string(owner, "id", f"{path}.user"),
      owner_username=_required_string(owner, "username", f"{path}.user"),
   )


def parse_highlight_tray(payload: Any) -> HighlightTray:
   """One ``PolarisProfileStoryHighlightsTrayContentQuery`` payload, the tray's first page.

   Each node carried ``id``, ``title``, ``cover_media.cropped_image_version.url`` and a ``user``
   of ``id`` and ``username``, and ``__typename`` XDTReelDict, which is dropped. The per-edge
   ``cursor`` was the empty string. ``page_info.has_next_page`` is carried as ``has_more`` and
   its cursor is not, because no query that follows it has answered (W54).

   Finding: ``profile-page-story-highlights``.
   """

   connection = _object_at(payload, HIGHLIGHT_TRAY_PATH)
   connection_path = ".".join(HIGHLIGHT_TRAY_PATH)
   edges = _list_of(connection, "edges", connection_path)

   highlights = tuple(
      _highlight(
         _required(edge, "node", f"{connection_path}.edges[{index}]"),
         f"{connection_path}.edges[{index}].node",
      )
      for index, edge in enumerate(edges)
   )
   has_more, _ = _page_info(connection, connection_path)

   return HighlightTray(highlights=highlights, has_more=has_more)


def _flag_if_carried(node: dict[str, Any], key: str, path: str) -> bool | None:
   """A flag some lists carry and others do not: ``None`` when the key is absent."""

   if key not in node:
      return None

   return _optional_flag(node, key, path)


def _list_friendship_status(row: dict[str, Any], path: str) -> ListFriendshipStatus | None:
   raw = row.get("friendship_status")

   if raw is None:
      return None

   return _read_list_friendship_status(raw, f"{path}.friendship_status")


def _read_list_friendship_status(raw: Any, status_path: str) -> ListFriendshipStatus:
   if not isinstance(raw, dict):
      raise SchemaChanged(f"{status_path} is not an object or null", path=status_path)

   return ListFriendshipStatus(
      following=_required_flag(raw, "following", status_path),
      outgoing_request=_required_flag(raw, "outgoing_request", status_path),
      incoming_request=_required_flag(raw, "incoming_request", status_path),
      is_bestie=_required_flag(raw, "is_bestie", status_path),
      is_feed_favorite=_required_flag(raw, "is_feed_favorite", status_path),
      is_restricted=_required_flag(raw, "is_restricted", status_path),
      followed_by=_flag_if_carried(raw, "followed_by", status_path),
      blocking=_flag_if_carried(raw, "blocking", status_path),
   )


def parse_profile_summary(row: Any, path: str, *, id_key: str = "pk") -> ProfileSummary:
   """One account row of a list, mapped field by field.

   ``pk`` is the id read, the key a row is built around, and ``id`` held the same value on all
   138 rows read on 2026-09-27. A list whose ``pk`` is a number, as the pending follow requests
   send it, names another key that carries the same id as a string in ``id_key``.
   ``is_private``, ``hd_profile_pic_url_info`` and ``friendship_status`` are read where the row
   carries them and are ``None`` where it does not: no row of the suggested accounts list
   carried ``is_private``. Dropped: ``is_unpublished``, false on every row, and
   ``supervision_info``, ``social_context``,
   ``live_broadcast_visibility`` and ``live_broadcast_id``, null on every row.
   """

   if not isinstance(row, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

   carries_hd_picture = "hd_profile_pic_url_info" in row
   hd_profile_pic_url = _hd_profile_pic_url(row, path) if carries_hd_picture else None

   return ProfileSummary(
      id=_required_string(row, id_key, path),
      username=_required_string(row, "username", path),
      full_name=_required_string(row, "full_name", path),
      is_verified=_required_flag(row, "is_verified", path),
      profile_pic_url=_required_string(row, "profile_pic_url", path),
      is_private=_flag_if_carried(row, "is_private", path),
      hd_profile_pic_url=hd_profile_pic_url,
      friendship_status=_list_friendship_status(row, path),
   )


def parse_suggested_beside_profile(payload: Any) -> tuple[ProfileSummary, ...]:
   """One ``PolarisProfileSuggestedUsersWithLazyQueryQuery`` payload, the accounts in its order.

   The root carried ``users`` and no cursor or count on each of six answers, so the list is
   whole as sent.

   Finding: ``profile-suggested-users-on-demand``.
   """

   root = _object_at(payload, SUGGESTED_BESIDE_PROFILE_PATH)
   root_path = ".".join(SUGGESTED_BESIDE_PROFILE_PATH)
   users = _list_of(root, "users", root_path)

   return tuple(
      parse_profile_summary(user, f"{root_path}.users[{index}]") for index, user in enumerate(users)
   )


def parse_suggested_accounts(payload: Any) -> tuple[SuggestedAccount, ...]:
   """One ``PolarisSuggestedUserListQuery`` payload, every group's items in the upstream's order.

   Each of six answers held one group of five items. An item carried ``user``, ``social_context``
   (the reason line), ``uuid`` and ``social_context_facepile_users``; the last two are dropped,
   a tracking id and the small pictures of the accounts the reason names. The answer carried no
   cursor, so the list is whole as sent. More than one group has not been seen, and groups are
   read in order.

   Finding: ``home-suggested-accounts``.
   """

   root = _object_at(payload, SUGGESTED_ACCOUNTS_PATH)
   root_path = ".".join(SUGGESTED_ACCOUNTS_PATH)
   groups = _list_of(root, "groups", root_path)
   accounts: list[SuggestedAccount] = []

   for group_index, group in enumerate(groups):
      group_path = f"{root_path}.groups[{group_index}]"

      for item_index, item in enumerate(_list_of(group, "items", group_path)):
         item_path = f"{group_path}.items[{item_index}]"

         accounts.append(
            SuggestedAccount(
               account=parse_profile_summary(
                  _required(item, "user", item_path), f"{item_path}.user"
               ),
               reason=_required_string(item, "social_context", item_path),
            )
         )

   return tuple(accounts)


_FOLLOWERS = "<followers>"

_STATUSES = "<friendship statuses>"


def parse_followers_page(payload: Any) -> Page[ProfileSummary]:
   """One followers page, its accounts in the upstream's order, with the upstream's terminator.

   ``has_more`` says whether another page exists and ``next_max_id`` is the cursor that reaches
   it, a 120 character string on every page read. Both pages of both replays said ``has_more``
   true, the second with 7 accounts where 12 were asked for, so no last page has been read and
   what one carries is unobserved: ``next_max_id`` is read where the answer carries it and
   ``None`` where it is absent or null. A row carries no relationship; the statuses are a
   second request, attached by :func:`attach_friendship_statuses`.

   Dropped: ``groups`` and ``more_groups_available``, two groups shown above the list with a
   title and the small pictures of two accounts each, three of the four on the same page. The
   groups were empty on one of four first pages and absent from the next page. Also dropped are
   ``big_list``, ``page_size``,
   ``follow_ranking_token``, ``use_clickable_see_more``, ``show_spam_follow_request_tab`` and
   the two ``should_limit_list_of_*`` flags, which describe the list's chrome.

   Finding: ``read-an-account-s-followers``.
   """

   _raise_unless_ok(payload, "followers page")

   users = _list_of(payload, "users", _FOLLOWERS)
   has_more = _required_flag(payload, "has_more", _FOLLOWERS)
   carries_a_cursor = payload.get("next_max_id") is not None
   next_max_id = _required_string(payload, "next_max_id", _FOLLOWERS) if carries_a_cursor else None

   accounts = tuple(
      parse_profile_summary(user, f"{_FOLLOWERS}.users[{index}]")
      for index, user in enumerate(users)
   )

   return Page(items=accounts, has_next_page=has_more, end_cursor=next_max_id)


def parse_friendship_statuses(payload: Any) -> dict[str, ListFriendshipStatus]:
   """The viewer's relationship to each account asked about, keyed by account id.

   Every status read on 2026-09-27, 11 on each of four answers, carried the six flags
   :class:`ListFriendshipStatus` requires and neither ``followed_by`` nor ``blocking``, which
   are ``None``. Dropped: ``is_private``, which the followers row carries itself, and
   ``text_post_app_pre_following``, a flag about the Threads app.

   Finding: ``friendship-statuses-for-many-accounts``.
   """

   _raise_unless_ok(payload, "friendship statuses")

   statuses = _required(payload, "friendship_statuses", _STATUSES)
   statuses_path = f"{_STATUSES}.friendship_statuses"

   if not isinstance(statuses, dict):
      raise SchemaChanged(f"{statuses_path} is not an object", path=statuses_path)

   return {
      str(account_id): _read_list_friendship_status(raw, f"{statuses_path}.{account_id}")
      for account_id, raw in statuses.items()
   }


def attach_friendship_statuses(
   page: Page[ProfileSummary], statuses: Mapping[str, ListFriendshipStatus]
) -> Page[ProfileSummary]:
   """The page with each account's status filled in from ``statuses``, matched on its id.

   An account the answer does not name keeps ``None``. None was missing on any answer read.
   """

   accounts = tuple(
      replace(account, friendship_status=statuses.get(account.id, account.friendship_status))
      for account in page.items
   )

   return replace(page, items=accounts)
