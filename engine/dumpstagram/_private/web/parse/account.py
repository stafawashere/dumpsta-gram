"""Map the viewer's own pending follow requests, activity feed, saved posts and collections,
and close friends list into typed models.

Built from the answers ``probes/e2_own_account.py`` kept on 2026-09-27, and for the saved reads
and the close friends list those ``probes/e2_capture_replays.py`` kept the same day. Dropped, and
why:

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
- on the saved posts, ``num_results``, the page's length, ``next_max_id``, which no request here
  sends back (W105), ``auto_load_more_enabled``, and on an item everything the explore grid's
  post mapper drops, and ``has_viewer_saved``, true on all 42, ``view_count``, ``play_count``,
  ``ig_play_count`` and ``expiring_at``, carried on some items and not others
- on a saved collection, ``__isXDTSavedCollectionItem``, which repeats ``__typename``,
  ``cover_media``, null on both rows read, and each edge's ``cursor``
- on the close friends screen, every row the screen offers to add, the accounts that are not close
  friends, and the whole UI tree around the rows (W107)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from dumpstagram._private.web.parse.bloks import (
   BloksAtom,
   BloksCall,
   BloksValue,
   read_bloks_script,
)
from dumpstagram._private.web.parse.common import (
   _object_at,
   _optional_integer,
   _optional_string,
   _required,
   _required_flag,
   _required_integer,
   _required_string,
)
from dumpstagram._private.web.parse.discovery import _absent_as_null
from dumpstagram._private.web.parse.media import (
   _audio,
   _caption_text,
   _carousel_children,
   _collaborators,
   _duration_if_video,
   _images,
   _location,
   _post_author,
   _taken_at,
   _user_tags,
   _videos,
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
   CollectionCover,
   FollowRequests,
   ProfileSummary,
   SavedCollection,
   SavedCollectionKind,
   SavedCollections,
   SavedPost,
   SavedPosts,
)

__all__ = [
   "SAVED_COLLECTIONS_PATH",
   "parse_activity_feed",
   "parse_close_friends",
   "parse_follow_requests",
   "parse_saved_collections",
   "parse_saved_posts",
]

SAVED_COLLECTIONS_PATH = ("data", "viewer", "collections_unified_with_auto_collections")
"""The path to the saved tab's connection."""

_SAVED = "<saved posts>"

_BLOKS_PAYLOAD_PATH = ("payload", "layout", "bloks_payload")

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


def _flag_if_carried(node: dict[str, Any], key: str, path: str) -> bool | None:
   if key not in node:
      return None

   return _required_flag(node, key, path)


def _saved_post(entry: Any, path: str) -> SavedPost:
   """One item of the saved view, its REST media read as the explore grid reads it (W77), with
   no comment count, which the view never sends, and no ``is_seen``."""

   media_path = f"{path}.media"
   node = _absent_as_null(_required(entry, "media", path))

   if not isinstance(node, dict):
      raise SchemaChanged(f"{media_path} is not an object", path=media_path)

   videos = _videos(node, media_path)

   return SavedPost(
      id=_required_string(node, "id", media_path),
      pk=_required_string(node, "pk", media_path),
      code=_required_string(node, "code", media_path),
      taken_at=_taken_at(node, media_path),
      author=_post_author(node, media_path),
      media_type=_required_integer(node, "media_type", media_path),
      product_type=_required_string(node, "product_type", media_path),
      like_count=_required_integer(node, "like_count", media_path),
      has_liked=_required_flag(node, "has_liked", media_path),
      caption=_caption_text(node, media_path),
      accessibility_caption=_optional_string(node, "accessibility_caption", media_path),
      original_width=_optional_integer(node, "original_width", media_path),
      original_height=_optional_integer(node, "original_height", media_path),
      carousel_media_count=_optional_integer(node, "carousel_media_count", media_path),
      images=_images(node, media_path),
      is_paid_partnership=_required_flag(node, "is_paid_partnership", media_path),
      like_and_view_counts_disabled=_flag_if_carried(
         node, "like_and_view_counts_disabled", media_path
      ),
      videos=videos,
      video_duration=_duration_if_video(node, videos, media_path),
      has_audio=_optional_flag_or_absent(node, "has_audio", media_path),
      audio=_audio(node, media_path),
      carousel_children=_carousel_children(node, media_path),
      location=_location(node, media_path),
      user_tags=_user_tags(node, media_path),
      collaborators=_collaborators(node, media_path),
   )


