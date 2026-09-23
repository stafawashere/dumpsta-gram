"""Map one GraphQL payload into typed models.

This is the only module that knows both the upstream field names and the public models, and
that is deliberate: ADR-0007 requires GraphQL shapes to stop before ``_core``, so the mapping
happens on the surface adapter rather than one layer up.

Mapping is explicit and total. Every field is read by name, a missing required key raises
:class:`~dumpstagram.errors.SchemaChanged` carrying the path that was missing, and unknown
keys are ignored. Nothing is splatted into a constructor, because a permissive mapper turns
an upstream rename into silently degraded records rather than an error.

What the upstream sends and this module drops, from the twenty-node capture on 2026-09-21 in
`engine/logs/message-node-shape-2026-09-21-022957.json`:

- ``message_id``, equal to ``id`` on all twenty nodes, so it is a second name rather than a
  second identifier.
- ``msg_reactions``, non-empty on exactly the message ``reactions`` was non-empty on, and
  carrying ``sender_igid`` instead of the emoji. ``reactions`` is the one with the emoji.
- ``content``, whose ``text_body`` duplicates the node's own ``text_body``.
- ``bot_response_id``, ``expiration_timestamp_ms``, ``igd_wearables_attribution_text``,
  ``igd_wearables_attribution_type``, ``is_tombstone_revealable``, ``tombstone_reason`` and
  ``view_expiration_timestamp_ms``, all null on all twenty nodes, so there is nothing measured
  to model.
- ``is_reported``, ``mentions``, ``offline_threading_id``, ``replied_to_message`` and
  ``slide_edit_history``, which are real but belong to capabilities that do not exist yet.
- the per-edge ``cursor``, because pagination terminates on ``page_info`` and a caller that
  holds a mid-page cursor has a way to resume nothing else offers.

Finding: `skills/reverse-engineer/knowledge/endpoints/direct-thread-message-page.md`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from dumpstagram.errors import SchemaChanged
from dumpstagram.models import (
   BioLink,
   FeedItem,
   FeedItemKind,
   MediaImage,
   Message,
   MessageSender,
   Note,
   NoteAudience,
   Page,
   Post,
   PostAuthor,
   PostDetail,
   Profile,
   Reaction,
)

__all__ = [
   "FEED_PAGE_PATH",
   "INBOX_TRAY_PATH",
   "LIKE_ANSWER_ROOT",
   "POST_PATH",
   "PROFILE_PATH",
   "THREAD_DETAIL_PATH",
   "THREAD_PAGE_PATH",
   "TIMELINE_PATH",
   "UNLIKE_ANSWER_ROOT",
   "parse_feed_page",
   "parse_inbox_tray",
   "parse_like_answer",
   "parse_note",
   "parse_post_detail",
   "parse_profile",
   "parse_thread_detail",
   "parse_thread_message_page",
   "parse_user_id",
]

THREAD_PAGE_PATH = ("data", "fetch__SlideThread", "as_ig_direct_thread", "slide_messages")
"""The canonical path to the message connection, unchanged across both measured days."""

THREAD_DETAIL_PATH = (
   "data",
   "get_slide_thread_nullable",
   "as_ig_direct_thread",
   "slide_messages",
)
"""The same message connection in an ``IGDThreadDetailQuery`` payload, under its own root."""

PROFILE_PATH = ("data", "user")
"""The path to the profile object in a ``PolarisProfilePageContentQuery`` payload."""

TIMELINE_PATH = ("data", "xdt_api__v1__feed__user_timeline_graphql_connection")
"""The path to the timeline connection the username resolution reads an author id off."""

FEED_PAGE_PATH = ("data", "xdt_api__v1__feed__timeline__connection")
"""The path to the home timeline connection.

One character away from :data:`TIMELINE_PATH`, which is a different connection on a different
query: that one is one account's posts keyed on a username, this one is the signed-in
account's home feed.
"""

INBOX_TRAY_PATH = ("data", "response")
"""The path to the notes tray in an ``IGDInboxTrayQuery`` payload.

The operation's root field is ``xdt_get_inbox_tray_items``, and the query aliases it, so the
payload carries it under ``response``.
"""

POST_PATH = ("data", "xdt_api__v1__media__shortcode__web_info")
"""The path to the item list in a ``PolarisPostRootQuery`` payload, one item for one post."""

LIKE_ANSWER_ROOT = "xig_media_like"
"""The root field a like answers under, carrying ``media`` with ``id`` and ``has_liked``."""

UNLIKE_ANSWER_ROOT = "xig_media_unlike"
"""The root field an unlike answers under, the same shape as :data:`LIKE_ANSWER_ROOT`."""

TRAY_PAGINATION_KEYS = frozenset(
   {"page_info", "cursor", "end_cursor", "has_next_page", "next_max_id", "max_id"}
)
"""Keys that would mean the tray had become paged.

