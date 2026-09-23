"""Comment on a post and delete one's own comment, each sent once through ``_core/writing.py``.

A comment appends. A second send of the same text is a second comment that everyone who can
see the post sees, so after :class:`~dumpstagram.errors.OutcomeUnknown` the only safe path is to
read the comment page, look for the viewer's own comment made after the attempt began, and only
then decide. The engine never sends a comment again on its own.

A delete sets a state. It names the comment by its id and the post by its media ``pk``, both
digits only, and anything else is refused before a request is built.
"""

from __future__ import annotations

from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.writing import send_write
from dumpstagram._private.transport import WriteRequest
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.parse import comment_was_deleted, parse_created_comment
from dumpstagram._private.web.requests import (
   build_create_comment_request,
   build_delete_comment_request,
   is_a_comment_id,
   is_a_media_pk,
)
from dumpstagram.errors import UpstreamRejected
from dumpstagram.models import Comment
from dumpstagram.session import Session

__all__ = ["create_comment", "delete_comment"]

NOTHING_DELETED = "comment_not_deleted"
"""The code raised when a delete's answer says no comment was deleted."""


async def create_comment(
   sender: PacedSender,
   session: Session,
   post_pk: str,
   text: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Comment:
   """Comment ``text`` on the post whose media ``pk`` is ``post_pk`` and return the comment.

   One write, and one bootstrap first when the session carries no page token.
   """

   _refuse_what_is_not_a_pk(post_pk)

   if not text.strip():
      raise ValueError("a comment needs text")

   if not session.fb_dtsg:
      await bootstrap(sender, session, user_agent=user_agent)

   request = build_create_comment_request(session, post_pk, text, user_agent=user_agent)
   payload = await send_write(sender, session, WriteRequest(request, "comment"))

   return parse_created_comment(payload)


async def delete_comment(
   sender: PacedSender,
   session: Session,
   post_pk: str,
   comment_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> None:
   """Delete the comment ``comment_id`` on the post whose media ``pk`` is ``post_pk``.

   One write, and one bootstrap first when the session carries no page token. Raises
   :class:`~dumpstagram.errors.UpstreamRejected` with code ``comment_not_deleted`` when the
   answer says nothing was deleted, which is what a delete naming no existing comment answered.
   """

   _refuse_what_is_not_a_pk(post_pk)

   if not is_a_comment_id(comment_id):
      raise ValueError(f"{comment_id!r} is not a comment id, which is digits only")

   if not session.fb_dtsg:
      await bootstrap(sender, session, user_agent=user_agent)

   request = build_delete_comment_request(
      session,
      post_pk,
      comment_id,
      client_mutation_id=str(sender.pacer.next_write_number()),
      user_agent=user_agent,
   )
   payload = await send_write(sender, session, WriteRequest(request, "delete_comment"))

   if not comment_was_deleted(payload):
      raise UpstreamRejected(
         "the delete was answered without an error but reported no comment deleted",
         code=NOTHING_DELETED,
      )


def _refuse_what_is_not_a_pk(post_pk: str) -> None:
   if not is_a_media_pk(post_pk):
      raise ValueError(
         f"{post_pk!r} is not a media pk. Pass Post.pk or PostDetail.pk, not the id form"
      )