def _optional_flag_or_absent(node: dict[str, Any], key: str, path: str) -> bool | None:
   value = node.get(key)

   if value is None:
      return None

   if not isinstance(value, bool):
      raise SchemaChanged(f"{path}.{key} is not a boolean or null", path=f"{path}.{key}")

   return value


def parse_saved_posts(payload: Any) -> SavedPosts:
   """The first page of the saved "All posts" view, in the upstream's order.

   ``has_more`` is ``more_available``, true on both answers read.

   Finding: ``read-all-saved-posts``.
   """

   _raise_unless_ok(payload, "saved posts")

   items = _list_of(payload, "items", _SAVED)
   posts = tuple(_saved_post(item, f"{_SAVED}.items[{index}]") for index, item in enumerate(items))

   return SavedPosts(posts=posts, has_more=_required_flag(payload, "more_available", _SAVED))


def _collection_kind(node: dict[str, Any], path: str) -> SavedCollectionKind:
   typename = _required_string(node, "__typename", path)
   known = {
      kind.value: kind for kind in SavedCollectionKind if kind is not SavedCollectionKind.OTHER
   }

   return known.get(typename, SavedCollectionKind.OTHER)


def _covers_of(node: dict[str, Any], key: str, path: str) -> list[Any]:
   """A cover list, empty when the row does not carry it, which the audio collection's row did
   not for ``cover_media_list``."""

   if key not in node:
      return []

   return _list_of(node, key, path)


def _media_cover(raw: Any, path: str) -> CollectionCover:
   versions = _object_at(raw, ("image_versions2",))
   candidates = _list_of(versions, "candidates", f"{path}.image_versions2")
   urls = tuple(
      _required_string(candidate, "url", f"{path}.image_versions2.candidates[{index}]")
      for index, candidate in enumerate(candidates)
   )

   return CollectionCover(media_id=_required_string(raw, "id", path), image_urls=urls)


def _audio_cover(raw: Any, path: str) -> CollectionCover:
   return CollectionCover(media_id=None, image_urls=(_required_string(raw, "thumbnail_uri", path),))


def _saved_collection(edge: Any, path: str) -> SavedCollection:
   node = _object_at(edge, ("node",))
   node_path = f"{path}.node"
   media_covers = _covers_of(node, "cover_media_list", node_path)
   audio_covers = _covers_of(node, "cover_audio_list", node_path)
   covers = tuple(
      _media_cover(raw, f"{node_path}.cover_media_list[{index}]")
      for index, raw in enumerate(media_covers)
   ) + tuple(
      _audio_cover(raw, f"{node_path}.cover_audio_list[{index}]")
      for index, raw in enumerate(audio_covers)
   )

   return SavedCollection(
      id=_required_string(node, "collection_id", node_path),
      name=_required_string(node, "collection_name", node_path),
      kind=_collection_kind(node, node_path),
      media_count=_optional_integer(node, "collection_media_count", node_path),
      covers=covers,
   )


def parse_saved_collections(payload: Any) -> SavedCollections:
   """The saved tab's first page, the collections in the upstream's order.

   A row of a type not read is kept as :attr:`SavedCollectionKind.OTHER` rather than refused,
   since a collection the viewer named is the tab's ordinary content and its type name was not
   observed (W106); it must still carry every key both rows read carried.

   Finding: ``read-saved-posts``.
   """

   connection = _object_at(payload, SAVED_COLLECTIONS_PATH)
   connection_path = ".".join(SAVED_COLLECTIONS_PATH)
   edges = _list_of(connection, "edges", connection_path)
   collections = tuple(
      _saved_collection(edge, f"{connection_path}.edges[{index}]")
      for index, edge in enumerate(edges)
   )
   page_info = _object_at(connection, ("page_info",))

   return SavedCollections(
      collections=collections,
      has_more=_required_flag(page_info, "has_next_page", f"{connection_path}.page_info"),
   )


