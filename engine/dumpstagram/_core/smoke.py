"""One read through the whole stack, used to prove the stack is wired and nothing else.

This is not a capability and it is not public. Build plan Step 8 calls for an internal
end-to-end read so that the pacer, the adapter, the transport and the classifier are exercised
together before Phase 2 builds anything on top of them, and the roadmap is explicit that the
transport must not be proved by shipping a feature. So this returns the parsed structure the
classifier produced, untouched. Nothing here reads a GraphQL field, which is what keeps it a
wiring check rather than a second copy of the capability in `_core/direct.py`.

The probes under `probes/` still drive this rather than the capability, deliberately: their
measured runs are the evidence for the layers underneath, and a probe that goes through the
mapper would fail on an upstream field rename that the layers it is checking survived.

The re-bootstrap judgement it used to own now lives in `_core/tokens.py`, because the
capability needs the same one.
"""

from __future__ import annotations

from typing import Any

from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import HTML_APP_SHELL, with_token_recovery
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.requests.direct import build_thread_page_request
from dumpstagram.session import Session

__all__ = ["HTML_APP_SHELL", "read_one_thread_page"]


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

   return await with_token_recovery(attempt, sender=sender, session=session, deadline=deadline)
