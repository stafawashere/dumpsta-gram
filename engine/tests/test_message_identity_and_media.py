"""Gates on who sent a message, who reacted, what a message is, and what it carries to draw.

Release phase 2, items 1 and 2. The viewer rule is the sender's ``igid`` equal to the session's
``ds_user_id``, measured live on 2026-10-18 against the sender's ``fbid`` and the mailbox id on 40
of 40 messages (``engine/logs/viewer-identity-identity-2026-10-18-042908.json``). The kinds and
media addresses come from the pseudonymised thread oracle of 2026-09-22, whose nodes are used as
they are, so a mapper key that drifts from the recorded shape fails here and not in the app.

Four defects live here. The read can forget to tell the mapper who the viewer is, so every
message says ``None``. A reaction can take its sender's ``igid`` from the wrong entry of
``msg_reactions``. A media list can be read from the wrong key, so every photo is lost without
an error. And an unknown content type can fail a whole thread page.

Every response is canned. Nothing in this file touches the network.
"""

from __future__ import annotations

import copy
import gzip
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from dumpstagram._private.web.parse.direct import parse_thread_message_page
from dumpstagram.behavior import Behavior
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import Message, MessageKind, MessageMedia, MessageMediaKind
from tests.test_direct import ScriptedTransport, a_bootstrapped_session, json_response
from tests.test_parse import node, payload
from tests.test_poller import a_poller, listing, message_ids, row, thread_page
from tests.test_thread_route import detail_payload, read_through_a_client

ORACLE = Path(__file__).parent / "fixtures" / "thread_oracle" / "pages.json.gz"

VIEWER_IGID = "1234567890"
"""``ds_user_id`` of :func:`tests.test_direct.a_bootstrapped_session`."""

VIEWER_FBID = "17841400000000001"
OTHER_IGID = "1111111111"
OTHER_FBID = "17841400000000000"

ORACLE_KIND_COUNTS = {
   MessageKind.TEXT: 7522,
   MessageKind.ACTION_LOG: 233,
   MessageKind.SHARE: 100,
   MessageKind.IMAGE: 46,
   MessageKind.ANIMATED_IMAGE: 19,
   MessageKind.VIDEO: 15,
   MessageKind.VIEW_ONCE_IMAGE: 14,
   MessageKind.STICKER: 7,
   MessageKind.MUSIC_STICKER: 4,
   MessageKind.AUDIO: 4,
   MessageKind.VIEW_ONCE_VIDEO: 2,
   MessageKind.MULTI_MEDIA: 1,
}
"""Each kind's count over the oracle's 7967 messages, counted independently of the mapper."""


def oracle_nodes() -> list[dict[str, Any]]:
   pages = json.loads(gzip.decompress(ORACLE.read_bytes()))

   return [
      edge["node"]
      for page in pages
      for edge in page["payload"]["data"]["fetch__SlideThread"]["as_ig_direct_thread"][
         "slide_messages"
      ]["edges"]
   ]


def first_of(typename: str, *, xma: str | None = None) -> dict[str, Any]:
   for candidate in oracle_nodes():
      content = candidate["content"]
      is_the_kind = content["__typename"] == typename
      is_the_share = xma is None or (content.get("xma") or {}).get("__typename") == xma

      if is_the_kind and is_the_share:
         return copy.deepcopy(candidate)

   raise AssertionError(f"the oracle holds no {typename} {xma or ''}")


def mapped(*nodes: dict[str, Any], viewer_igid: str | None = VIEWER_IGID) -> list[Message]:
   return list(parse_thread_message_page(payload(list(nodes)), viewer_igid=viewer_igid).items)


def from_viewer(**overrides: Any) -> dict[str, Any]:
   return node(
      sender={"id": "sender-node-id", "igid": VIEWER_IGID, "name": "me", "user_dict": None},
      sender_fbid=VIEWER_FBID,
      **overrides,
   )


def reacted_by_both() -> dict[str, Any]:
   """Reactions listed in a different order from ``msg_reactions``, as the upstream may."""

   return node(
      reactions=[
         {"reaction": "\u2764", "sender_fbid": OTHER_FBID},
         {"reaction": "\U0001f602", "sender_fbid": VIEWER_FBID},
      ],
      msg_reactions=[
         {"sender_fbid": VIEWER_FBID, "sender_igid": VIEWER_IGID},
         {"sender_fbid": OTHER_FBID, "sender_igid": OTHER_IGID},
      ],
   )


# Who sent it, and who reacted.


def test_the_viewers_message_and_anothers_are_told_apart_by_igid() -> None:
   """Catches the rule reading the fbid or the actor id, neither of which is ``ds_user_id``."""

   mine, theirs = mapped(from_viewer(), node())

   assert mine.is_from_viewer is True
   assert theirs.is_from_viewer is False