def _bloks_schema_changed(message: str, path: str) -> SchemaChanged:
   return SchemaChanged(f"{path} {message}", path=path)


def _call_named(value: BloksValue | None, name: str) -> BloksCall | None:
   """``value`` when it is a call to ``name``, else ``None``."""

   if isinstance(value, BloksCall) and value.name == name:
      return value

   return None


def _only_argument(call: BloksCall | None) -> BloksValue | None:
   if call is None or len(call.arguments) != 1:
      return None

   return call.arguments[0]


def _calls_in(value: BloksValue) -> list[BloksCall]:
   """Every call inside ``value``, itself first, depth first."""

   if not isinstance(value, BloksCall):
      return []

   found = [value]

   for argument in value.arguments:
      found.extend(_calls_in(argument))

   return found


def _components_in(value: Any) -> list[dict[str, Any]]:
   """Every object of the UI tree that carries a string ``on_bind``, depth first."""

   found: list[dict[str, Any]] = []

   if isinstance(value, dict):
      if isinstance(value.get("on_bind"), str):
         found.append(value)

      for inner in value.values():
         found.extend(_components_in(inner))
   elif isinstance(value, list):
      for inner in value:
         found.extend(_components_in(inner))

   return found


def _bloks_variables(bloks_payload: dict[str, Any], path: str) -> dict[str, str]:
   """Each data entry's id and the script of its initial value."""

   entries = _list_of(bloks_payload, "data", path)
   variables: dict[str, str] = {}

   for index, entry in enumerate(entries):
      entry_path = f"{path}.data[{index}]"
      entry_id = _required_string(entry, "id", entry_path)
      data = _object_at(entry, ("data",))
      variables[entry_id] = _required_string(data, "initial_lispy", f"{entry_path}.data")

   return variables


def _mapped_list_variable(on_bind: BloksValue) -> str | None:
   """The variable a component's rows are mapped from, when its binding maps one into its
   children, as both lists of the close friends screen did."""

   for call in _calls_in(on_bind):
      mapping = _call_named(call, "bk.action.array.Map")
      source = mapping.arguments[0] if mapping is not None and mapping.arguments else None
      variable = _only_argument(_call_named(source, "bk.action.bloks.GetVariable2"))

      if isinstance(variable, str):
         return variable

   return None


def _selected_variables(templates: Any, path: str) -> set[str]:
   """The variables the row templates bind their ``selected`` state to."""

   found: set[str] = set()

   for component in _components_in(templates):
      script = component["on_bind"]

      if '"selected"' not in script:
         continue

      for call in _calls_in(read_bloks_script(script, f"{path}.on_bind")):
         for argument, following in zip(call.arguments, call.arguments[1:], strict=False):
            state = _call_named(following, "bk.action.bloks.GetVariableWithScope")
            variable = state.arguments[0] if state is not None and state.arguments else None
            binds_selected = argument == "selected" and isinstance(variable, str)

            if binds_selected and isinstance(variable, str):
               found.add(variable)

   return found


def _constant_atom(value: BloksValue | None, names: tuple[str, ...]) -> str | None:
   """The bare word of a one-argument constant call to one of ``names``, else ``None``."""

   if not isinstance(value, BloksCall) or value.name not in names:
      return None

   atom = _only_argument(value)

   return atom.text if isinstance(atom, BloksAtom) else None


def _constant_flag(script: str, path: str) -> bool:
   flag = _constant_atom(read_bloks_script(script, path), ("bk.action.bool.Const",))

   if flag not in ("true", "false"):
      raise _bloks_schema_changed("is not a constant boolean", path)

   return flag == "true"


def _row_string(row: dict[str, BloksValue], key: str, path: str) -> str:
   value = row.get(key)

   if not isinstance(value, str):
      raise _bloks_schema_changed(f"carries no {key} string", path)

   return value


