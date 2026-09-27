"""Map a post payload: a post, a post read on its own by shortcode or by media pk, a like answer,
comments and their replies, the likers, and the more posts from the author."""

from __future__ import annotations

import re
from datetime import UTC, datetime
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
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import (
   AudioKind,
   CarouselChild,
   Comment,
   CommentAuthor,
   Location,
   MediaAudio,
   MediaImage,
   Page,
   Post,
   PostAuthor,
   PostDetail,
   PostThumbnail,
   ProfileSummary,
   UserTag,
   VideoRendition,
)

__all__ = [
   "COMMENT_PAGE_PATH",
   "CREATE_COMMENT_ROOT",
   "DELETE_COMMENT_ROOT",
   "LIKERS_PATH",
   "LIKE_ANSWER_ROOT",
   "MORE_FROM_AUTHOR_PATH",
   "POST_BY_MEDIA_ID_PATH",
   "POST_PATH",
   "REPLIES_PATH",
   "UNLIKE_ANSWER_ROOT",
   "comment_was_deleted",
   "parse_comment",
   "parse_comment_page",
   "parse_created_comment",
   "parse_like_answer",
   "parse_likers",
   "parse_more_from_author",
   "parse_post",
   "parse_post_by_media_id",
   "parse_post_detail",
   "parse_reply_page",
]

POST_PATH = ("data", "xdt_api__v1__media__shortcode__web_info")
"""The path to the item list in a ``PolarisPostRootQuery`` payload, one item for one post."""

LIKE_ANSWER_ROOT = "xig_media_like"
"""The root field a like answers under, carrying ``media`` with ``id`` and ``has_liked``."""

COMMENT_PAGE_PATH = ("data", "xdt_api__v1__media__media_id__comments__connection")
"""The path to the comment connection in a ``PolarisPostCommentsPaginationQuery`` payload."""

CREATE_COMMENT_ROOT = "xig_comment_create"
"""The root field a new comment answers under, carrying the comment as ``comment_dict``."""

DELETE_COMMENT_ROOT = "xig_comment_delete"
"""The root field a comment delete answers under, an object on a delete and null otherwise."""

UNLIKE_ANSWER_ROOT = "xig_media_unlike"
"""The root field an unlike answers under, the same shape as :data:`LIKE_ANSWER_ROOT`."""

REPLIES_PATH = (
   "data",
   "xdt_api__v1__media__media_id__comments__parent_comment_id__child_comments__connection",
)
"""The path to the replies connection, which both the first and the later reply pages answer
under."""

LIKERS_PATH = ("data", "fetch__XDTMediaDict", "likers_connection")
"""The path to the likers in a ``PolarisPostLikedByListDialogQuery`` payload, ``nodes`` only."""

POST_BY_MEDIA_ID_PATH = ("data", "xdt_api__v1__media__media_id_web_info")
"""The path to the item list in a ``PolarisPostActionLoadPostQueryMediaIdQuery`` payload."""

MORE_FROM_AUTHOR_PATH = ("data", "xdt_api__v1__profile_timeline")
"""The path to the strip in a ``PolarisDesktopPostPageRelatedMediaGridQuery`` payload, which
carries ``profile_grid_items`` and ``num_results``."""


def _taken_at(node: dict[str, Any], path: str) -> datetime:
   """Convert ``taken_at`` to timezone-aware UTC.

   The timeline sends whole seconds since the Unix epoch as a JSON number, which is a
   different unit and a different type from the ``timestamp_ms`` string a direct message
   carries. The two are kept apart rather than unified, because a converter that guesses the
   unit from the magnitude is a converter that silently dates a post to 1970 or to the year
   58000 when the upstream changes it.
   """

   raw = _required(node, "taken_at", path)

   if isinstance(raw, bool) or not isinstance(raw, int):
      raise SchemaChanged(f"{path}.taken_at is not an integer", path=f"{path}.taken_at")

   return datetime.fromtimestamp(raw, tz=UTC)


def _caption_text(node: dict[str, Any], path: str) -> str | None:
   """The poster's caption, which arrives wrapped in an object with its own identifier.

   A null wrapper means no caption. An object that is not a dict is the upstream changing
   rather than an absent caption, so it raises.
   """

   raw = _required(node, "caption", path)

   if raw is None:
      return None

   if not isinstance(raw, dict):
      raise SchemaChanged(f"{path}.caption is not an object or null", path=f"{path}.caption")

   return _optional_string(raw, "text", f"{path}.caption")