None has been seen. Every measured tray was one flat list with no cursor anywhere, which is
why the read is one call. A tray that grew one would be returning a first page while the
engine reported the whole tray, so it raises rather than being ignored.
"""

NOTE_ITEM_TYPE = "note"

MILLISECONDS_PER_SECOND = 1000


def _object_at(payload: Any, path: tuple[str, ...]) -> dict[str, Any]:
   """Walk ``path``, raising with the exact prefix that stopped resolving."""

   current = payload

   for depth, key in enumerate(path):
      reached = ".".join(path[: depth + 1])

      if not isinstance(current, dict):
         raise SchemaChanged(
            f"{reached} is not reachable, its parent is not an object", path=reached
         )

      if key not in current:
         raise SchemaChanged(f"{reached} is missing from the payload", path=reached)

      current = current[key]

   if not isinstance(current, dict):
      raise SchemaChanged(f"{'.'.join(path)} is not an object", path=".".join(path))

   return current


def _required(node: Any, key: str, path: str) -> Any:
   if not isinstance(node, dict) or key not in node:
      raise SchemaChanged(f"{path}.{key} is missing from the payload", path=f"{path}.{key}")

   return node[key]


def _required_string(node: Any, key: str, path: str) -> str:
   value = _required(node, key, path)

   if not isinstance(value, str):
      raise SchemaChanged(f"{path}.{key} is not a string", path=f"{path}.{key}")

   return value


def _required_flag(node: Any, key: str, path: str) -> bool:
   value = _required(node, key, path)

   if not isinstance(value, bool):
      raise SchemaChanged(f"{path}.{key} is not a boolean", path=f"{path}.{key}")

   return value


def _optional_string(node: dict[str, Any], key: str, path: str) -> str | None:
   value = _required(node, key, path)

   if value is None:
      return None

   if not isinstance(value, str):
      raise SchemaChanged(f"{path}.{key} is not a string or null", path=f"{path}.{key}")

   return value


def _sent_at(node: dict[str, Any], path: str) -> datetime:
   """Convert ``timestamp_ms`` to timezone-aware UTC.

   The upstream sends it as a string of milliseconds since the Unix epoch, thirteen digits on
   every measured node. It is accepted as an integer too, because a JSON number is the shape
   the same value would most plausibly change into, and refusing that would be a break with no
   safety behind it. Anything else raises rather than being coerced.
   """

   raw = _required(node, "timestamp_ms", path)

   if isinstance(raw, bool) or not isinstance(raw, (str, int)):
      raise SchemaChanged(
         f"{path}.timestamp_ms is neither a string nor an integer", path=f"{path}.timestamp_ms"
      )

   try:
      milliseconds = int(raw)
   except ValueError as failure:
      raise SchemaChanged(
         f"{path}.timestamp_ms does not hold an integer", path=f"{path}.timestamp_ms"
      ) from failure

   return datetime.fromtimestamp(milliseconds / MILLISECONDS_PER_SECOND, tz=UTC)


def _sender(node: dict[str, Any], path: str) -> MessageSender:
   """Build the sender from ``sender_fbid``, enriched by the sender object when it resolves.

   ``sender_fbid`` is required because it is present on every node. The nested object is
   optional because a sender that no longer resolves is a state the upstream can be in, and
   losing the display name is not a reason to fail a whole page.
   """

   fbid = _required_string(node, "sender_fbid", path)
   details = node.get("sender")

   if not isinstance(details, dict):
      return MessageSender(fbid=fbid)

   igid = details.get("igid")
   name = details.get("name")

   return MessageSender(
      fbid=fbid,
      igid=igid if isinstance(igid, str) else None,
      name=name if isinstance(name, str) else None,
   )


def _reactions(node: dict[str, Any], path: str) -> tuple[Reaction, ...]:
   raw = _required(node, "reactions", path)

   if raw is None:
      return ()

   if not isinstance(raw, list):
      raise SchemaChanged(f"{path}.reactions is not a list", path=f"{path}.reactions")

   built: list[Reaction] = []

   for index, entry in enumerate(raw):
      entry_path = f"{path}.reactions[{index}]"

      built.append(
         Reaction(
            emoji=_required_string(entry, "reaction", entry_path),
            sender_fbid=_required_string(entry, "sender_fbid", entry_path),
         )
      )

   return tuple(built)


def parse_message(node: Any, path: str) -> Message:
   """One message node, mapped field by field."""

   if not isinstance(node, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

   return Message(
      id=_required_string(node, "id", path),
      thread_fbid=_required_string(node, "thread_fbid", path),
      sender=_sender(node, path),
      sent_at=_sent_at(node, path),
      text=_optional_string(node, "text_body", path),
      content_type=_required_string(node, "content_type", path),
      reactions=_reactions(node, path),
      replied_to_message_id=_optional_string(node, "replied_to_message_id", path),
      is_forwarded=_required_flag(node, "igd_is_forwarded", path),
      is_pinned=_required_flag(node, "is_pinned", path),
      is_ai_generated=_required_flag(node, "is_ai_generated", path),
   )


def parse_thread_message_page(payload: Any) -> Page[Message]:
   """One page of the pagination query, mapped into typed messages.

   ``useIGDMessageListPaginationQuery`` and ``IGDMessageListOffMsysQuery`` answer with the same
   root field, so this maps both.

   Edges keep the order the upstream sent them in. Nothing is sorted here, because a
   normalisation applied at the boundary is a normalisation a recorded oracle has to know
   about, and reordering hides whether the upstream order ever changes.

   Two shapes are deliberately not special cased, because neither has been observed and a
   mapper that invents a meaning for an unmeasured shape is guessing in the one place this
   package exists to stop guessing.

   A thread field resolving to null is one of them. It stops the walk like any other
   unreachable path and raises :class:`~dumpstagram.errors.SchemaChanged` naming where it
   stopped. What was measured is that the two thread identifiers which are not the ``fbid``
   answer with nothing; the null shape of that answer was not, so it is reported as a payload
   this mapper cannot map rather than as a thread that does not exist.

   A page claiming a successor while carrying no cursor is the other. It is returned exactly
   as it arrived, with ``has_next_page`` true and ``end_cursor`` ``None``, and the caller sees
   the contradiction the upstream sent.
   """

   return _message_page(payload, THREAD_PAGE_PATH)


def parse_thread_detail(payload: Any) -> Page[Message]:
   """One ``IGDThreadDetailQuery`` payload, mapped into the thread's newest page.

   The thread object around the connection also carries its title, members, read receipts and
   pinned messages. None of that is mapped yet, because no public model holds it.

   A null ``get_slide_thread_nullable`` raises :class:`~dumpstagram.errors.SchemaChanged` for
   the reason :func:`parse_thread_message_page` gives: the name says null is possible, and no
   null answer has been observed, so nothing here claims to know what one means.
   """

   return _message_page(payload, THREAD_DETAIL_PATH)


def _message_page(payload: Any, path: tuple[str, ...]) -> Page[Message]:
   connection = _object_at(payload, path)
   connection_path = ".".join(path)

   edges = _required(connection, "edges", connection_path)

   if not isinstance(edges, list):
      raise SchemaChanged(f"{connection_path}.edges is not a list", path=f"{connection_path}.edges")

   messages = tuple(
      parse_message(
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

   return Page(items=messages, has_next_page=has_next_page, end_cursor=end_cursor)


def _required_integer(node: Any, key: str, path: str) -> int:
   value = _required(node, key, path)

   if isinstance(value, bool) or not isinstance(value, int):
      raise SchemaChanged(f"{path}.{key} is not an integer", path=f"{path}.{key}")

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


def _hd_profile_pic_url(node: dict[str, Any], path: str) -> str | None:
   """The high resolution avatar, which arrives wrapped in a one-key object.

   The wrapper resolving to something other than an object is not treated as absent, because
   an unexpected shape there is the upstream changing and not the account lacking a picture.
   """

   raw = _required(node, "hd_profile_pic_url_info", path)

   if raw is None:
      return None

   if not isinstance(raw, dict):
      raise SchemaChanged(
         f"{path}.hd_profile_pic_url_info is not an object or null",
         path=f"{path}.hd_profile_pic_url_info",
      )

   return _optional_string(raw, "url", f"{path}.hd_profile_pic_url_info")


def parse_profile(payload: Any) -> Profile:
   """One ``PolarisProfilePageContentQuery`` payload, mapped field by field.

   ``pk`` and ``id`` held the identical value on the measured response. ``id`` is the one
   read, and ``pk`` is not compared against it, because a mapper that raises on two upstream
   names disagreeing would turn a cosmetic upstream change into a dead capability.

   What the upstream sends and this mapper drops, from the response recorded on 2026-09-21:

   - ``pk``, a second name for ``id``.
   - ``friendship_status`` and ``mutual_followers_count``, both null because the measured read
     was the viewer reading the viewer. Neither has been observed populated.
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
      is_professional_account=_required_flag(user, "is_professional_account", path),
      is_memorialized=_required_flag(user, "is_memorialized", path),
      is_unpublished=_required_flag(user, "is_unpublished", path),
      is_embeds_disabled=_required_flag(user, "is_embeds_disabled", path),
      has_profile_pic=_required_flag(user, "has_profile_pic", path),
      has_story_archive=_required_flag(user, "has_story_archive", path),
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


