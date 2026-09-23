"""One post, read by its shortcode, asynchronously.

Both public surfaces call this, and the like capability's docstrings name it as the read that
confirms a like or reconciles one whose outcome is unknown. Nothing here knows the upstream
speaks GraphQL: the adapter in `_private/web/` builds the request and maps the answer.

A browser reads a post inside a post page load, beside the page's document and its companion
queries. That burst has not been recorded, because ruling 23 allowed no browser load when this
read was verified, so the engine sends the post query alone, a recorded departure in
`engine/docs/web-request-contract.md`.
"""

from __future__ import annotations

from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse import parse_post_detail
from dumpstagram._private.web.requests import build_post_request
from dumpstagram.models import PostDetail
from dumpstagram.session import Session

__all__ = ["read_post"]


async def read_post(
   sender: PacedSender,
   session: Session,
   code: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> PostDetail:
   """Read the post whose shortcode is ``code`` and return it typed.

   One live request when the session already carries usable tokens, two when it has to
   bootstrap first.
   """

   async def attempt() -> PostDetail:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_post_request(session, code, user_agent=user_agent)
      response = await sender.send(request)

      return parse_post_detail(classify(response))

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)
