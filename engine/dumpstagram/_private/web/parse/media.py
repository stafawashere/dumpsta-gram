"""Map a post payload: a post, a post read on its own, a like answer, and comments."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from dumpstagram._private.web.parse.common import (
   _hd_profile_pic_url,
   _object_at,
   _optional_integer,
   _optional_string,
   _required,
   _required_flag,
   _required_integer,
   _required_string,
)
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import (
   Comment,
   CommentAuthor,
   MediaImage,
   Page,
   Post,
   PostAuthor,
   PostDetail,
)

__all__ = [
   "COMMENT_PAGE_PATH",
   "CREATE_COMMENT_ROOT",
   "DELETE_COMMENT_ROOT",
   "LIKE_ANSWER_ROOT",
   "POST_PATH",
   "UNLIKE_ANSWER_ROOT",
   "comment_was_deleted",
   "parse_comment",
   "parse_comment_page",
   "parse_created_comment",
   "parse_like_answer",
   "parse_post_detail",
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


def _post_author(node: dict[str, Any], path: str) -> PostAuthor:
   """The posting account, read off the media's own ``user`` object.

   ``id`` and ``pk`` held the identical value on all six measured nodes, and ``id`` is the one
   read, matching :func:`~dumpstagram._private.web.parse.profiles.parse_profile`.

   The media also carries ``owner_id``, which is an object holding those same two fields again
   rather than the bare number its name suggests. It is dropped, because reading the third
   copy of one value adds a way to be wrong and nothing else.

   ``friendship_status`` is the viewer's relationship with this account. It is optional here
   rather than required, because it is absent on an account the viewer has no relationship
   with and losing a boolean is not a reason to fail a page.
   """

   author = _required(node, "user", path)
   author_path = f"{path}.user"

   if not isinstance(author, dict):
      raise SchemaChanged(f"{author_path} is not an object", path=author_path)

   friendship = author.get("friendship_status")
   following = friendship.get("following") if isinstance(friendship, dict) else None
   is_favorite = friendship.get("is_feed_favorite") if isinstance(friendship, dict) else None

   return PostAuthor(
      id=_required_string(author, "id", author_path),
      username=_required_string(author, "username", author_path),
      full_name=_required_string(author, "full_name", author_path),
      is_private=_required_flag(author, "is_private", author_path),
      is_verified=_required_flag(author, "is_verified", author_path),
      profile_pic_url=_required_string(author, "profile_pic_url", author_path),
      hd_profile_pic_url=_hd_profile_pic_url(author, author_path),
      is_following=following if isinstance(following, bool) else None,
      is_favorite=is_favorite if isinstance(is_favorite, bool) else None,
   )


def parse_post(node: Any, path: str) -> Post:
   """One media node, mapped field by field."""

   if not isinstance(node, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

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
      is_seen=_required_flag(node, "is_seen", path),
      caption=_caption_text(node, path),
      accessibility_caption=_optional_string(node, "accessibility_caption", path),
      original_width=_optional_integer(node, "original_width", path),
      original_height=_optional_integer(node, "original_height", path),
      carousel_media_count=_optional_integer(node, "carousel_media_count", path),
      images=_images(node, path),
      is_paid_partnership=_required_flag(node, "is_paid_partnership", path),
      like_and_view_counts_disabled=_required_flag(node, "like_and_view_counts_disabled", path),
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
