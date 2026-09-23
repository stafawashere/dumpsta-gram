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

from types import TracebackType

from dumpstagram._core.pacer import Pacer, PacingPolicy
from dumpstagram._private.transport import Request, Response, Sender

__all__ = ["PacedSender"]


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