def _images(node: dict[str, Any], path: str) -> tuple[MediaImage, ...]:
   """Every rendition the upstream offered, in the order it sent them.

   Thirteen arrived per post across two aspect ratios, so these are crops as well as sizes and
   nothing here picks one or sorts them.
   """

   wrapper = _required(node, "image_versions2", path)

   if wrapper is None:
      return ()

   if not isinstance(wrapper, dict):
      raise SchemaChanged(
         f"{path}.image_versions2 is not an object or null", path=f"{path}.image_versions2"
      )

   wrapper_path = f"{path}.image_versions2"
   candidates = _required(wrapper, "candidates", wrapper_path)

   if candidates is None:
      return ()

   if not isinstance(candidates, list):
      raise SchemaChanged(
         f"{wrapper_path}.candidates is not a list or null", path=f"{wrapper_path}.candidates"
      )

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


MANIFEST_ROOT = re.compile(r"<MPD\b[^>]*>")
MANIFEST_DURATION = re.compile(r'\bmediaPresentationDuration="([^"]*)"')
ISO_DURATION = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?")
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600


def _videos(node: dict[str, Any], path: str) -> tuple[VideoRendition, ...]:
   """A video's renditions, in the order the upstream sent them, empty on anything else.

   ``video_versions`` was null on every photo and carousel measured and a list of three on every
   reel. Each entry carried ``url``, ``width``, ``height`` and ``type`` and nothing else.
   """

   versions = _required(node, "video_versions", path)

   if versions is None:
      return ()

   if not isinstance(versions, list):
      raise SchemaChanged(
         f"{path}.video_versions is not a list or null", path=f"{path}.video_versions"
      )

   built: list[VideoRendition] = []

   for index, entry in enumerate(versions):
      entry_path = f"{path}.video_versions[{index}]"

      built.append(
         VideoRendition(
            url=_required_string(entry, "url", entry_path),
            width=_required_integer(entry, "width", entry_path),
            height=_required_integer(entry, "height", entry_path),
            version_type=_required_integer(entry, "type", entry_path),
         )
      )

   return tuple(built)


def _seconds_from(iso_duration: str, path: str) -> float:
   match = ISO_DURATION.fullmatch(iso_duration)
   refusal = f"{path} is not a duration in hours, minutes and seconds"

   if match is None:
      raise SchemaChanged(refusal, path=path)

   hours, minutes, seconds = match.groups()
   names_no_component = hours is None and minutes is None and seconds is None

   if names_no_component:
      raise SchemaChanged(refusal, path=path)

   return (
      int(hours or 0) * SECONDS_PER_HOUR
      + int(minutes or 0) * SECONDS_PER_MINUTE
      + float(seconds or 0)
   )


def _video_duration(node: dict[str, Any], path: str) -> float:
   """A video's length in seconds, from its DASH manifest.

   The web payload carries no duration field. The manifest in ``video_dash_manifest`` carried
   ``mediaPresentationDuration`` on its root element on all eleven reels measured, as an ISO 8601
   duration such as ``PT68.26667S``. A video without the manifest, or a manifest without that
   attribute, raises rather than reporting no duration, because both mean the upstream changed.
   Only the root element's opening tag is searched, with a pattern rather than an XML parser, so
   an upstream document is never expanded.
   """

   manifest_path = f"{path}.video_dash_manifest"
   manifest = _required(node, "video_dash_manifest", path)

   if not isinstance(manifest, str):
      raise SchemaChanged(f"{manifest_path} is not a string on a video", path=manifest_path)

   root = MANIFEST_ROOT.search(manifest)
   duration = MANIFEST_DURATION.search(root.group(0)) if root is not None else None

   if duration is None:
      raise SchemaChanged(
         f"{manifest_path} names no mediaPresentationDuration on its root", path=manifest_path
      )

   return _seconds_from(duration.group(1), f"{manifest_path}.mediaPresentationDuration")


def _duration_if_video(
   node: dict[str, Any], videos: tuple[VideoRendition, ...], path: str
) -> float | None:
   if not videos:
      return None

   return _video_duration(node, path)


def _music(slot: dict[str, Any], path: str) -> MediaAudio:
   asset_path = f"{path}.music_asset_info"
   asset = _required(slot, "music_asset_info", path)
   consumption_path = f"{path}.music_consumption_info"
   consumption = _required(slot, "music_consumption_info", path)

   return MediaAudio(
      kind=AudioKind.MUSIC,
      audio_id=_required_string(asset, "audio_cluster_id", asset_path),
      title=_required_string(asset, "title", asset_path),
      artist=_required_string(asset, "display_artist", asset_path),
      is_explicit=_required_flag(asset, "is_explicit", asset_path),
      should_mute=_required_flag(consumption, "should_mute_audio", consumption_path),
   )


def _original_sound(slot: dict[str, Any], path: str) -> MediaAudio:
   artist_path = f"{path}.ig_artist"
   artist = _required(slot, "ig_artist", path)

   return MediaAudio(
      kind=AudioKind.ORIGINAL_SOUND,
      audio_id=_required_string(slot, "audio_asset_id", path),
      title=_required_string(slot, "original_audio_title", path),
      artist=_required_string(artist, "username", artist_path),
      is_explicit=_required_flag(slot, "is_explicit", path),
      should_mute=_required_flag(slot, "should_mute_audio", path),
      artist_id=_required_string(artist, "id", artist_path),
   )


