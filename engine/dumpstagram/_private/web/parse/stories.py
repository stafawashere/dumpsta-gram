"""Map the stories tray, one account's live stories and one highlight into typed models, and read
the seen mutation's answer.

Built from the answers ``probes/e2_stories.py`` kept on 2026-09-27. Dropped, and why:

- on a tray row, ``__typename`` XDTReelDict, ``latest_besties_reel_media``, which was a time on
  rows whose ``has_besties_media`` was false, ``latest_wearables_reel_media_long`` and
  ``unseen_wearables_media_igids``, zero and empty on all 33, ``seen_ranked_position``, equal to
  ``ranked_position`` on all 33, and the owner's ``latest_reel_media``,
  ``reel_media_seen_timestamp``, ``is_unpublished`` and the two live broadcast fields, which
  repeat the row or were null; beside the tray, ``broadcasts``, empty, the suggested accounts
  under ``ayml``, which the variables ask to show none of, and ``xdt_viewer``
- on a reel, ``seen`` and ``muted``, null on the highlight, and on the live reel of W121 ``seen``
  zero and ``muted`` null, since the tray row carries both, ``unviewable_authors_infos``, empty,
  and the owner's ``aigm_account_label_info``, ``interop_messaging_user_fbid``, three
  transparency fields and, on the live reel only, ``friendship_status``, which a profile read
  carries
- on an item, every field null on all 18 (``caption``, ``accessibility_caption``, ``link``,
  ``story_link_stickers``, ``story_locations``, ``story_hashtags``, ``story_questions``,
  ``story_sliders``, ``story_countdowns``, ``story_cta`` and the rest), ``viewers``, an empty
  list on every item and a list of other people where it is not, ``video_dash_manifest``, since
  ``video_duration`` is sent, ``organic_tracking_token``, ``ai_label_info``,
  ``sharing_friction_info``, and flags false on all 18 that no reader needs; on the live item
  of W121, ``has_liked``, null on every highlight item and false there, left until the story
  like write of E3 can confirm what it reads, and the place and size of the shared media
  sticker

``probes/live_reel_shape.py`` read the first live reel of another account twice on 2026-09-27.
It carried every reel and item key the highlight carried and no other; ``title`` and
``cover_media`` were null where the highlight sent a name and a cover, and the item's
``story_feed_media`` named the reel it shares.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from dumpstagram._private.web.parse.common import (
   _hd_profile_pic_url,
   _object_at,
   _optional_flag,
   _optional_string,
   _required,
   _required_flag,
   _required_integer,
   _required_string,
)
from dumpstagram.errors import NotFound, SchemaChanged
from dumpstagram.models import (
   MediaImage,
   StoryItem,
   StoryMention,
   StoryMusic,
   StoryOwner,
   StoryReel,
   StorySharedMedia,
   StoryVideo,
   TrayReel,
)

__all__ = [
   "REELS_MEDIA_PATH",
   "SEEN_ANSWER_ROOT",
   "SEEN_ANSWER_TYPE",
   "STORIES_TRAY_PATH",
   "parse_highlight_reel",
   "parse_stories_tray",
   "parse_story_reel",
   "story_was_marked_seen",
]

SEEN_ANSWER_ROOT = "xdt_mark_story_reel_seen"
"""The root field the seen mutation answers under."""

SEEN_ANSWER_TYPE = "XDTMarkSeenResponse"
"""The ``__typename`` of that root on the browser's answer and the engine's, the only field it
carried on either."""

STORIES_TRAY_PATH = ("data", "xdt_api__v1__feed__reels_tray")
"""The path to the tray in a ``PolarisStoriesV3TrayContainerQuery`` payload, which carries
``tray`` and ``broadcasts``."""

REELS_MEDIA_PATH = ("data", "xdt_api__v1__feed__reels_media")
"""The path to the reels in a ``PolarisStoriesV3ReelPageStandaloneQuery`` payload, which carries
``reels_media`` and ``unviewable_authors_infos``."""


def _list_of(node: Any, key: str, path: str) -> list[Any]:
   value = _required(node, key, path)

   if not isinstance(value, list):
      raise SchemaChanged(f"{path}.{key} is not a list", path=f"{path}.{key}")

   return value


def _objects_or_none(node: dict[str, Any], key: str, path: str) -> list[dict[str, Any]]:
   """A list the upstream sends as null when it is empty, each entry an object."""

   value = _required(node, key, path)

   if value is None:
      return []

   if not isinstance(value, list):
      raise SchemaChanged(f"{path}.{key} is not a list or null", path=f"{path}.{key}")

   for index, entry in enumerate(value):
      if not isinstance(entry, dict):
         raise SchemaChanged(f"{path}.{key}[{index}] is not an object", path=f"{path}.{key}")

   return value


def _time(node: Any, key: str, path: str) -> datetime:
   """Whole seconds since the Unix epoch, as every time a story carries arrives."""

   return datetime.fromtimestamp(_required_integer(node, key, path), tz=UTC)


def _as_object(node: Any, path: str) -> dict[str, Any]:
   if not isinstance(node, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

   return node


def _owner(node: dict[str, Any], path: str) -> StoryOwner:
   owner_path = f"{path}.user"
   owner = _as_object(_required(node, "user", path), owner_path)
   carries_verified = "is_verified" in owner
   carries_private = "is_private" in owner
   carries_hd_picture = "hd_profile_pic_url_info" in owner
   is_verified = _optional_flag(owner, "is_verified", owner_path) if carries_verified else None
   is_private = _optional_flag(owner, "is_private", owner_path) if carries_private else None
   hd_picture = _hd_profile_pic_url(owner, owner_path) if carries_hd_picture else None

   return StoryOwner(
      id=_required_string(owner, "pk", owner_path),
      username=_required_string(owner, "username", owner_path),
      profile_pic_url=_required_string(owner, "profile_pic_url", owner_path),
      is_verified=is_verified,
      is_private=is_private,
      hd_profile_pic_url=hd_picture,
   )


def _tray_reel(row: Any, path: str) -> TrayReel:
   row = _as_object(row, path)
   seen = _required_integer(row, "seen", path)
   never_seen = seen == 0

   return TrayReel(
      id=_required_string(row, "id", path),
      reel_type=_required_string(row, "reel_type", path),
      owner=_owner(row, path),
      latest_item_at=_time(row, "latest_reel_media", path),
      expiring_at=_time(row, "expiring_at", path),
      ranked_position=_required_integer(row, "ranked_position", path),
      muted=_required_flag(row, "muted", path),
      has_close_friends_items=_required_flag(row, "has_besties_media", path),
      seen_at=None if never_seen else datetime.fromtimestamp(seen, tz=UTC),
   )


def parse_stories_tray(payload: Any) -> tuple[TrayReel, ...]:
   """One ``PolarisStoriesV3TrayContainerQuery`` payload, the tray's rows in its order.

   Finding: ``page-load-stories-tray``.
   """

   tray = _object_at(payload, STORIES_TRAY_PATH)
   tray_path = ".".join(STORIES_TRAY_PATH)
   rows = _list_of(tray, "tray", tray_path)

   return tuple(_tray_reel(row, f"{tray_path}.tray[{index}]") for index, row in enumerate(rows))


def _images(item: dict[str, Any], path: str) -> tuple[MediaImage, ...]:
   wrapper_path = f"{path}.image_versions2"
   wrapper = _as_object(_required(item, "image_versions2", path), wrapper_path)
   candidates = _list_of(wrapper, "candidates", wrapper_path)
   built: list[MediaImage] = []

   for index, entry in enumerate(candidates):
      entry_path = f"{wrapper_path}.candidates[{index}]"

      built.append(
         MediaImage(
            url=_required_string(entry, "url", entry_path),
            width=_required_integer(entry, "width", entry_path),
            height=_required_integer(entry, "height", entry_path),
         )
      )

   return tuple(built)


def _videos(item: dict[str, Any], path: str) -> tuple[StoryVideo, ...]:
   versions = _objects_or_none(item, "video_versions", path)

   return tuple(
      StoryVideo(
         url=_required_string(entry, "url", f"{path}.video_versions[{index}]"),
         version_type=_required_integer(entry, "type", f"{path}.video_versions[{index}]"),
      )
      for index, entry in enumerate(versions)
   )


def _video_duration(item: dict[str, Any], path: str) -> float | None:
   raw = _required(item, "video_duration", path)

   if raw is None:
      return None

   is_a_number = isinstance(raw, int | float) and not isinstance(raw, bool)

   if not is_a_number:
      raise SchemaChanged(
         f"{path}.video_duration is not a number or null", path=f"{path}.video_duration"
      )

   return float(raw)


def _mentions(item: dict[str, Any], path: str) -> tuple[StoryMention, ...]:
   """The mention stickers among the item's bloks stickers. A bloks sticker that is not a
   mention has not been seen, and one arriving raises rather than being skipped."""

   built: list[StoryMention] = []

   for index, sticker in enumerate(_objects_or_none(item, "story_bloks_stickers", path)):
      sticker_path = f"{path}.story_bloks_stickers[{index}]"
      mention = _object_at(sticker, ("bloks_sticker", "sticker_data", "ig_mention"))
      mention_path = f"{sticker_path}.bloks_sticker.sticker_data.ig_mention"

      built.append(
         StoryMention(
            username=_required_string(mention, "username", mention_path),
            full_name=_required_string(mention, "full_name", mention_path),
         )
      )

   return tuple(built)


def _music(item: dict[str, Any], path: str) -> tuple[StoryMusic, ...]:
   built: list[StoryMusic] = []

   for index, sticker in enumerate(_objects_or_none(item, "story_music_stickers", path)):
      asset = _object_at(sticker, ("music_asset_info",))
      asset_path = f"{path}.story_music_stickers[{index}].music_asset_info"

      built.append(
         StoryMusic(
            title=_required_string(asset, "title", asset_path),
            artist=_required_string(asset, "display_artist", asset_path),
            should_mute=_required_flag(asset, "should_mute_audio", asset_path),
         )
      )

   return tuple(built)


def _shared_media(item: dict[str, Any], path: str) -> tuple[StorySharedMedia, ...]:
   """The post or reel the item shares, null on every highlight item and one reel on the live
   item read (W121)."""

   built: list[StorySharedMedia] = []

   for index, entry in enumerate(_objects_or_none(item, "story_feed_media", path)):
      entry_path = f"{path}.story_feed_media[{index}]"

      built.append(
         StorySharedMedia(
            id=_required_string(entry, "id", entry_path),
            code=_required_string(entry, "media_code", entry_path),
            product_type=_required_string(entry, "product_type", entry_path),
         )
      )

   return tuple(built)


def _item(node: Any, path: str) -> StoryItem:
   item = _as_object(node, path)
   owner = _as_object(_required(item, "user", path), f"{path}.user")

   return StoryItem(
      id=_required_string(item, "id", path),
      pk=_required_string(item, "pk", path),
      code=_required_string(item, "code", path),
      owner_id=_required_string(owner, "pk", f"{path}.user"),
      media_type=_required_integer(item, "media_type", path),
      product_type=_required_string(item, "product_type", path),
      taken_at=_time(item, "taken_at", path),
      expiring_at=_time(item, "expiring_at", path),
      original_width=_required_integer(item, "original_width", path),
      original_height=_required_integer(item, "original_height", path),
      can_reply=_required_flag(item, "can_reply", path),
      can_reshare=_required_flag(item, "can_reshare", path),
      is_paid_partnership=_required_flag(item, "is_paid_partnership", path),
      is_story_edited=_required_flag(item, "is_story_edited", path),
      images=_images(item, path),
      videos=_videos(item, path),
      video_duration=_video_duration(item, path),
      has_audio=_optional_flag(item, "has_audio", path),
      audience=_optional_string(item, "audience", path),
      mentions=_mentions(item, path),
      music=_music(item, path),
      shared_media=_shared_media(item, path),
   )


def _cover_url(reel: dict[str, Any], path: str) -> str | None:
   """A highlight's cover. A live reel sends ``cover_media`` as null (W121)."""

   carries_no_cover = reel.get("cover_media") is None

   if carries_no_cover:
      return None

   cover = _object_at(reel, ("cover_media", "cropped_image_version"))

   return _required_string(cover, "url", f"{path}.cover_media.cropped_image_version")


