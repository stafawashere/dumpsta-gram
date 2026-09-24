"""Follow and unfollow an account, each sent once through ``_core/writing.py``.

Both set a state rather than append one. Whether a second follow of a followed account answers
like the first is unobserved, unlike the like pair, so the read that reconciles an unknown
outcome is the account's profile, whose ``friendship_status`` says where things stand.

The account is named by its numeric id. A username is refused before anything is built.

A follow is checked less strictly than an unfollow. Its answer selects ``following`` alone, and
a follow of a private account becomes a request that leaves ``following`` false, so an answer of
false is not proof that nothing happened. An unfollow always ends with ``following`` false, so an
answer of true means it did not apply.
"""

from __future__ import annotations

from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.writing import send_write
from dumpstagram._private.transport import WriteRequest
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.parse.social import (
   FOLLOW_ANSWER_ROOT,
   UNFOLLOW_ANSWER_ROOT,
   parse_follow_answer,
)
from dumpstagram._private.web.requests.social import (
   build_follow_request,
   build_unfollow_request,
   is_a_user_id,
)
from dumpstagram.errors import UpstreamRejected
from dumpstagram.session import Session

__all__ = ["follow_user", "unfollow_user"]

UNFOLLOW_NOT_APPLIED = "following_did_not_end"
"""The code raised when an unfollow's answer without an error still reports following."""


async def follow_user(
   sender: PacedSender,
   session: Session,
   user_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> None:
   """Follow the account whose numeric id is ``user_id``. One write, and one bootstrap first
   when the session carries no page token."""

   _refuse_what_is_not_an_id(user_id)

   if not session.fb_dtsg:
      await bootstrap(sender, session, user_agent=user_agent)

   request = build_follow_request(session, user_id, user_agent=user_agent)
   payload = await send_write(sender, session, WriteRequest(request, "follow"))

   parse_follow_answer(payload, FOLLOW_ANSWER_ROOT, user_id)


async def unfollow_user(
   sender: PacedSender,
   session: Session,
   user_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> None:
   """Unfollow the account whose numeric id is ``user_id``. One write, and one bootstrap first
   when the session carries no page token."""

   _refuse_what_is_not_an_id(user_id)

   if not session.fb_dtsg:
      await bootstrap(sender, session, user_agent=user_agent)

   request = build_unfollow_request(session, user_id, user_agent=user_agent)
   payload = await send_write(sender, session, WriteRequest(request, "unfollow"))

   still_following = parse_follow_answer(payload, UNFOLLOW_ANSWER_ROOT, user_id)

   if still_following:
      raise UpstreamRejected(
         "the answer reported following true after an unfollow",
         code=UNFOLLOW_NOT_APPLIED,
      )


def _refuse_what_is_not_an_id(user_id: str) -> None:
   if not is_a_user_id(user_id):
      raise ValueError(f"{user_id!r} is not a numeric account id. Pass Profile.id, not a username")