def _audio(
   node: dict[str, Any], path: str, *, original_sound_without_flag_is_unknown: bool = False
) -> MediaAudio | None:
   """The track a reel plays, from whichever of its two audio slots the upstream filled.

   ``clips_metadata`` is null on a photo and a carousel, and on each of the eleven reels
   measured exactly one of ``music_info`` and ``original_sound_info`` was an object. Both filled
   raises, because which one plays would be a guess. Both null returns ``None``: it has not been
   seen, and it is what a reel with no track of either kind would plausibly send.

   The post read by media pk sends an original sound without ``is_explicit``, which
   :class:`~dumpstagram.models.MediaAudio` requires, so its mapper passes
   ``original_sound_without_flag_is_unknown`` and such a track reads as ``None`` rather than with a
   guessed flag (W63). Every other read still refuses it.
   """

   metadata = _required(node, "clips_metadata", path)

   if metadata is None:
      return None

   metadata_path = f"{path}.clips_metadata"

   if not isinstance(metadata, dict):
      raise SchemaChanged(f"{metadata_path} is not an object or null", path=metadata_path)

   music = _required(metadata, "music_info", metadata_path)
   original = _required(metadata, "original_sound_info", metadata_path)
   has_music = music is not None
   has_original = original is not None
   has_both = has_music and has_original

   if has_both:
      raise SchemaChanged(
         f"{metadata_path} filled both music_info and original_sound_info", path=metadata_path
      )

   if has_music:
      return _music(music, f"{metadata_path}.music_info")

   lacks_the_explicit_flag = isinstance(original, dict) and "is_explicit" not in original
   skips_the_original_sound = original_sound_without_flag_is_unknown and lacks_the_explicit_flag

   if has_original and skips_the_original_sound:
      return None

   if has_original:
      return _original_sound(original, f"{metadata_path}.original_sound_info")

   return None


def _account_row(row: Any, path: str) -> ProfileSummary:
   """An account a post names, read as a list row is read.

   Imported here rather than at the top, because the profiles mapper imports this module for the
   posts on a grid.
   """

   from dumpstagram._private.web.parse.profiles import parse_profile_summary

   return parse_profile_summary(row, path)


def _place_id(location: dict[str, Any], path: str) -> str:
   """A place's ``pk``, a string on the home timeline and a number on a grid and a post read."""

   raw = _required(location, "pk", path)
   is_a_number = isinstance(raw, int) and not isinstance(raw, bool)

   if is_a_number:
      return str(raw)

   if not isinstance(raw, str):
      raise SchemaChanged(f"{path}.pk is not a string or an integer", path=f"{path}.pk")

   return raw


def _as_float(raw: Any, path: str) -> float:
   is_a_number = isinstance(raw, int | float) and not isinstance(raw, bool)

   if not is_a_number:
      raise SchemaChanged(f"{path} is not a number", path=path)

   return float(raw)


def _coordinate(location: dict[str, Any], key: str, path: str) -> float:
   return _as_float(_required(location, key, path), f"{path}.{key}")


def _location(node: dict[str, Any], path: str) -> Location | None:
   """The place a post is tagged at, ``None`` when the node sends null or does not carry it.

   Dropped: ``__typename``, and ``profile_pic_url``, null on every location read and the field a
   grid's partial answer names in its errors (W52).
   """

   raw = node.get("location")

   if raw is None:
      return None

   location_path = f"{path}.location"

   if not isinstance(raw, dict):
      raise SchemaChanged(f"{location_path} is not an object or null", path=location_path)

   return Location(
      id=_place_id(raw, location_path),
      name=_required_string(raw, "name", location_path),
      lat=_coordinate(raw, "lat", location_path),
      lng=_coordinate(raw, "lng", location_path),
   )


def _tag_position(entry: dict[str, Any], path: str) -> tuple[float, float] | None:
   if "position" not in entry:
      return None

   raw = entry["position"]
   position_path = f"{path}.position"
   is_a_pair = isinstance(raw, list) and len(raw) == 2

   if not is_a_pair:
      raise SchemaChanged(f"{position_path} is not a pair of numbers", path=position_path)

   return (_as_float(raw[0], f"{position_path}[0]"), _as_float(raw[1], f"{position_path}[1]"))