def _reel(node: Any, path: str) -> StoryReel:
   reel = _as_object(node, path)
   items = _list_of(reel, "items", path)
   carries_title = "title" in reel
   title = _optional_string(reel, "title", path) if carries_title else None

   return StoryReel(
      id=_required_string(reel, "id", path),
      reel_type=_required_string(reel, "reel_type", path),
      owner=_owner(reel, path),
      latest_item_at=_time(reel, "latest_reel_media", path),
      can_reshare=_required_flag(reel, "can_reshare", path),
      items=tuple(_item(item, f"{path}.items[{index}]") for index, item in enumerate(items)),
      title=title,
      cover_url=_cover_url(reel, path),
   )


def _reels(payload: Any) -> list[Any]:
   answer = _object_at(payload, REELS_MEDIA_PATH)

   return _list_of(answer, "reels_media", ".".join(REELS_MEDIA_PATH))


def _one_reel_at_most(payload: Any) -> Any | None:
   reels = _reels(payload)
   answers_more_than_one = len(reels) > 1

   if answers_more_than_one:
      path = ".".join(REELS_MEDIA_PATH)

      raise SchemaChanged(
         f"{path}.reels_media held {len(reels)} reels for one id", path=f"{path}.reels_media"
      )

   return reels[0] if reels else None


