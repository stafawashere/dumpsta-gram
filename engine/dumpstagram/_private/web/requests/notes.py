"""The notes requests: the tray on the direct inbox, and setting and deleting the viewer's note."""

from __future__ import annotations

import re

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import BOOTSTRAP_URL, DEFAULT_USER_AGENT
from dumpstagram._private.web.documents.notes import CREATE_NOTE, DELETE_NOTE, INBOX_TRAY
from dumpstagram._private.web.requests.common import build_graphql_request
from dumpstagram.errors import SchemaChanged
from dumpstagram.session import Session

__all__ = [
   "build_create_note_request",
   "build_delete_note_request",
   "build_inbox_tray_request",
   "is_a_note_id",
]

_NOTE_ID = re.compile(r"[0-9]{1,30}")

NOTE_STYLE_TEXT = 0
"""The ``note_style`` of a plain text note, the only style a create has sent."""


def build_inbox_tray_request(
   session: Session,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The notes tray, asked for the way the inbox asks for it: no variables, the inbox as referer.

   The query goes to ``/api/graphql`` and carries neither path header, as on every captured
   inbox load.

   Finding: ``read-the-notes-tray-on-the-direct-inbox`` in the knowledge base.
   """

   return build_graphql_request(
      session,
      INBOX_TRAY,
      {},
      referer=BOOTSTRAP_URL,
      user_agent=user_agent,
   )


def build_create_note_request(
   session: Session,
   text: str,
   audience: int,
   *,
   client_mutation_id: str,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Set the viewer's note to ``text`` for ``audience``, 0 for followers followed back, 1 for
   close friends.

   ``actor_id`` is the account's Facebook-side id from the bootstrap page, and never
   ``ds_user_id``, which the finding records as a different number for the same account. A
   session that has not read it raises :class:`~dumpstagram.errors.SchemaChanged`, because the
   capability bootstraps before building, so a missing id means the page stopped carrying it.
   The referer is the inbox, where the composer lives.

   Finding: ``set-my-own-note-on-the-direct-inbox`` in the knowledge base.
   """

   if not session.actor_id:
      raise SchemaChanged(
         "the bootstrap page carried no RelayAPIConfigDefaults actorID, so the actor_id a note "
         "create needs cannot be sent",
         path="RelayAPIConfigDefaults.actorID",
      )

   return build_graphql_request(
      session,
      CREATE_NOTE,
      {
         "input": {
            "actor_id": session.actor_id,
            "additional_params": {
               "note_create_params": {"note_style": NOTE_STYLE_TEXT, "text": text}
            },
            "audience": audience,
            "client_mutation_id": client_mutation_id,
            "inbox_tray_item_type": "note",
         }
      },
      referer=BOOTSTRAP_URL,
      user_agent=user_agent,
   )


def is_a_note_id(value: str) -> bool:
   """Whether ``value`` has the shape of a tray item id, digits only, 17 on every one observed."""

   return _NOTE_ID.fullmatch(value) is not None


def build_delete_note_request(
   session: Session,
   note_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Delete the note whose tray item id is ``note_id``.

   The one variable is the tray item id, not wrapped in ``input``, so the Relay network layer
   adds no ``client_mutation_id``.

   Finding: ``delete-my-own-note-on-the-direct-inbox`` in the knowledge base.
   """

   return build_graphql_request(
      session,
      DELETE_NOTE,
      {"inbox_tray_item_id": note_id},
      referer=BOOTSTRAP_URL,
      user_agent=user_agent,
   )