def _optional_integer(node: dict[str, Any], key: str, path: str) -> int | None:
   value = _required(node, key, path)

   if value is None:
      return None

   if isinstance(value, bool) or not isinstance(value, int):
      raise SchemaChanged(f"{path}.{key} is not an integer or null", path=f"{path}.{key}")

   return value


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
   read, matching :func:`parse_profile`.

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


def _feed_item(node: Any, path: str) -> FeedItem:
   """One timeline item, reduced to the one union slot the upstream filled.

   Exactly one slot was non-null on all fifteen measured items. Two filled slots, or none,
   raises rather than picking a winner, because both shapes would mean the union stopped being
   a union and neither has a measured meaning.
   """

   if not isinstance(node, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

   filled = [key for key, value in node.items() if key != "__typename" and value is not None]

   if len(filled) != 1:
      raise SchemaChanged(
         f"{path} filled {len(filled)} of its union slots rather than exactly one", path=path
      )

   slot = filled[0]

   try:
      kind = FeedItemKind(slot)
   except ValueError as failure:
      raise SchemaChanged(
         f"{path}.{slot} is a union slot this version does not know", path=path
      ) from failure

   if kind is not FeedItemKind.POST:
      return FeedItem(kind=kind)

   return FeedItem(kind=kind, post=parse_post(node["media"], f"{path}.media"))


def parse_feed_page(payload: Any) -> Page[FeedItem]:
   """One ``PolarisFeedRootPaginationCachedQuery_subscribe`` payload, mapped into feed items.

   Items keep the order the upstream sent them in, and no item is dropped. Six of fifteen
   measured items were posts, so filtering the rest out here would make a page's length
   unexplainable to the caller and would hide how much of a feed is not posts.

   The per-edge ``cursor`` is ignored, and on this connection it has to be: it was null on all
   fifteen edges measured, while ``page_info.end_cursor`` was populated on every page. The
   cursor in ``page_info`` is the only one that paginates this surface.

   What the upstream sends on a media node and this mapper drops, from the fifteen-item page
   recorded on 2026-09-21:

   - ``owner_id``, an object repeating the author's ``pk`` and ``id`` a third time.
   - ``message_id``-style second names aside, ``caption.pk`` and ``caption.has_translation``,
     which belong to a caption capability that does not exist yet.
   - ``carousel_media``, the slides themselves, for the same reason.
   - ``clips_metadata``, ``video_versions``, ``video_dash_manifest``, ``has_audio``,
     ``number_of_qualities`` and ``view_count``, all null across the measured page because
     every post on it was a photo or a photo carousel. Video is unmeasured on this surface.
   - ``facepile_top_likers``, ``top_likers``, ``social_context``, ``floating_context_items``
     and ``media_notes``, which are presentation the web client assembles.
   - ``logging_info_token``, ``organic_tracking_token``, ``inventory_source`` and
     ``crosspost_metadata``, which are telemetry.
   - ``comments_disabled``, ``commenting_disabled_for_viewer``, ``has_viewer_saved``,
     ``can_reshare``, ``usertags``, ``location``, ``sponsor_tags`` and thirty more, null on
     every measured node, so there is nothing measured to model.

   Finding: `skills/reverse-engineer/knowledge/endpoints/home-timeline-feed-page.md`.
   """

   connection = _object_at(payload, FEED_PAGE_PATH)
   connection_path = ".".join(FEED_PAGE_PATH)

   edges = _required(connection, "edges", connection_path)

   if not isinstance(edges, list):
      raise SchemaChanged(f"{connection_path}.edges is not a list", path=f"{connection_path}.edges")

   items = tuple(
      _feed_item(
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

   return Page(items=items, has_next_page=has_next_page, end_cursor=end_cursor)


def _note_audience(note: dict[str, Any], path: str) -> NoteAudience:
   raw = _required_integer(note, "audience", path)

   try:
      return NoteAudience(raw)
   except ValueError as failure:
      raise SchemaChanged(
         f"{path}.audience holds {raw}, which no audience declares", path=f"{path}.audience"
      ) from failure


def _author_username(item: dict[str, Any], author_id: str, path: str) -> str | None:
   """The username on the tray's picture of the author, when that picture is the author.

   Every measured item carried one picture user whose id was the note's ``author_id``. A
   picture of anyone else is not the author, so it yields nothing rather than a wrong name.
   """

   pog_info = _required(item, "pog_info", path)
   pog_users = _required(pog_info, "pog_users", f"{path}.pog_info")

   if not isinstance(pog_users, list):
      raise SchemaChanged(
         f"{path}.pog_info.pog_users is not a list", path=f"{path}.pog_info.pog_users"
      )

   for index, pog_user in enumerate(pog_users):
      user_path = f"{path}.pog_info.pog_users[{index}]"
      is_the_author = _required_string(pog_user, "id", user_path) == author_id

      if is_the_author:
         return _required_string(pog_user, "username", user_path)

   return None


def parse_note(item: Any, path: str) -> Note:
   """One tray item, mapped field by field.

   ``created_at`` is whole seconds since the Unix epoch as a JSON number, the unit a post's
   ``taken_at`` uses and not the milliseconds string a message carries.

   What the upstream sends and this mapper drops, from the trays recorded on 2026-09-21 and
   2026-09-23:

   - ``note_style``, 0 or 1. Only 0 was produced by a plain text note, and 1 is a song note on
     INFERENCE, so the number has no measured meaning to model.
   - ``note_response_info``, which carries the song on a song note, and ``custom_theme``, a
     colour theme on three of thirteen items. Both belong to capabilities that do not exist.
   - ``pog_info.pog_style`` and the pictures' profile URLs and Facebook-side ids.
   """

   if not isinstance(item, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

   item_type = _required_string(item, "inbox_tray_item_type", path)

   if item_type != NOTE_ITEM_TYPE:
      raise SchemaChanged(
         f"{path}.inbox_tray_item_type is {item_type!r}, not a note",
         path=f"{path}.inbox_tray_item_type",
      )

   note_path = f"{path}.note_dict"
   note = _required(item, "note_dict", path)

   if not isinstance(note, dict):
      raise SchemaChanged(f"{note_path} is not an object", path=note_path)

   author_id = _required_string(note, "author_id", note_path)
   created_at = _required_integer(note, "created_at", note_path)

   return Note(
      id=_required_string(item, "inbox_tray_item_id", path),
      author_id=author_id,
      text=_required_string(note, "text", note_path),
      audience=_note_audience(note, note_path),
      created_at=datetime.fromtimestamp(created_at, tz=UTC),
      is_emoji_only=_required_flag(note, "is_emoji_only", note_path),
      author_username=_author_username(item, author_id, path),
   )


def parse_inbox_tray(payload: Any) -> tuple[Note, ...]:
   """One ``IGDInboxTrayQuery`` payload, mapped into the notes it carries, in the tray's order.

   The tray is the whole answer, one call with no cursor, so a pagination key appearing
   beside the items raises :class:`~dumpstagram.errors.SchemaChanged`: the engine would
   otherwise report a first page as the whole tray.

   Finding: `read-the-notes-tray-on-the-direct-inbox` in the knowledge base.
   """

   tray = _object_at(payload, INBOX_TRAY_PATH)
   tray_path = ".".join(INBOX_TRAY_PATH)

   pagination_keys = sorted(TRAY_PAGINATION_KEYS & tray.keys())

   if pagination_keys:
      raise SchemaChanged(
         f"{tray_path} carries {pagination_keys[0]}, so the tray is no longer one call",
         path=f"{tray_path}.{pagination_keys[0]}",
      )

   items = _required(tray, "inbox_tray_items", tray_path)

   if not isinstance(items, list):
      raise SchemaChanged(
         f"{tray_path}.inbox_tray_items is not a list", path=f"{tray_path}.inbox_tray_items"
      )

   return tuple(
      parse_note(item, f"{tray_path}.inbox_tray_items[{index}]") for index, item in enumerate(items)
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
