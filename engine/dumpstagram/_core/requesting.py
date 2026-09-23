"""The one path an outbound request takes out of ``_core``.

Every request this library sends passes a :class:`~dumpstagram._core.pacer.Pacer`, including
the Phase 4 listener's polling, and there is no bypass. The pacer alone cannot guarantee that,
because a caller holding a :class:`~dumpstagram._private.transport.Sender` can simply not call
it. :class:`PacedSender` closes that hole by being a ``Sender`` itself: code above it receives
the paced object and has no unpaced one to reach for.

That is also what makes the end-to-end pacing gate possible. A counting transport behind a
:class:`PacedSender` measures spacing at the point requests actually leave, rather than
measuring the pacer working correctly in isolation while something routes around it.

Nothing here knows the upstream speaks GraphQL. The request is opaque, the response is
returned untouched, and interpreting it belongs to the surface adapter.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from types import TracebackType

from dumpstagram._core.pacer import Pacer, PacingPolicy
from dumpstagram._private.transport import Request, Response, Sender

__all__ = ["ActionSender", "PacedSender"]


class ActionSender:
   """Sends the requests of one user action inside the single slot the action was given.

   A browser page load is one action that sends a document and then several queries at once.
   Pacing each of those as its own action would space them by seconds where the page spaces
   them by milliseconds, so the action takes one slot and everything inside it departs as the
   page's own requests do. It exists only inside :meth:`PacedSender.action`.
   """

   def __init__(self, sender: Sender) -> None:
      self._sender = sender

   async def send(self, request: Request) -> Response:
      return await self._sender.send(request)

   async def send_together(self, requests: Sequence[Request]) -> list[Response]:
      """Send every request at once and return the responses in the order given.

      A failure cancels the requests still in flight, so an action never leaves a send running
      behind the error it raised.
      """

      async with asyncio.TaskGroup() as group:
         tasks = [group.create_task(self._sender.send(request)) for request in requests]

      return [task.result() for task in tasks]


class PacedSender:
   """A :class:`~dumpstagram._private.transport.Sender` that cannot depart early.

   Wraps one sender and one pacer for one account. The wrapped sender belongs to whoever
   constructed it, so :meth:`aclose` closes it only when it has an ``aclose`` of its own, and
   the ownership rule in ``engine/docs/engineering/04-errors-resources-logging.md`` decides
   which of the two that is.
   """

   def __init__(self, sender: Sender, pacer: Pacer, pacing: PacingPolicy | None = None) -> None:
      self._sender = sender
      self.pacer = pacer
      self.pacing = pacing

   def with_pacing(self, pacing: PacingPolicy) -> PacedSender:
      """Another paced sender over the same transport and the same account's pacer.

      Only the spacing differs. The transport still belongs to this sender's owner, so the
      caller of this method must not close the one it gets back.
      """

      return PacedSender(self._sender, self.pacer, pacing)

   async def send(self, request: Request) -> Response:
      """Wait until this account may send again, then send inside the same slot.

      The send is inside the slot rather than after it. Releasing the pacer between the
      decision and the departure is the interleaving the pacer's lock exists to prevent, and
      doing it here would defeat it from outside.
      """

      async with self.pacer.slot(self.pacing):
         return await self._sender.send(request)

   @asynccontextmanager
   async def action(self) -> AsyncIterator[ActionSender]:
      """Take one slot for a whole user action and send its requests inside it.

      The gap before the action is the ordinary one. Nothing else on this account departs
      until the action ends, because the pacer's lock is held for it, which is also what keeps
      another action from landing inside a page load.
      """

      async with self.pacer.slot(self.pacing):
         yield ActionSender(self._sender)

   async def aclose(self) -> None:
      closer = getattr(self._sender, "aclose", None)

      if closer is not None:
         await closer()

   async def __aenter__(self) -> PacedSender:
      return self

   async def __aexit__(
      self,
      exc_type: type[BaseException] | None,
      exc: BaseException | None,
      traceback: TracebackType | None,
   ) -> None:
      await self.aclose()