def test_without_the_viewer_nothing_is_claimed() -> None:
   """Catches a mapper defaulting to False, which says "not mine" about the viewer's own."""

   (message,) = mapped(from_viewer(), viewer_igid=None)

   assert message.is_from_viewer is None
   assert all(reaction.is_from_viewer is None for reaction in message.reactions)


def test_a_sender_without_an_igid_is_not_claimed_either_way() -> None:
   """Catches a missing igid read as "not the viewer"."""

   (message,) = mapped(node(sender=None))

   assert message.sender.igid is None
   assert message.is_from_viewer is None


def test_each_reaction_takes_the_igid_its_own_sender_fbid_names() -> None:
   """Catches pairing ``reactions`` and ``msg_reactions`` by position rather than by sender."""

   (message,) = mapped(reacted_by_both())

   assert [(r.emoji, r.sender_igid, r.is_from_viewer) for r in message.reactions] == [
      ("\u2764", OTHER_IGID, False),
      ("\U0001f602", VIEWER_IGID, True),
   ]


def test_a_reaction_msg_reactions_does_not_list_has_no_owner() -> None:
   """Catches a reaction with no igid entry claimed for the viewer or against it."""

   reacted = node(reactions=[{"reaction": "\u2764", "sender_fbid": OTHER_FBID}], msg_reactions=[])

   (message,) = mapped(reacted)

   assert message.reactions[0].sender_igid is None
   assert message.reactions[0].is_from_viewer is None


def test_the_oracle_marks_exactly_one_participants_messages_and_reactions() -> None:
   """Catches the rule drifting on real nodes: every message of one participant, none of the
   other's, and the reactions on the same split, with 293 reacted messages in play."""

   nodes = oracle_nodes()
   viewer = nodes[0]["sender"]["igid"]
   messages = mapped(*nodes, viewer_igid=viewer)
   reactions = [reaction for message in messages for reaction in message.reactions]

   assert all(message.is_from_viewer == (message.sender.igid == viewer) for message in messages)
   assert {message.is_from_viewer for message in messages} == {True, False}
   assert len(reactions) == 293
   assert all(reaction.sender_igid is not None for reaction in reactions)
   assert all(reaction.is_from_viewer == (reaction.sender_igid == viewer) for reaction in reactions)


@pytest.mark.asyncio
async def test_a_thread_read_tells_the_mapper_who_the_viewer_is() -> None:
   """Catches ``_core.direct`` calling the mapper without the session's ``ds_user_id``."""

   transport = ScriptedTransport([json_response(detail_payload([from_viewer(), node()]))])

   messages = await read_through_a_client(transport, Behavior())

   assert [message.is_from_viewer for message in messages] == [True, False]


@pytest.mark.asyncio
async def test_an_older_page_tells_the_mapper_who_the_viewer_is() -> None:
   """Catches the scrolling route alone forgetting the viewer."""

   transport = ScriptedTransport([json_response(payload([from_viewer(), node()]))])

   messages = await read_through_a_client(transport, Behavior(), after="cursor")

   assert [message.is_from_viewer for message in messages] == [True, False]


@pytest.mark.asyncio
async def test_a_polled_message_says_whether_the_viewer_sent_it() -> None:
   """Catches the listener's read back mapping without the viewer, so every event says None."""

   moved = row("17800000000000012", [("mid.$b2", 30), ("mid.$b1", 5)])
   quiet = row("17800000000000012", [("mid.$b1", 5)])
   transport = ScriptedTransport(
      [listing(quiet), listing(moved), thread_page("17800000000000012", [("mid.$b2", 30)])]
   )
   poller = a_poller(transport, session=a_bootstrapped_session())

   await poller.poll()
   found = await poller.poll()

   assert message_ids(found) == ["mid.$b2"]
   assert [item.is_from_viewer for item in found if isinstance(item, Message)] == [False]


# What it is, and what it carries.


def test_every_oracle_message_has_a_named_kind_in_the_counts_recorded() -> None:
   """Catches a kind's type name drifting, which would sort real messages into OTHER."""

   counts = Counter(message.kind for message in mapped(*oracle_nodes()))

   assert counts == ORACLE_KIND_COUNTS


def test_text_carries_no_media() -> None:
   (message,) = mapped(node())

   assert message.kind is MessageKind.TEXT
   assert message.media == ()


def test_a_photo_carries_its_full_picture_preview_and_size() -> None:
   """Catches the preview taken for the photo, or the photo list read from the wrong key."""

   original = first_of("SlideMessageImageContent")
   attachment = original["content"]["attachments"][0]

   (message,) = mapped(original)

   assert message.kind is MessageKind.IMAGE
   assert message.content_type == "IMAGES"
   assert message.media[0] == MessageMedia(
      kind=MessageMediaKind.IMAGE,
      url=attachment["attachment_cdn_url"],
      preview_url=attachment["preview_cdn_url"],
      width=attachment["preview_width"],
      height=attachment["preview_height"],
   )
   assert len(message.media) == len(original["content"]["attachments"])


