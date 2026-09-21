"""One read through the whole stack, used to prove the stack is wired and nothing else.

This is not a capability and it is not public. Build plan Step 8 calls for an internal
end-to-end read so that the pacer, the adapter, the transport and the classifier are exercised
together before Phase 2 builds anything on top of them, and the roadmap is explicit that the
transport must not be proved by shipping a feature. So this returns the parsed structure the
classifier produced, untouched. Nothing here reads a GraphQL field, and no typed model exists
for it to build.

The re-bootstrap path is the only judgement in the module. Stale per-page tokens are not a
measured failure mode: what was measured is that a request carrying no ``fb_dtsg`` comes back
as the HTML application shell under HTTP 200, and the shortest token lifetime anyone has
observed here is a lower bound of 16 minutes with no upper bound. INFERENCE, not FACT: a token
that has expired behaves like one that was never sent. So both the missing-token error and the
application-shell rejection re-bootstrap once, and only once. A second failure is raised,
because a loop that re-bootstraps forever spends a live request per attempt against an account
that is already refusing them.
"""

from __future__ import annotations

from typing import Any

from dumpstagram._core.pacer import run_with_retries
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.requests import build_thread_page_request
from dumpstagram.errors import AuthenticationFailed, UpstreamRejected
from dumpstagram.session import Session

__all__ = ["HTML_APP_SHELL", "read_one_thread_page"]

HTML_APP_SHELL = "html_app_shell"
"""The classifier's code for the shell, which is what an unusable ``fb_dtsg`` produces."""


def _is_a_stale_token_failure(failure: Exception) -> bool:
   """Whether re-bootstrapping is a plausible fix for this failure.

   :class:`~dumpstagram.errors.AuthenticationFailed` is raised by the request builder when the
   session carries no token at all, and by the token scraper when the bootstrap page carried
   none. :class:`~dumpstagram.errors.UpstreamRejected` with the shell code is what the upstream
   returns for a token it will not accept.
   """

   if isinstance(failure, AuthenticationFailed):
      return True

   if not isinstance(failure, UpstreamRejected):
      return False

   return failure.code == HTML_APP_SHELL


async def read_one_thread_page(
   sender: PacedSender,
   session: Session,
   thread_fbid: str,
   *,
   after: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
   deadline: float | None = None,
) -> Any:
   """Bootstrap if needed, then read one page of one thread, and return it parsed.

   Costs one live request when ``session`` already carries usable tokens, and two when it does
   not. ``deadline`` is a monotonic instant on the pacer's clock, and a backoff that would
   cross it is not taken.
   """

   async def attempt() -> Any:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_thread_page_request(session, thread_fbid, after=after, user_agent=user_agent)
      response = await sender.send(request)

      return classify(response)

   token_before_the_attempt = session.fb_dtsg

   try:
      return await run_with_retries(attempt, pacer=sender.pacer, deadline=deadline)
   except (AuthenticationFailed, UpstreamRejected) as failure:
      if not _is_a_stale_token_failure(failure):
         raise

      used_a_token_it_had_not_just_fetched = (
         token_before_the_attempt is not None and session.fb_dtsg == token_before_the_attempt
      )
      if not used_a_token_it_had_not_just_fetched:
         raise

      session.fb_dtsg = None

      return await run_with_retries(attempt, pacer=sender.pacer, deadline=deadline)
