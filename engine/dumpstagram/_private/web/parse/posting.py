"""The answers to an upload, a publish and a post delete.

These are REST answers, not GraphQL, and a REST call on this surface reports its outcome in a
``status`` field beside the payload. The classifier recognises the GraphQL envelopes only, so a
``status`` other than ``ok`` is read here and raised as a rejection rather than mapped.

Findings: ``upload-a-photo-for-a-post``, ``publish-a-photo-post``, ``publish-a-carousel-post``
and ``delete-my-own-post`` in the knowledge base.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from dumpstagram._private.web.parse.common import (
   _object_at,
   _required,
   _required_integer,
   _required_string,
)
from dumpstagram.errors import SchemaChanged, UpstreamRejected
from dumpstagram.models import PublishedPost

__all__ = ["check_upload_answer", "parse_published_post", "post_was_deleted"]

_STATUS_OK = "ok"

_REFUSED_WITHOUT_A_TYPE = "status_not_ok"
"""The code raised for a ``status`` other than ``ok`` that names no ``error_type``."""


def check_upload_answer(payload: Any, upload_id: str) -> None:
   """Return quietly when an upload's answer accepts the upload it was sent for.

   Both measured answers were ``{"upload_id", "status": "ok"}`` with the id sent. An answer
   naming another upload is a schema change rather than a success, because a publish naming
   the id that was sent would then publish nothing the caller knows about.
   """

   _raise_unless_ok(payload, "upload")

   answered_id = _required(payload, "upload_id", "<upload>")
   is_the_same_upload = str(answered_id) == upload_id

   if not is_the_same_upload:
      raise SchemaChanged(
         "the upload was answered for a different upload id", path="<upload>.upload_id"
      )


def parse_published_post(payload: Any, upload_ids: tuple[str, ...]) -> PublishedPost:
   """Map a publish answer's ``media`` into the post it created.

   The answer is the private API's media object, 110 keys on the one measured carousel, of
   which only the identifiers, the time and the kind are read here.
   """

   _raise_unless_ok(payload, "publish")

   media = _object_at(payload, ("media",))

   return PublishedPost(
      pk=_required_string(media, "pk", "media"),
      id=_required_string(media, "id", "media"),
      code=_required_string(media, "code", "media"),
      taken_at=datetime.fromtimestamp(_required_integer(media, "taken_at", "media"), tz=UTC),
      media_type=_required_integer(media, "media_type", "media"),
      upload_ids=upload_ids,
   )


def post_was_deleted(payload: Any) -> bool:
   """Whether a post delete's answer says the post was deleted.

   The measured answer carried ``payload.did_delete`` true. Anything but true is not a delete,
   and an answer without the field at all is a schema change.
   """

   answer = _object_at(payload, ("payload",))
   did_delete = _required(answer, "did_delete", "payload")

   return did_delete is True


def _raise_unless_ok(payload: Any, what: str) -> None:
   if not isinstance(payload, dict):
      raise SchemaChanged(f"the {what} answer is not an object", path="<body>")

   status = _required(payload, "status", f"<{what}>")

   if status == _STATUS_OK:
      return

   error_type = payload.get("error_type")
   code = error_type if isinstance(error_type, str) and error_type else _REFUSED_WITHOUT_A_TYPE

   raise UpstreamRejected(f"the {what} was answered with status {status!r}", code=code)
