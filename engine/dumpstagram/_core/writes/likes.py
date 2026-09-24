"""Like and unlike a post, each sent once through ``_core/writing.py``.

Both set a state rather than append one, and a repeat converges: on 2026-09-23 a second like
of a liked post and a second unlike of an unliked one each answered like the first and moved
``like_count`` no further. So after :class:`~dumpstagram.errors.OutcomeUnknown` a caller may
read the post and send again, and the engine still does not send again on its own.

The post is named by its media ``pk``. The ``<pk>_<author id>`` form a post also carries is
refused before anything is built, because nothing records what the upstream does with it.
"""

from __future__ import annotations

from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.writing import send_write
from dumpstagram._private.transport import WriteRequest
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.parse.media import (
   LIKE_ANSWER_ROOT,
   UNLIKE_ANSWER_ROOT,
   parse_like_answer,
)
from dumpstagram._private.web.requests.media import (
   build_like_request,
   build_unlike_request,
   is_a_media_pk,
)
from dumpstagram.errors import UpstreamRejected
from dumpstagram.session import Session

__all__ = ["like_post", "unlike_post"]

LIKE_NOT_APPLIED = "has_liked_did_not_follow"
"""The code raised when an answer without an error names the opposite state."""


async def like_post(
   sender: PacedSender,
   session: Session,
   post_pk: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> None:
   """Like the post whose media ``pk`` is ``post_pk``. One write, and one bootstrap first when
   the session carries no page token."""

   _refuse_what_is_not_a_pk(post_pk)

   if not session.fb_dtsg:
      await bootstrap(sender, session, user_agent=user_agent)

   request = build_like_request(
      session,
      post_pk,
      client_mutation_id=str(sender.pacer.next_write_number()),
      user_agent=user_agent,
   )
   payload = await send_write(sender, session, WriteRequest(request, "like"))

   _require_the_state(parse_like_answer(payload, LIKE_ANSWER_ROOT), wanted=True)


async def unlike_post(
   sender: PacedSender,
   session: Session,
   post_pk: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> None:
   """Unlike the post whose media ``pk`` is ``post_pk``. One write, and one bootstrap first
   when the session carries no page token."""

   _refuse_what_is_not_a_pk(post_pk)

   if not session.fb_dtsg:
      await bootstrap(sender, session, user_agent=user_agent)

   request = build_unlike_request(
      session,
      post_pk,
      client_mutation_id=str(sender.pacer.next_write_number()),
      user_agent=user_agent,
   )
   payload = await send_write(sender, session, WriteRequest(request, "unlike"))

   _require_the_state(parse_like_answer(payload, UNLIKE_ANSWER_ROOT), wanted=False)


def _refuse_what_is_not_a_pk(post_pk: str) -> None:
   if not is_a_media_pk(post_pk):
      raise ValueError(
         f"{post_pk!r} is not a media pk. Pass Post.pk or PostDetail.pk, not the id form"
      )


def _require_the_state(has_liked: bool, *, wanted: bool) -> None:
   """Raise when the upstream answered without an error but named the other state.

   Never observed. It is raised rather than ignored because a caller told nothing would take
   the write as applied.
   """

   if has_liked is not wanted:
      raise UpstreamRejected(
         f"the answer reported has_liked {has_liked} after a write asking for {wanted}",
         code=LIKE_NOT_APPLIED,
      )
