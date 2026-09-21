"""The profile capability, written once, asynchronously.

Both public surfaces call this. ``SyncClient`` reaches it across the loop thread and
``AsyncClient`` awaits it directly, and neither adds behavior on the way, which is what
ADR-0001 means by one implementation and two doors.

Nothing here knows the upstream speaks GraphQL. The adapter in `_private/web/` owns the
document ids, the variables and the field names, and hands back typed models.

The shape of this capability is set by the surface rather than by taste. The profile query
takes an account id and nothing else, so reading a profile from a username costs two live
requests and reading one from an id costs one. That difference is visible in the public API
on purpose, because hiding it would make a caller holding an id pay for a resolution it does
not need.
"""

from __future__ import annotations

from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse import parse_profile, parse_user_id
from dumpstagram._private.web.requests import (
   build_profile_request,
   build_username_resolution_request,
)
from dumpstagram.errors import NotFound
from dumpstagram.models import Profile
from dumpstagram.session import Session

__all__ = ["read_profile", "read_profile_by_id", "resolve_username"]


async def resolve_username(
   sender: PacedSender,
   session: Session,
   username: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> str:
   """The numeric account id behind ``username``, in one live request.

   Raises :class:`~dumpstagram.errors.NotFound` when the upstream answers with an empty
   timeline. That covers an account that does not exist and an account whose posts the viewer
   cannot see, and the upstream does not distinguish the two on this route, so neither does
   this. An account that genuinely has no posts is reachable by id and not by username.
   """

   async def attempt() -> str:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_username_resolution_request(session, username, user_agent=user_agent)
      response = await sender.send(request)
      user_id = parse_user_id(classify(response))

      if user_id is None:
         raise NotFound(
            f"no account id came back for {username!r}, which means the account does not "
            "exist, its posts are not visible to this session, or it has none"
         )

      return user_id

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_profile_by_id(
   sender: PacedSender,
   session: Session,
   user_id: str,
   *,
   username_for_referer: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> Profile:
   """One account's profile, in one live request, keyed on the numeric account id."""

   async def attempt() -> Profile:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_profile_request(
         session,
         user_id,
         username_for_referer=username_for_referer,
         user_agent=user_agent,
      )
      response = await sender.send(request)

      return parse_profile(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)


async def read_profile(
   sender: PacedSender,
   session: Session,
   username: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> Profile:
   """One account's profile, found by username, in two live requests.

   The two are serial because the second needs the first one's answer, which is the ordinary
   case for ``_core`` under ADR-0001 rather than a missed chance to run them together.
   """

   user_id = await resolve_username(
      sender, session, username, user_agent=user_agent, deadline=deadline
   )

   return await read_profile_by_id(
      sender,
      session,
      user_id,
      username_for_referer=username,
      user_agent=user_agent,
      deadline=deadline,
   )
