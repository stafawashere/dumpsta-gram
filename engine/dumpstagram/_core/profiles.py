"""The profile capability, written once, asynchronously.

Both public surfaces call this. ``SyncClient`` reaches it across the loop thread and
``AsyncClient`` awaits it directly, and neither adds behavior on the way, which is what
ADR-0001 means by one implementation and two doors.

Nothing here knows the upstream speaks GraphQL. The adapter in `_private/web/` owns the
document ids, the variables and the field names, and hands back typed models.

The shape of this capability is set by the surface rather than by taste. The profile query
takes an account id and nothing else. A browser gets the id from the profile page it loads,
and :attr:`ProfileRoute.PAGE` does the same, sending the page's six queries at once as one
action. :attr:`ProfileRoute.QUERIES` resolves the id through a timeline query instead, which is
the departure. A caller that already holds an id reads the profile query alone, since no
browser page is keyed on an id.

The six queries are the one place in ``_core`` that sends concurrently. ADR-0001 keeps the core
serial unless concurrency is known to help, and here it is what makes the requests look like
the page's: both measured loads sent all six within 5 ms.
"""

from __future__ import annotations

from dumpstagram._core.pacer import run_with_retries
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._private.transport import Response
from dumpstagram._private.web.bootstrap import (
   DEFAULT_USER_AGENT,
   apply_tokens,
   bootstrap,
   build_document_request,
   tokens_from,
)
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse import parse_profile, parse_user_id
from dumpstagram._private.web.preload import read_profile_id
from dumpstagram._private.web.requests import (
   build_profile_page_requests,
   build_profile_request,
   build_username_resolution_request,
   profile_page_url,
)
from dumpstagram.behavior import ProfileRoute
from dumpstagram.errors import NotFound, SchemaChanged, UpstreamRejected
from dumpstagram.models import Profile
from dumpstagram.session import Session

__all__ = [
   "read_profile",
   "read_profile_by_id",
   "read_profile_from_page",
   "resolve_username",
]


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
   route: ProfileRoute = ProfileRoute.QUERIES,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> Profile:
   """One account's profile, found by username.

   Under :attr:`ProfileRoute.QUERIES` that is two live requests, serial because the second
   needs the first one's answer. Under :attr:`ProfileRoute.PAGE` it is the page load
   :func:`read_profile_from_page` describes. ``QUERIES`` stays the default at this level so
   callers below the client keep the route they had, and the client passes its behavior down.
   """

   if route is ProfileRoute.PAGE:
      return await read_profile_from_page(
         sender, session, username, user_agent=user_agent, deadline=deadline
      )

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


async def read_profile_from_page(
   sender: PacedSender,
   session: Session,
   username: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> Profile:
   """One account's profile, read the way a browser's profile page reads it.

   One action: the profile page document, then its six queries at once. The document needs no
   page token and carries fresh ones, which are written onto the session before the queries
   are built, so there is no stale token to recover from.

   Raises :class:`~dumpstagram.errors.NotFound` when the page is about no account, which is
   how the upstream answered for a username nobody holds. Unlike the timeline route, an
   account with no visible posts is found.

   Only the profile query's answer is read. The other five are checked for a checkpoint or a
   throttle, which concern the whole account, and otherwise left alone, so a companion the
   upstream stops answering does not cost the caller the profile.
   """

   page_url = profile_page_url(username)

   async def attempt() -> Profile:
      async with sender.action() as action:
         document = await action.send(build_document_request(page_url, user_agent))

         apply_tokens(session, tokens_from(document))
         user_id = read_profile_id(document.text)

         if user_id is None:
            raise NotFound(f"no account has the username {username!r}")

         requests = build_profile_page_requests(session, user_id, username, user_agent=user_agent)
         profile_response, *companion_responses = await action.send_together(requests)

      for companion in companion_responses:
         _raise_only_what_concerns_the_account(companion)

      return parse_profile(classify(profile_response))

   return await run_with_retries(attempt, pacer=sender.pacer, deadline=deadline)


def _raise_only_what_concerns_the_account(response: Response) -> None:
   try:
      classify(response)
   except (UpstreamRejected, SchemaChanged):
      return