def _tagged_account(user: Any, path: str) -> ProfileSummary:
   """The tagged account, read by ``id``: every tag read on 2026-09-27 carried ``id``, and the
   home timeline's one slide tag carried no ``pk``, where the same tag read by media pk did.
   ``is_private`` is read where the tag carries it. ``aigm_account_label_info``, a label for
   generated accounts on some tags, is dropped."""

   if not isinstance(user, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

   carries_privacy = "is_private" in user

   return ProfileSummary(
      id=_required_string(user, "id", path),
      username=_required_string(user, "username", path),
      full_name=_required_string(user, "full_name", path),
      is_verified=_required_flag(user, "is_verified", path),
      profile_pic_url=_required_string(user, "profile_pic_url", path),
      is_private=_optional_flag(user, "is_private", path) if carries_privacy else None,
   )


def _user_tag(entry: Any, path: str) -> UserTag:
   if not isinstance(entry, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

   return UserTag(
      account=_tagged_account(_required(entry, "user", path), f"{path}.user"),
      position=_tag_position(entry, path),
   )


def _user_tags(node: dict[str, Any], path: str) -> tuple[UserTag, ...] | None:
   """The accounts tagged on a post or a slide, empty when the node sends null, and ``None``
   only when it does not carry ``usertags`` at all. The wrapper carried ``in`` and nothing else
   on every one read."""

   if "usertags" not in node:
      return None

   raw = node["usertags"]

   if raw is None:
      return ()

   tags_path = f"{path}.usertags"

   if not isinstance(raw, dict):
      raise SchemaChanged(f"{tags_path} is not an object or null", path=tags_path)

   entries = _required(raw, "in", tags_path)

   if not isinstance(entries, list):
      raise SchemaChanged(f"{tags_path}.in is not a list", path=f"{tags_path}.in")

   return tuple(_user_tag(entry, f"{tags_path}.in[{index}]") for index, entry in enumerate(entries))


def _collaborators(node: dict[str, Any], path: str) -> tuple[ProfileSummary, ...] | None:
   """The accounts a post is shared with, from ``coauthor_producers``, empty when the node sends
   null or an empty list, and ``None`` when it does not carry the key, as the post read by media
   pk does not. ``invited_coauthor_producers`` was an empty list on every node read and is not
   modelled."""

   if "coauthor_producers" not in node:
      return None

   raw = node["coauthor_producers"]

   if raw is None:
      return ()

   producers_path = f"{path}.coauthor_producers"

   if not isinstance(raw, list):
      raise SchemaChanged(f"{producers_path} is not a list or null", path=producers_path)

   return tuple(
      _account_row(producer, f"{producers_path}[{index}]") for index, producer in enumerate(raw)
   )


def _carousel_child(node: Any, path: str) -> CarouselChild:
   """One slide, read with its own kind, renditions and dimensions.

   A slide carries the video keys a reel does, null on every photo slide measured. It has no
   ``code`` (null), and on the post query no ``has_audio`` at all, so neither is read.
   """

   if not isinstance(node, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

   videos = _videos(node, path)

   return CarouselChild(
      id=_required_string(node, "id", path),
      pk=_required_string(node, "pk", path),
      media_type=_required_integer(node, "media_type", path),
      product_type=_required_string(node, "product_type", path),
      original_width=_optional_integer(node, "original_width", path),
      original_height=_optional_integer(node, "original_height", path),
      accessibility_caption=_optional_string(node, "accessibility_caption", path),
      images=_images(node, path),
      videos=videos,
      video_duration=_duration_if_video(node, videos, path),
      user_tags=_user_tags(node, path),
   )


def _carousel_children(node: dict[str, Any], path: str) -> tuple[CarouselChild, ...]:
   """A carousel's slides in the upstream's order, empty on a post that is not a carousel."""

   children = _required(node, "carousel_media", path)

   if children is None:
      return ()

   if not isinstance(children, list):
      raise SchemaChanged(
         f"{path}.carousel_media is not a list or null", path=f"{path}.carousel_media"
      )

   return tuple(
      _carousel_child(child, f"{path}.carousel_media[{index}]")
      for index, child in enumerate(children)
   )


def _post_author(
   node: dict[str, Any], path: str, *, hd_picture_if_carried: bool = False
) -> PostAuthor:
   """The posting account, read off the media's own ``user`` object.

   ``id`` and ``pk`` held the identical value on all six measured nodes, and ``id`` is the one
   read, matching :func:`~dumpstagram._private.web.parse.profiles.parse_profile`.

   The media also carries ``owner_id``, which is an object holding those same two fields again
   rather than the bare number its name suggests. It is dropped, because reading the third
   copy of one value adds a way to be wrong and nothing else.

   ``friendship_status`` is the viewer's relationship with this account. It is optional here
   rather than required, because it is absent on an account the viewer has no relationship
   with and losing a boolean is not a reason to fail a page.

   The post read by media pk sends no ``hd_profile_pic_url_info`` on its author, so its mapper
   passes ``hd_picture_if_carried`` and the picture reads as ``None``. Every other read still
   refuses an author without the key.
   """

   author = _required(node, "user", path)
   author_path = f"{path}.user"

   if not isinstance(author, dict):
      raise SchemaChanged(f"{author_path} is not an object", path=author_path)

   friendship = author.get("friendship_status")
   following = friendship.get("following") if isinstance(friendship, dict) else None
   is_favorite = friendship.get("is_feed_favorite") if isinstance(friendship, dict) else None
   skips_the_hd_picture = hd_picture_if_carried and "hd_profile_pic_url_info" not in author
   hd_profile_pic_url = None if skips_the_hd_picture else _hd_profile_pic_url(author, author_path)

   return PostAuthor(
      id=_required_string(author, "id", author_path),
      username=_required_string(author, "username", author_path),
      full_name=_required_string(author, "full_name", author_path),
      is_private=_required_flag(author, "is_private", author_path),
      is_verified=_required_flag(author, "is_verified", author_path),
      profile_pic_url=_required_string(author, "profile_pic_url", author_path),
      hd_profile_pic_url=hd_profile_pic_url,
      is_following=following if isinstance(following, bool) else None,
      is_favorite=is_favorite if isinstance(is_favorite, bool) else None,
   )


def _is_seen(node: dict[str, Any], path: str, *, null_is_unseen: bool) -> bool:
   """Whether the viewer has seen the post in the feed.

   The home timeline sent a boolean on every node. A profile's grid sent null on all 32 nodes
   read on 2026-09-27, because the grid is not a feed the viewer has seen things in, and the grid
   mapper passes ``null_is_unseen`` so that null reads as False (W53). Anything but a boolean or
   that null still raises.
   """

   if not null_is_unseen:
      return _required_flag(node, "is_seen", path)

   seen = _optional_flag(node, "is_seen", path)

   return seen is True


def parse_post(node: Any, path: str, *, null_is_unseen: bool = False) -> Post:
   """One media node, mapped field by field.

   The home timeline and a profile's grid send the same node, key for key but for ``is_seen``,
   which the grid sends as null, so ``null_is_unseen`` is the grid mapper's one difference.
   """

   if not isinstance(node, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

   videos = _videos(node, path)

   return Post(
      id=_required_string(node, "id", path),
      pk=_required_string(node, "pk", path),
      code=_required_string(node, "code", path),
      taken_at=_taken_at(node, path),
      author=_post_author(node, path),
      media_type=_required_integer(node, "media_type", path),
      product_type=_required_string(node, "product_type", path),
      like_count=_required_integer(node, "like_count", path),
      comment_count=_required_integer(node, "comment_count", path),
      has_liked=_required_flag(node, "has_liked", path),
      is_seen=_is_seen(node, path, null_is_unseen=null_is_unseen),
      caption=_caption_text(node, path),
      accessibility_caption=_optional_string(node, "accessibility_caption", path),
      original_width=_optional_integer(node, "original_width", path),
      original_height=_optional_integer(node, "original_height", path),
      carousel_media_count=_optional_integer(node, "carousel_media_count", path),
      images=_images(node, path),
      is_paid_partnership=_required_flag(node, "is_paid_partnership", path),
      like_and_view_counts_disabled=_required_flag(node, "like_and_view_counts_disabled", path),
      videos=videos,
      video_duration=_duration_if_video(node, videos, path),
      has_audio=_optional_flag(node, "has_audio", path),
      audio=_audio(node, path),
      carousel_children=_carousel_children(node, path),
      location=_location(node, path),
      user_tags=_user_tags(node, path),
      collaborators=_collaborators(node, path),
   )


def parse_post_detail(payload: Any) -> PostDetail:
   """One ``PolarisPostRootQuery`` payload, mapped into the one post it carries.

   Every measured answer held exactly one item. Zero or several raise
   :class:`~dumpstagram.errors.SchemaChanged` rather than picking one, because what either
   would mean is unobserved, and that includes what a shortcode with no post behind it answers.

   The item carries everything :func:`parse_post` reads except ``is_seen``, so it is read here
   field by field into its own model rather than through that function.

   Finding: `read-a-post-by-shortcode` in the knowledge base.
   """

   root = _object_at(payload, POST_PATH)
   root_path = ".".join(POST_PATH)
   items = _required(root, "items", root_path)
   is_exactly_one_item = isinstance(items, list) and len(items) == 1

   if not is_exactly_one_item:
      raise SchemaChanged(
         f"{root_path}.items is not a list of exactly one post", path=f"{root_path}.items"
      )

   node = items[0]
   path = f"{root_path}.items[0]"

   if not isinstance(node, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

   videos = _videos(node, path)

   return PostDetail(
      id=_required_string(node, "id", path),
      pk=_required_string(node, "pk", path),
      code=_required_string(node, "code", path),
      taken_at=_taken_at(node, path),
      author=_post_author(node, path),
      media_type=_required_integer(node, "media_type", path),
      product_type=_required_string(node, "product_type", path),
      like_count=_required_integer(node, "like_count", path),
      comment_count=_required_integer(node, "comment_count", path),
      has_liked=_required_flag(node, "has_liked", path),
      caption=_caption_text(node, path),
      accessibility_caption=_optional_string(node, "accessibility_caption", path),
      original_width=_optional_integer(node, "original_width", path),
      original_height=_optional_integer(node, "original_height", path),
      carousel_media_count=_optional_integer(node, "carousel_media_count", path),
      images=_images(node, path),
      is_paid_partnership=_required_flag(node, "is_paid_partnership", path),
      like_and_view_counts_disabled=_required_flag(node, "like_and_view_counts_disabled", path),
      videos=videos,
      video_duration=_duration_if_video(node, videos, path),
      has_audio=_optional_flag(node, "has_audio", path),
      audio=_audio(node, path),
      carousel_children=_carousel_children(node, path),
      location=_location(node, path),
      user_tags=_user_tags(node, path),
      collaborators=_collaborators(node, path),
   )


def parse_like_answer(payload: Any, root_field: str) -> bool:
   """The ``has_liked`` a like or an unlike answered with, from ``data.<root_field>.media``.

   Four sends on 2026-09-23 each answered with the media under that root and no ``errors``
   array, so a missing media object is a schema change rather than a quiet success.
   """

   media = _object_at(payload, ("data", root_field, "media"))

   return _required_flag(media, "has_liked", f"data.{root_field}.media")


def _created_at(node: dict[str, Any], path: str) -> datetime:
   """Convert a comment's ``created_at`` to timezone-aware UTC.

   Whole seconds since the Unix epoch as a JSON number, like a post's ``taken_at``, on both
   observed answers. The unit was confirmed against the clock by the Step 16 acceptance run.
   """

   raw = _required(node, "created_at", path)

   if isinstance(raw, bool) or not isinstance(raw, int):
      raise SchemaChanged(f"{path}.created_at is not an integer", path=f"{path}.created_at")

   return datetime.fromtimestamp(raw, tz=UTC)


def _comment_author(node: dict[str, Any], path: str) -> CommentAuthor:
   user_path = f"{path}.user"
   user = _required(node, "user", path)

   if not isinstance(user, dict):
      raise SchemaChanged(f"{user_path} is not an object", path=user_path)

   return CommentAuthor(
      id=_required_string(user, "pk", user_path),
      username=_required_string(user, "username", user_path),
      is_verified=_required_flag(user, "is_verified", user_path),
      profile_pic_url=_required_string(user, "profile_pic_url", user_path),
   )


def parse_comment(node: Any, path: str) -> Comment:
   """One node of the comment page, mapped field by field.

   The node also carries ``fallback_user_info``, ``giphy_media_info``, ``has_translation``,
   ``is_covered``, ``is_edited`` and ``restricted_status``, which are dropped: all were empty or
   false on the one node read, so there is nothing measured to model.
   """

   if not isinstance(node, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

   return Comment(
      id=_required_string(node, "pk", path),
      text=_required_string(node, "text", path),
      created_at=_created_at(node, path),
      author=_comment_author(node, path),
      like_count=_required_integer(node, "comment_like_count", path),
      reply_count=_required_integer(node, "child_comment_count", path),
      parent_comment_id=_optional_string(node, "parent_comment_id", path),
      has_liked=_required_flag(node, "has_liked_comment", path),
   )


def parse_comment_page(payload: Any) -> Page[Comment]:
   """One ``PolarisPostCommentsPaginationQuery`` payload, mapped into comments.

   ``page_info.has_next_page`` is the only terminator. A page shorter than was asked for, or
   empty, says nothing about whether more exist, and is passed on with the flag as sent.

   Finding: `read-a-post-comment-page` in the knowledge base.
   """

   connection = _object_at(payload, COMMENT_PAGE_PATH)
   connection_path = ".".join(COMMENT_PAGE_PATH)

   edges = _required(connection, "edges", connection_path)

   if not isinstance(edges, list):
      raise SchemaChanged(f"{connection_path}.edges is not a list", path=f"{connection_path}.edges")

   comments = tuple(
      parse_comment(
         _required(edge, "node", f"{connection_path}.edges[{index}]"),
         f"{connection_path}.edges[{index}].node",
      )
      for index, edge in enumerate(edges)
   )

   page_info_path = f"{connection_path}.page_info"
   page_info = _required(connection, "page_info", connection_path)

   if not isinstance(page_info, dict):
      raise SchemaChanged(f"{page_info_path} is not an object", path=page_info_path)

   has_next_page = _required_flag(page_info, "has_next_page", page_info_path)
   end_cursor = _optional_string(page_info, "end_cursor", page_info_path)

   return Page(items=comments, has_next_page=has_next_page, end_cursor=end_cursor)


def parse_created_comment(payload: Any) -> Comment:
   """The comment a create answered with, from ``data.xig_comment_create.comment_dict``.

   That object carries the id, the text, the time and the author, and none of the counts the
   comment page adds, so those stay None. Both observed answers carried it with no ``errors``
   array, so its absence is a schema change rather than a quiet success.

   Finding: `comment-on-a-post` in the knowledge base.
   """

   path = f"data.{CREATE_COMMENT_ROOT}.comment_dict"
   node = _object_at(payload, ("data", CREATE_COMMENT_ROOT, "comment_dict"))

   return Comment(
      id=_required_string(node, "pk", path),
      text=_required_string(node, "text", path),
      created_at=_created_at(node, path),
      author=_comment_author(node, path),
   )


def comment_was_deleted(payload: Any) -> bool:
   """Whether a delete's answer says a comment was deleted.

   Two real deletes answered ``data.xig_comment_delete`` with an object, and a delete naming
   no comment answered it null with no error, so only an object is a delete. A payload without
   the root field at all is a schema change.

   Finding: `delete-my-own-comment` in the knowledge base.
   """

   data = _object_at(payload, ("data",))
   root = _required(data, DELETE_COMMENT_ROOT, "data")

   return isinstance(root, dict)


def parse_post_by_media_id(payload: Any) -> PostDetail:
   """One ``PolarisPostActionLoadPostQueryMediaIdQuery`` payload, the one post it carries.

   The item is the post query's item with less in it, and the gaps are left empty rather than
   filled (W63). Its slides carry neither ``media_type`` nor ``product_type``, which
   :class:`~dumpstagram.models.CarouselChild` requires, so ``carousel_children`` is empty while
   ``carousel_media_count`` counts them. It carries no ``accessibility_caption``, no author's high
   resolution picture and no ``coauthor_producers``, which read as ``None``. Its tags carry no
   position. An original sound comes without ``is_explicit``, so ``audio`` is ``None`` on such a
   reel. Zero or several items raise, as :func:`parse_post_detail` does.

   Dropped as on the other post reads, and also ``photo_of_you``, ``sharing_friction_info`` and
   ``facepile_top_likers``. A first answer on 2026-09-27 came beside twelve field errors, each on a
   field nothing here reads, and is mapped whole under W52.

   Finding: ``read-a-post-by-media-id``.
   """

   root = _object_at(payload, POST_BY_MEDIA_ID_PATH)
   root_path = ".".join(POST_BY_MEDIA_ID_PATH)
   items = _required(root, "items", root_path)
   is_exactly_one_item = isinstance(items, list) and len(items) == 1

   if not is_exactly_one_item:
      raise SchemaChanged(
         f"{root_path}.items is not a list of exactly one post", path=f"{root_path}.items"
      )

   node = items[0]
   path = f"{root_path}.items[0]"

   if not isinstance(node, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

   videos = _videos(node, path)
   carries_accessibility_caption = "accessibility_caption" in node
   accessibility_caption = (
      _optional_string(node, "accessibility_caption", path)
      if carries_accessibility_caption
      else None
   )

   return PostDetail(
      id=_required_string(node, "id", path),
      pk=_required_string(node, "pk", path),
      code=_required_string(node, "code", path),
      taken_at=_taken_at(node, path),
      author=_post_author(node, path, hd_picture_if_carried=True),
      media_type=_required_integer(node, "media_type", path),
      product_type=_required_string(node, "product_type", path),
      like_count=_required_integer(node, "like_count", path),
      comment_count=_required_integer(node, "comment_count", path),
      has_liked=_required_flag(node, "has_liked", path),
      caption=_caption_text(node, path),
      accessibility_caption=accessibility_caption,
      original_width=_optional_integer(node, "original_width", path),
      original_height=_optional_integer(node, "original_height", path),
      carousel_media_count=_optional_integer(node, "carousel_media_count", path),
      images=_images(node, path),
      is_paid_partnership=_required_flag(node, "is_paid_partnership", path),
      like_and_view_counts_disabled=_required_flag(node, "like_and_view_counts_disabled", path),
      videos=videos,
      video_duration=_duration_if_video(node, videos, path),
      has_audio=_optional_flag(node, "has_audio", path),
      audio=_audio(node, path, original_sound_without_flag_is_unknown=True),
      location=_location(node, path),
      user_tags=_user_tags(node, path),
      collaborators=_collaborators(node, path),
   )


def parse_reply(node: Any, path: str) -> Comment:
   """One reply, a node of the comment page's own shape key for key.

   A reply's ``child_comment_count`` was null on all 32 read, so ``reply_count`` is ``None``
   rather than a count, and its ``parent_comment_id`` was the parent's id on every one, so it is
   required here. The rest is read as :func:`parse_comment` reads it.
   """

   if not isinstance(node, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

   return Comment(
      id=_required_string(node, "pk", path),
      text=_required_string(node, "text", path),
      created_at=_created_at(node, path),
      author=_comment_author(node, path),
      like_count=_required_integer(node, "comment_like_count", path),
      reply_count=_optional_integer(node, "child_comment_count", path),
      parent_comment_id=_required_string(node, "parent_comment_id", path),
      has_liked=_required_flag(node, "has_liked_comment", path),
   )


def parse_reply_page(payload: Any) -> Page[Comment]:
   """One page of replies, first or next, mapped in the upstream's order, oldest first.

   ``page_info.has_next_page`` is the only terminator, and the page's length is the upstream's:
   9 and then 11 replies came back for the same ``first``. The per-edge ``cursor`` was the empty
   string on every edge.

   Findings: ``read-comment-replies`` and ``read-comment-replies-next-page``.
   """

   connection = _object_at(payload, REPLIES_PATH)
   connection_path = ".".join(REPLIES_PATH)
   edges = _required(connection, "edges", connection_path)

   if not isinstance(edges, list):
      raise SchemaChanged(f"{connection_path}.edges is not a list", path=f"{connection_path}.edges")

   replies = tuple(
      parse_reply(
         _required(edge, "node", f"{connection_path}.edges[{index}]"),
         f"{connection_path}.edges[{index}].node",
      )
      for index, edge in enumerate(edges)
   )

   page_info_path = f"{connection_path}.page_info"
   page_info = _required(connection, "page_info", connection_path)

   if not isinstance(page_info, dict):
      raise SchemaChanged(f"{page_info_path} is not an object", path=page_info_path)

   has_next_page = _required_flag(page_info, "has_next_page", page_info_path)
   end_cursor = _optional_string(page_info, "end_cursor", page_info_path)

   return Page(items=replies, has_next_page=has_next_page, end_cursor=end_cursor)


def parse_likers(payload: Any) -> tuple[ProfileSummary, ...]:
   """One ``PolarisPostLikedByListDialogQuery`` payload, the accounts in the upstream's order.

   A node is a list row: ``pk`` equal to ``id``, the names and pictures, and a relationship
   carrying all eight flags. No node carried ``is_private``. The connection carried ``nodes``
   and nothing else, no cursor and no count, so the tuple is what the upstream lists, which is a
   bounded sample of the likes: 98 accounts on a post counting 193647 (W62).

   Finding: ``read-a-post-s-likers``.
   """

   connection = _object_at(payload, LIKERS_PATH)
   connection_path = ".".join(LIKERS_PATH)
   nodes = _required(connection, "nodes", connection_path)

   if not isinstance(nodes, list):
      raise SchemaChanged(f"{connection_path}.nodes is not a list", path=f"{connection_path}.nodes")

   return tuple(
      _account_row(node, f"{connection_path}.nodes[{index}]") for index, node in enumerate(nodes)
   )


def _post_thumbnail(node: Any, path: str) -> PostThumbnail:
   """One item of the strip. Dropped, each null on all six or chrome: ``audience``,
   ``comments_disabled``, ``accessibility_caption``, ``display_uri``, ``preview``,
   ``thumbnails``, ``media_overlay_info``, ``upcoming_event``, ``view_count``, the three boost
   fields, ``media_cropping_info``, ``profile_grid_thumbnail_fitting_style``, ``media_notes``,
   ``timeline_pinned_user_ids``, and ``carousel_media``, whose slides carried an id and
   renditions and nothing that says what each slide is."""

   if not isinstance(node, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

   author = _object_at(node, ("user",))
   author_path = f"{path}.user"

   return PostThumbnail(
      id=_required_string(node, "id", path),
      pk=_required_string(node, "pk", path),
      code=_required_string(node, "code", path),
      author_id=_required_string(author, "pk", author_path),
      author_username=_required_string(author, "username", author_path),
      media_type=_required_integer(node, "media_type", path),
      product_type=_required_string(node, "product_type", path),
      like_count=_required_integer(node, "like_count", path),
      comment_count=_required_integer(node, "comment_count", path),
      like_and_view_counts_disabled=_required_flag(node, "like_and_view_counts_disabled", path),
      caption=_caption_text(node, path),
      carousel_media_count=_optional_integer(node, "carousel_media_count", path),
      images=_images(node, path),
   )


def parse_more_from_author(payload: Any) -> tuple[PostThumbnail, ...]:
   """One ``PolarisDesktopPostPageRelatedMediaGridQuery`` payload, the strip in its order.

   Each entry of ``profile_grid_items`` carries the post as ``media`` and nothing else.
   ``num_results`` equalled the entries' count on both answers and is not read.

   Finding: ``read-more-posts-from-an-account``.
   """

   root = _object_at(payload, MORE_FROM_AUTHOR_PATH)
   root_path = ".".join(MORE_FROM_AUTHOR_PATH)
   items = _required(root, "profile_grid_items", root_path)

   if not isinstance(items, list):
      raise SchemaChanged(
         f"{root_path}.profile_grid_items is not a list", path=f"{root_path}.profile_grid_items"
      )

   return tuple(
      _post_thumbnail(
         _required(item, "media", f"{root_path}.profile_grid_items[{index}]"),
         f"{root_path}.profile_grid_items[{index}].media",
      )
      for index, item in enumerate(items)
   )
