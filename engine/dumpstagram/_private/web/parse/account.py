"""Map the viewer's own pending follow requests and activity feed into typed models.

Built from the answers ``probes/e2_own_account.py`` kept on 2026-09-27. Dropped, and why:

- on the follow requests, ``big_list``, false on both, ``page_size``, the count of the page,
  ``truncate_follow_requests_at_index`` and ``follow_ranking_token``, which shape the list's
  display, ``friend_requests``, an empty object, ``sections`` and ``global_blacklist_sample``,
  null, and ``suggested_users``, a suggestions block with no suggestion in it; on a row,
  ``fbid_v2``, ``strong_id__``, ``account_badges``, ``latest_reel_media``,
  ``has_anonymous_profile_picture`` and ``third_party_downloads_enabled``
- on the feed, ``continuation_token``, 0 on both reads, since no next page is read, and
  ``subscription``, null
- on an item, ``type``, which came with exactly one ``story_type`` for each of the nine kinds,
  ``rich_text``, which is ``text`` with each link written into it as markup and nothing more on
  all 69, ``images``, equal to ``media`` on all 69, ``inline_follow``'s own three flags, which
  repeat the account's relationship, ``comment_ids`` and ``comment_notif_type``,
  ``extra_actions``, the menu offered beside a line, ``latest_reel_media`` and
  ``latest_reel_seen_time``, the story ring around the avatar, the icon fields of the two items
  that carry an icon rather than an avatar, ``media_destination`` and
  ``profile_image_destination``, and the tracking fields ``af_candidate_id``,
  ``aggregation_type``, ``content_version_id``, ``tuuid``, ``logging_context``,
  ``indicator_config``, ``ndid``, ``trace_id``, ``generation_source`` and the item's own
  ``counts``, an empty object on all 69
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from dumpstagram._private.web.parse.common import (
   _required,
   _required_flag,
   _required_integer,
   _required_string,
)
from dumpstagram._private.web.parse.posting import _raise_unless_ok
from dumpstagram._private.web.parse.profiles import _list_of, parse_profile_summary
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import (
   ActivityCounts,
   ActivityFeed,
   ActivityItem,
   ActivityLink,
   ActivityMedia,
   ActivitySection,
   FollowRequests,
)

__all__ = ["parse_activity_feed", "parse_follow_requests"]

_REQUESTS = "<follow requests>"

_FEED = "<activity feed>"

_COUNTERS = (
   "likes",
   "comments",
   "comment_likes",
   "relationships",
   "requests",
   "usertags",
   "photos_of_you",
   "new_posts",
   "media_to_approve",
   "fundraiser",
   "promotional",
   "shopping_notification",
   "campaign_notification",
   "activity_feed_dot_badge",
   "activity_feed_dot_badge_only",
)


def parse_follow_requests(payload: Any) -> FollowRequests:
   """The accounts asking to follow the viewer, in the upstream's order.

   A row is the followers list's row family, except that ``pk`` arrives as a number, so the id
   is read from ``id``, the same value as a string on both rows read. ``has_more`` is
   ``next_max_id`` being present and not null; both answers carried it null.

   Finding: ``pending-follow-requests``.
   """

   _raise_unless_ok(payload, "follow requests")

   users = _list_of(payload, "users", _REQUESTS)
   accounts = tuple(
      parse_profile_summary(user, f"{_REQUESTS}.users[{index}]", id_key="id")
      for index, user in enumerate(users)
   )

   return FollowRequests(accounts=accounts, has_more=payload.get("next_max_id") is not None)


def _object(node: Any, key: str, path: str) -> dict[str, Any]:
   value = _required(node, key, path)

   if not isinstance(value, dict):
      raise SchemaChanged(f"{path}.{key} is not an object", path=f"{path}.{key}")

   return value


def _moment(node: Any, key: str, path: str) -> datetime:
   value = _required(node, key, path)
   is_a_number = isinstance(value, int | float) and not isinstance(value, bool)

   if not is_a_number:
      raise SchemaChanged(f"{path}.{key} is not a number", path=f"{path}.{key}")

   return datetime.fromtimestamp(value, tz=UTC)


def _string_if_carried(node: dict[str, Any], key: str, path: str) -> str | None:
   value = node.get(key)

   if value is None:
      return None

   if not isinstance(value, str):
      raise SchemaChanged(f"{path}.{key} is not a string", path=f"{path}.{key}")

   return value


def _parse_link(raw: Any, path: str) -> ActivityLink:
   return ActivityLink(
      start=_required_integer(raw, "start", path),
      end=_required_integer(raw, "end", path),
      kind=_required_string(raw, "type", path),
      id=_required_string(raw, "id", path),
      username=_required_string(raw, "username", path),
   )


def _parse_media(raw: Any, path: str) -> ActivityMedia:
   return ActivityMedia(
      id=_required_string(raw, "id", path),
      shortcode=_required_string(raw, "shortcode", path),
      image_url=_required_string(raw, "image", path),
   )


def _parse_item(raw: Any, path: str) -> ActivityItem:
   args = _object(raw, "args", path)
   args_path = f"{path}.args"
   carries_links = "links" in args
   carries_media = "media" in args
   carries_a_follow_button = "inline_follow" in args

   links = _list_of(args, "links", args_path) if carries_links else []
   media = _list_of(args, "media", args_path) if carries_media else []
   follow_account = None

   if carries_a_follow_button:
      follow_path = f"{args_path}.inline_follow"
      follow = _object(args, "inline_follow", args_path)
      follow_account = parse_profile_summary(
         _object(follow, "user_info", follow_path), f"{follow_path}.user_info"
      )

   return ActivityItem(
      id=_required_string(raw, "pk", path),
      kind=_required_string(raw, "notif_name", path),
      story_type=_required_integer(raw, "story_type", path),
      created_at=_moment(args, "timestamp", args_path),
      text=_required_string(args, "text", args_path),
      links=tuple(
         _parse_link(link, f"{args_path}.links[{index}]") for index, link in enumerate(links)
      ),
      media=tuple(
         _parse_media(entry, f"{args_path}.media[{index}]") for index, entry in enumerate(media)
      ),
      account_id=_string_if_carried(args, "profile_id", args_path),
      account_username=_string_if_carried(args, "profile_name", args_path),
      account_pic_url=_string_if_carried(args, "profile_image", args_path),
      second_account_id=_string_if_carried(args, "second_profile_id", args_path),
      second_account_pic_url=_string_if_carried(args, "second_profile_image", args_path),
      follow_account=follow_account,
      comment_id=_string_if_carried(args, "comment_id", args_path),
      destination=_string_if_carried(args, "destination", args_path),
   )


def _parse_items(payload: Any, key: str) -> tuple[ActivityItem, ...]:
   return tuple(
      _parse_item(raw, f"{_FEED}.{key}[{index}]")
      for index, raw in enumerate(_list_of(payload, key, _FEED))
   )


def _parse_sections(payload: Any) -> tuple[ActivitySection, ...]:
   bucket_path = f"{_FEED}.partition.time_bucket"
   bucket = _object(_object(payload, "partition", _FEED), "time_bucket", f"{_FEED}.partition")
   titles = _list_of(bucket, "headers", bucket_path)
   indices = _list_of(bucket, "indices", bucket_path)
   lengths_match = len(titles) == len(indices)
   every_title_is_text = all(isinstance(title, str) for title in titles)
   every_index_is_whole = all(
      isinstance(index, int) and not isinstance(index, bool) for index in indices
   )
   is_well_formed = lengths_match and every_title_is_text and every_index_is_whole

   if not is_well_formed:
      raise SchemaChanged(
         f"{bucket_path} does not pair a title with a whole index", path=bucket_path
      )

   return tuple(
      ActivitySection(title=title, first_index=index)
      for title, index in zip(titles, indices, strict=True)
   )


def parse_activity_feed(payload: Any) -> ActivityFeed:
   """One ``news/inbox`` answer, every list in the upstream's order.

   Every earlier item read carried ``pk``, ``notif_name``, ``story_type`` and, under ``args``,
   ``timestamp`` as a float of seconds and ``text``; the rest is read where the item carries it
   and ``None`` or empty where it does not. A link's ``id`` and the account ids are strings.

   Finding: ``activity-feed-inbox``.
   """

   _raise_unless_ok(payload, "activity feed")

   counts = _object(payload, "counts", _FEED)
   counts_path = f"{_FEED}.counts"

   return ActivityFeed(
      new_items=_parse_items(payload, "new_stories"),
      earlier_items=_parse_items(payload, "old_stories"),
      priority_items=_parse_items(payload, "priority_stories"),
      counts=ActivityCounts(
         **{name: _required_integer(counts, name, counts_path) for name in _COUNTERS}
      ),
      sections=_parse_sections(payload),
      last_checked_at=_moment(payload, "last_checked", _FEED),
      is_last_page=_required_flag(payload, "is_last_page", _FEED),
   )
