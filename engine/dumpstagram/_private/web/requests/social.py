"""The follow and unfollow requests, keyed on the numeric account id."""

from __future__ import annotations

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, ORIGIN
from dumpstagram._private.web.documents.social import FOLLOW_USER, UNFOLLOW_USER
from dumpstagram._private.web.requests.common import _USER_ID, build_graphql_request
from dumpstagram.session import Session

__all__ = [
   "build_follow_request",
   "build_unfollow_request",
   "is_a_user_id",
]


def is_a_user_id(value: str) -> bool:
   """Whether ``value`` has the shape of a numeric account id, digits only.

   A username fails this, which is the mistake it exists to catch: the follow mutations take
   the id, and what they do with a username is unobserved.
   """

   return _USER_ID.fullmatch(value) is not None


def build_follow_request(
   session: Session,
   user_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Follow the account whose numeric id is ``user_id``.

   The one variable is ``target_user_id``, not wrapped in ``input``, so the Relay network layer
   adds no ``client_mutation_id``. The referer is the home page, where the compiled artifact was
   read off a suggested account's Follow button, and where both engine sends came from.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/follow-a-user.md``.
   """

   return build_graphql_request(
      session,
      FOLLOW_USER,
      {"target_user_id": user_id},
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )


def build_unfollow_request(
   session: Session,
   user_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Unfollow the account whose numeric id is ``user_id``.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/unfollow-a-user.md``.
   """

   return build_graphql_request(
      session,
      UNFOLLOW_USER,
      {"target_user_id": user_id},
      referer=f"{ORIGIN}/",
      user_agent=user_agent,
   )
