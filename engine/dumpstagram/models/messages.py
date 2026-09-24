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

__all__ = ["Message", "MessageSender", "Reaction", "SentMessage"]


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
   was non-empty on exactly the same message and carries no emoji, so it is dropped rather
   than merged.
   """

   emoji: str
   sender_fbid: str


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