def parse_story_reel(payload: Any) -> StoryReel | None:
   """One account's live stories from a ``PolarisStoriesV3ReelPageStandaloneQuery`` payload,
   ``None`` when ``reels_media`` is empty, which is how the owner's reel answered with no live
   story. More than one reel for the one id asked raises.

   Finding: ``read-one-account-s-stories-or-a-highlight``.
   """

   reel = _one_reel_at_most(payload)

   if reel is None:
      return None

   return _reel(reel, f"{'.'.join(REELS_MEDIA_PATH)}.reels_media[0]")


def parse_highlight_reel(payload: Any) -> StoryReel:
   """One highlight from a ``PolarisStoriesV3ReelPageStandaloneQuery`` payload.

   An empty ``reels_media`` raises :class:`~dumpstagram.errors.NotFound`. The one highlight read
   answered one reel both times, and what the upstream answers for a highlight that does not
   exist is unobserved, so reading no reel as a missing highlight is an INFERENCE.

   Finding: ``read-one-account-s-stories-or-a-highlight``.
   """

   reel = _one_reel_at_most(payload)

   if reel is None:
      raise NotFound("the upstream answered no reel for that highlight")

   return _reel(reel, f"{'.'.join(REELS_MEDIA_PATH)}.reels_media[0]")


def story_was_marked_seen(payload: Any) -> bool:
   """Whether a seen mutation's answer says the item was marked, from
   ``data.xdt_mark_story_reel_seen``.

   Both observed answers, the browser's and the engine's on 2026-09-27, carried that root as an
   object whose only field was ``__typename`` ``XDTMarkSeenResponse``, and a highlight read
   carries no seen field to check it against, so the answer is the only confirmation there is.
   A null root is False, never observed, and read as not marked because a write answered with
   nothing did not confirm itself. A missing root, or a root of another type, is a schema change.
   """

   data = _object_at(payload, ("data",))
   root = _required(data, SEEN_ANSWER_ROOT, "data")

   if root is None:
      return False

   root_path = f"data.{SEEN_ANSWER_ROOT}"

   if not isinstance(root, dict):
      raise SchemaChanged(f"{root_path} is not an object or null", path=root_path)

   typename = _required_string(root, "__typename", root_path)
   is_the_seen_answer = typename == SEEN_ANSWER_TYPE

   if not is_the_seen_answer:
      raise SchemaChanged(
         f"{root_path}.__typename is {typename!r}, not {SEEN_ANSWER_TYPE!r}",
         path=f"{root_path}.__typename",
      )

   return True
