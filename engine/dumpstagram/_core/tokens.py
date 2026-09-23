"""Re-bootstrap once when a failure looks like a token the upstream will not accept.

Extracted from ``_core/smoke.py`` when the first capability arrived, because two call sites
deciding independently when to spend a request on a fresh token is two places for the loop to
come back.

The judgement it carries is unchanged and still an inference. Stale per-page tokens are not a
measured failure mode: what was measured is that a request carrying no ``fb_dtsg`` comes back
as the HTML application shell under HTTP 200, and the shortest observed token lifetime is a
lower bound of 16 minutes with no upper bound. INFERENCE, not FACT: a token that has expired
behaves like one that was never sent.

So the missing-token error and the application-shell rejection both re-bootstrap, once, and
only when the failing attempt used a token it had not just fetched. Without that second
condition a freshly fetched token that is refused costs two more live requests per attempt for
nothing, and without the once a locked account is retried forever.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from dumpstagram._core.pacer import run_with_retries
from dumpstagram._core.requesting import PacedSender
from dumpstagram.errors import AuthenticationFailed, UpstreamRejected
from dumpstagram.session import Session

__all__ = [
   "HTML_APP_SHELL",
   "is_a_stale_token_failure",
   "with_one_token_recovery",
   "with_token_recovery",
]

HTML_APP_SHELL = "html_app_shell"
"""The classifier's code for the shell, which is what an unusable ``fb_dtsg`` produces."""


def is_a_stale_token_failure(failure: Exception) -> bool:
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


async def with_token_recovery[T](
   attempt: Callable[[], Awaitable[T]],
   *,
   sender: PacedSender,
   session: Session,
   deadline: float | None = None,
) -> T:
   """Run ``attempt`` under the retry policy, clearing the token and running it once more.

   ``attempt`` is responsible for bootstrapping when the session carries no ``fb_dtsg``, which
   is what makes clearing the field here enough to force a fresh one.
   """

   token_before_the_attempt = session.fb_dtsg

   try:
      return await run_with_retries(attempt, pacer=sender.pacer, deadline=deadline)
   except (AuthenticationFailed, UpstreamRejected) as failure:
      if not is_a_stale_token_failure(failure):
         raise

      used_a_token_it_had_not_just_fetched = (
         token_before_the_attempt is not None and session.fb_dtsg == token_before_the_attempt
      )
      if not used_a_token_it_had_not_just_fetched:
         raise

      session.fb_dtsg = None

      return await run_with_retries(attempt, pacer=sender.pacer, deadline=deadline)


async def with_one_token_recovery[T](
   attempt: Callable[[], Awaitable[T]],
   *,
   session: Session,
) -> T:
   """The judgement of :func:`with_token_recovery` around one attempt, with no retry policy.

   The listener's poll already runs under ``run_with_retries`` in the pump, so a poll built on
   :func:`with_token_recovery` would retry inside a retry and multiply what one failure costs.
   This sends ``attempt`` once, and once more only after clearing a token that looks stale.
   """

   token_before_the_attempt = session.fb_dtsg

   try:
      return await attempt()
   except (AuthenticationFailed, UpstreamRejected) as failure:
      if not is_a_stale_token_failure(failure):
         raise

      kept_a_token_it_had_not_just_fetched = (
         token_before_the_attempt is not None and session.fb_dtsg == token_before_the_attempt
      )
      if not kept_a_token_it_had_not_just_fetched:
         raise

      session.fb_dtsg = None

      return await attempt()