def test_a_video_carries_its_file_not_its_preview() -> None:
   original = first_of("SlideMessageVideosContent")
   video = original["content"]["videos"][0]

   (message,) = mapped(original)

   assert message.kind is MessageKind.VIDEO
   assert message.media[0].kind is MessageMediaKind.VIDEO
   assert message.media[0].url == video["attachment_cdn_url"]
   assert message.media[0].preview_url == video["preview_cdn_url"]


def test_a_multi_media_message_keeps_its_photos_and_videos_in_order() -> None:
   """Catches a mixed list mapped as all photos, or reordered."""

   original = first_of("SlideMessageMultiMediaContent")
   attachments = original["content"]["ordered_photo_video_attachments"]
   expected = [
      MessageMediaKind.VIDEO
      if item["__typename"] == "XFBSlideVideoAttachment"
      else MessageMediaKind.IMAGE
      for item in attachments
   ]

   (message,) = mapped(original)

   assert [item.kind for item in message.media] == expected
   assert [item.url for item in message.media] == [a["attachment_cdn_url"] for a in attachments]
   assert MessageMediaKind.VIDEO in expected and MessageMediaKind.IMAGE in expected


def test_a_voice_clip_carries_its_address_and_length() -> None:
   original = first_of("SlideMessageAudiosContent")
   clip = original["content"]["audio_attachments"][0]

   (message,) = mapped(original)

   assert message.kind is MessageKind.AUDIO
   assert message.media == (
      MessageMedia(
         kind=MessageMediaKind.AUDIO,
         url=clip["attachment_cdn_url"],
         duration_ms=clip["playable_duration_ms"],
      ),
   )


def test_an_animated_image_carries_its_webp() -> None:
   original = first_of("SlideMessageAnimatedMediaContent")
   animated = original["content"]["animated_media"][0]

   (message,) = mapped(original)

   assert message.media[0].kind is MessageMediaKind.ANIMATED_IMAGE
   assert message.media[0].url == animated["attachment_webp_url"]
   assert message.media[0].preview_url == animated["preview_cdn_url"]


def test_a_sticker_carries_its_picture() -> None:
   original = first_of("SlideMessageCutoutStickerXMAContent")

   (message,) = mapped(original)

   assert message.kind is MessageKind.STICKER
   assert message.media[0].kind is MessageMediaKind.STICKER
   assert message.media[0].url == original["content"]["preview_url"]


def test_a_shared_reel_carries_its_preview_picture() -> None:
   original = first_of("SlideMessageXMAContent", xma="SlideMessagePortraitXMA")
   image = original["content"]["xma"]["preview_image"]

   (message,) = mapped(original)

   assert message.kind is MessageKind.SHARE
   assert message.media == (
      MessageMedia(
         kind=MessageMediaKind.SHARE_PREVIEW,
         url=image["url"],
         width=image["width"],
         height=image["height"],
      ),
   )


def test_an_expired_share_carries_nothing_to_draw() -> None:
   (message,) = mapped(first_of("SlideMessageXMAContent", xma="SlideMessageExpiredPlaceholderXMA"))

   assert message.kind is MessageKind.SHARE
   assert message.media == ()


def test_a_view_once_photo_carries_nothing_to_draw() -> None:
   (message,) = mapped(first_of("SlideMessageRavenImageContent"))

   assert message.kind is MessageKind.VIEW_ONCE_IMAGE
   assert message.media == ()


def test_an_unknown_content_type_is_returned_as_other_with_the_rest_of_the_page() -> None:
   """Catches one unfamiliar message failing every message on its page."""

   unknown = node(
      content={"__typename": "SlideMessagePollContent", "poll": {}},
      content_type="POLL",
      id="mid.$unknown",
   )

   unknown_message, text = mapped(unknown, node())

   assert unknown_message.kind is MessageKind.OTHER
   assert unknown_message.content_type == "POLL"
   assert unknown_message.media == ()
   assert text.kind is MessageKind.TEXT


def test_a_photo_without_its_address_is_a_schema_change() -> None:
   """Catches a missing photo address mapped as a message with nothing to draw."""

   original = first_of("SlideMessageImageContent")
   del original["content"]["attachments"][0]["attachment_cdn_url"]

   with pytest.raises(SchemaChanged, match="attachment_cdn_url"):
      mapped(original)


def test_an_unknown_attachment_in_a_media_list_is_a_schema_change() -> None:
   original = first_of("SlideMessageMultiMediaContent")
   original["content"]["ordered_photo_video_attachments"][0]["__typename"] = "XFBSlideHologram"

   with pytest.raises(SchemaChanged, match="XFBSlideHologram"):
      mapped(original)


def test_a_node_without_content_is_a_schema_change() -> None:
   broken = node()
   del broken["content"]

   with pytest.raises(SchemaChanged, match="content"):
      mapped(broken)
