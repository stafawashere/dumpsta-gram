"""Typed representations of one direct message and the pieces hanging off it.

Every field below was observed on all twenty nodes of a live page on 2026-09-21, recorded in
`engine/logs/message-node-shape-2026-09-21-022957.json`. Fields the upstream sends and this
model does not carry were null on all twenty, or are duplicates, and each omission is named in
`dumpstagram/_private/web/parse/direct.py` beside the mapping that drops it.

Nothing here parses. Construction is done by the mapper in `_private/web/parse/direct.py`, which
reads named keys and raises rather than filling a default, so an upstream rename is loud.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

__all__ = [
   "Message",
   "MessageKind",
   "MessageMedia",
   "MessageMediaKind",
   "MessageSender",
   "Reaction",
   "SentMessage",
]


class MessageKind(StrEnum):
   """What one message is, read from the ``__typename`` of the node's ``content`` object.

   The values are the upstream's own type names, reproduced rather than renamed. Every member
   but :attr:`OTHER` was seen in the 7967-message thread oracle read on 2026-09-22
   (``tests/fixtures/thread_oracle``), where twelve type names covered nineteen
   ``content_type`` values. ``content_type`` stays on :class:`Message` as sent, because it is
   finer: a shared reel, a shared note and an expired story share all arrive as
   :attr:`SHARE`.

   :attr:`OTHER` is a content type name not listed here. A direct thread can hold kinds the
   oracle did not, and failing the whole page over one message would hide every other message
   in it, so such a message is still returned, with this kind, no media, and its
   ``content_type`` as sent. It is a named member a caller can test for, not a guess.
   """

   TEXT = "SlideMessageText"
   IMAGE = "SlideMessageImageContent"
   VIDEO = "SlideMessageVideosContent"
   MULTI_MEDIA = "SlideMessageMultiMediaContent"
   AUDIO = "SlideMessageAudiosContent"
   ANIMATED_IMAGE = "SlideMessageAnimatedMediaContent"
   SHARE = "SlideMessageXMAContent"
   STICKER = "SlideMessageCutoutStickerXMAContent"
   MUSIC_STICKER = "SlideMessageMusicStickerXMAContent"
   VIEW_ONCE_IMAGE = "SlideMessageRavenImageContent"
   VIEW_ONCE_VIDEO = "SlideMessageRavenVideoContent"
   ACTION_LOG = "SlideMessageAdminText"
   OTHER = "other"


class MessageMediaKind(StrEnum):
   """What one :class:`MessageMedia` holds."""

   IMAGE = "image"
   VIDEO = "video"
   AUDIO = "audio"
   ANIMATED_IMAGE = "animated_image"
   STICKER = "sticker"
   SHARE_PREVIEW = "share_preview"


@dataclass(frozen=True)
class MessageMedia:
   """One picture, video, voice clip or preview a message carries.

   ``url`` is the asset itself: the photo, the video file, the voice clip, the animated image
   as WebP, the sticker, or for a share the preview picture the share shows. ``preview_url`` is
   the still the thread draws before the asset loads, where the upstream sends one.
   ``width`` and ``height`` are the preview's, the only dimensions sent, and ``None`` for a
   voice clip. ``duration_ms`` is set for a voice clip only.

   Every URL is a signed CDN address that expires, so a message read long ago may no longer
   load. A view-once photo or video carries none: its attachment was null on fourteen of the
   sixteen in the oracle, and opening one is something a person does on purpose.
   """

   kind: MessageMediaKind
   url: str
   preview_url: str | None = None
   width: int | None = None
   height: int | None = None
   duration_ms: int | None = None


@dataclass(frozen=True)
class MessageSender:
   """Who sent a message, by the identifier the message itself carries.

   ``fbid`` comes from the message's own ``sender_fbid`` rather than from the nested sender
   object, because that is the field present on every node whether the sender object resolves
   or not. ``igid`` is the Instagram-side identifier for the same account and is a different
   number, so the two are never interchanged. Passing the wrong one of the two to an endpoint
   returns nothing rather than an error, which is why the field names say which is which.
   """

   fbid: str
   igid: str | None = None
   name: str | None = None


@dataclass(frozen=True)
class Reaction:
   """One reaction on one message.

   Mapped from the node's ``reactions`` list. The node also carries ``msg_reactions``, which
   lists the same senders by ``sender_fbid`` with their ``sender_igid`` and no emoji: the two
   named the same senders on all 293 reacted messages of the thread oracle. ``sender_igid`` is
   read from it, and ``None`` when it lists no entry for this sender.

   ``is_from_viewer`` is whether the viewer reacted: ``sender_igid`` equal to the session's
   ``ds_user_id``, the rule :attr:`Message.is_from_viewer` uses. ``None`` when ``sender_igid``
   is, because then nothing on the node says who reacted.
   """

   emoji: str
   sender_fbid: str
   sender_igid: str | None = None
   is_from_viewer: bool | None = None


@dataclass(frozen=True)
class Message:
   """One message in one direct thread.

   ``id`` is the upstream ``id``, a ``mid.``-prefixed string. The node also carries
   ``message_id``, which held the identical value on all twenty measured nodes, so it is
   treated as a second name for this field rather than as a second identifier.

   ``sent_at`` is timezone-aware UTC, converted from the upstream ``timestamp_ms``, which
   arrives as a thirteen-digit string of milliseconds since the Unix epoch.

   ``text`` is ``None`` when the upstream sends no body, which is a different state from an
   empty string, and both are different from the field being absent. Only ``content_type``
   ``TEXT`` has been observed, so ``text`` for any other content type is unmeasured.

   ``offline_threading_id`` is the identifier the sending client generated for the message,
   which the thread read echoes back. It is how a message sent with
   :meth:`~dumpstagram.aio.AsyncClient.send_message` is found again exactly, by
   :attr:`SentMessage.offline_threading_id`. Every live node measured carries it. ``None``
   when a node carries it as null or not at all.

   ``is_from_viewer`` is whether the viewer sent the message: the sender's ``igid`` equal to the
   session's ``ds_user_id``. On 2026-10-18 that agreed on all 40 messages of two live threads
   with the sender's ``fbid`` equal to the viewer's messaging id, the inbox's mailbox id, and
   neither matched ``Session.actor_id``, which is a third id (log
   ``viewer-identity-identity-2026-10-18-042908.json``). ``None`` when the node's sender
   carries no ``igid``, which none of the 8007 measured nodes did.

   ``kind`` is what the message is, and ``media`` what it carries to draw, in the upstream's
   order: one item for most kinds, several for a multi-photo message, none for text, an action
   log line, a view-once item, a music sticker or an unknown kind. A share carries its preview
   picture when the share has one.
   """

   id: str
   thread_fbid: str
   sender: MessageSender
   sent_at: datetime
   text: str | None
   content_type: str
   reactions: tuple[Reaction, ...] = ()
   replied_to_message_id: str | None = None
   is_forwarded: bool = False
   is_pinned: bool = False
   is_ai_generated: bool = False
   offline_threading_id: str | None = None
   is_from_viewer: bool | None = None
   kind: MessageKind = MessageKind.OTHER
   media: tuple[MessageMedia, ...] = ()


@dataclass(frozen=True)
class SentMessage:
   """What the upstream answers about a text message just sent.

   The send's answer carries the message's ``id`` and its ``sent_at`` and nothing else, so this
   is not a :class:`Message`: the sender's ``fbid`` is not in the answer or in the session, and
   a model that filled it in would be guessing. Reading the thread gives the full
   :class:`Message`, and ``offline_threading_id`` is the client-generated identifier the send
   carried, which the read echoes on the same message.
   """

   id: str
   thread_fbid: str
   sent_at: datetime
   offline_threading_id: str
