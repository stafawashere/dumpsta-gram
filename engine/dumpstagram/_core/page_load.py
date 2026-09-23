"""The companion requests a browser's page load sends after its document.

A page load is one action. Its document and the page's own queries come first, then the
companions this module sends: groups that each depart together, one group after another, in
the order the adapter lists them. None of their answers is read. They are sent because the page
sends them, which is the whole of ADR-0013's argument for them.

A companion's answer is still screened for what concerns the whole account. A checkpoint or a
throttle is raised, because either one arriving on a request nobody reads is still the
account being stopped. Anything else a companion answers is left alone, so a companion the
upstream stops answering does not cost the caller what they asked for.

Sending a group together is the second place ``_core`` is concurrent, beside the profile
page's six queries, and for the same reason: the page sends each group within a few
milliseconds.
"""

from __future__ import annotations

from collections.abc import Sequence

from dumpstagram._core.requesting import ActionSender
from dumpstagram._private.transport import Request, Response
from dumpstagram._private.web.classify import classify
from dumpstagram.errors import SchemaChanged, UpstreamRejected

__all__ = ["raise_only_what_concerns_the_account", "send_companions"]


async def send_companions(action: ActionSender, groups: Sequence[Sequence[Request]]) -> None:
   """Send each group together, one group after another, inside the caller's action."""

   for group in groups:
      responses = await action.send_together(group)

      for response in responses:
         raise_only_what_concerns_the_account(response)


def raise_only_what_concerns_the_account(response: Response) -> None:
   try:
      classify(response)
   except (UpstreamRejected, SchemaChanged):
      return