def _row_fields(row: BloksValue, path: str) -> dict[str, BloksValue]:
   """A row's keys and values, from a map made of a key array and a value array."""

   mapping = _call_named(row, "bk.action.map.Make")
   parts = mapping.arguments if mapping is not None else ()
   keys = _call_named(parts[0], "bk.action.array.Make") if len(parts) == 2 else None
   values = _call_named(parts[1], "bk.action.array.Make") if len(parts) == 2 else None

   if keys is None or values is None:
      raise _bloks_schema_changed("is not a map of keys to values", path)

   names = [key for key in keys.arguments if isinstance(key, str)]
   is_well_formed = len(names) == len(keys.arguments) == len(values.arguments)

   if not is_well_formed:
      raise _bloks_schema_changed("is not a map of keys to values", path)

   return dict(zip(names, values.arguments, strict=True))


def _close_friend(row: BloksValue, path: str) -> ProfileSummary:
   """One row of the list, the five keys every row read carried: ``user_id`` as a 64 or 32 bit
   constant, ``username``, ``name``, ``profile_pic_url`` and ``is_verified``."""

   fields = _row_fields(row, path)
   user_id = _constant_atom(fields.get("user_id"), ("bk.action.i64.Const", "bk.action.i32.Const"))
   verified = _constant_atom(fields.get("is_verified"), ("bk.action.bool.Const",))
   is_a_real_id = user_id is not None and user_id.isdigit()
   is_a_real_flag = verified in ("true", "false")

   if not (is_a_real_id and is_a_real_flag) or user_id is None:
      raise _bloks_schema_changed("carries no user_id or is_verified the engine can read", path)

   return ProfileSummary(
      id=user_id,
      username=_row_string(fields, "username", path),
      full_name=_row_string(fields, "name", path),
      is_verified=verified == "true",
      profile_pic_url=_row_string(fields, "profile_pic_url", path),
   )


def parse_close_friends(payload: Any) -> tuple[ProfileSummary, ...]:
   """The viewer's close friends, in the order the settings screen lists them.

   The screen is a Bloks tree, not a list. It carries two lists of accounts, each a data entry
   mapped into rows whose ``selected`` state is bound to a variable of its own: the close friends,
   whose rows start selected, and the accounts offered to add, whose rows do not. Both were read
   this way on all four answers, two replays and two browser fetches, the component ids differing
   on each, so the lists are found by that structure and never by id (W107). Anything else, a
   third list, two selected lists or none, a row that is not the five keys every row carried,
   raises :class:`~dumpstagram.errors.SchemaChanged` rather than returning a guess.

   Finding: ``read-the-close-friends-list``.
   """

   bloks_payload = _object_at(payload, _BLOKS_PAYLOAD_PATH)
   bloks_path = ".".join(_BLOKS_PAYLOAD_PATH)
   variables = _bloks_variables(bloks_payload, bloks_path)
   tree = _required(bloks_payload, "tree", bloks_path)
   tree_path = f"{bloks_path}.tree"
   selected_lists: list[str] = []
   list_count = 0

   for component in _components_in(tree):
      script = component["on_bind"]

      if "bk.action.array.Map" not in script:
         continue

      list_variable = _mapped_list_variable(read_bloks_script(script, f"{tree_path}.on_bind"))

      if list_variable is None:
         continue

      list_count += 1
      selected = _selected_variables(component.get("child_templates"), tree_path)
      selected_variable = next(iter(selected)) if len(selected) == 1 else ""
      binds_known_variables = selected_variable in variables and list_variable in variables

      if not binds_known_variables:
         raise _bloks_schema_changed(
            "maps a list whose rows bind no single known selected state", tree_path
         )

      starts_selected = _constant_flag(
         variables[selected_variable], f"{bloks_path}.data[{selected_variable}]"
      )

      if starts_selected:
         selected_lists.append(list_variable)

   is_one_selected_list_of_two = list_count == 2 and len(selected_lists) == 1

   if not is_one_selected_list_of_two:
      raise _bloks_schema_changed(
         f"carries {list_count} lists of accounts, {len(selected_lists)} of them selected, "
         "where the screen read carried two with one selected",
         tree_path,
      )

   list_path = f"{bloks_path}.data[{selected_lists[0]}]"
   rows = _call_named(
      read_bloks_script(variables[selected_lists[0]], list_path), "bk.action.array.Make"
   )

   if rows is None:
      raise _bloks_schema_changed("is not an array of rows", list_path)

   return tuple(
      _close_friend(row, f"{list_path}[{index}]") for index, row in enumerate(rows.arguments)
   )
