"""The one path a write takes out of ``_core``.

A write is never retried, per ``engine/docs/engineering/05-io-concurrency-and-pacing.md`` and
ruling 13 in ``engine/docs/build-plan.md``. A timeout can arrive after the upstream has
committed the write, and a second send of a comment or a message is a duplicate other people
see. So :func:`send_write` sends once, and every way a retry would otherwise creep back in ends
in an error the caller sees instead:

- a connection failure while the write is in flight is an unknown outcome, never a network
  error the caller might answer by sending again
- the HTML application shell clears the page token so the next call bootstraps, and raises
- a throttle holds the whole account and raises, without sleeping and resending
- a rejection nothing recorded explains stops later writes on the account, if the policy says so

It takes no deadline, because a write abandoned at a deadline and started again is a retry.
Cancelling it in flight raises :class:`~dumpstagram.errors.OperationCancelled` at the facade,
and the outcome is then unknown too.

Nothing here knows the upstream speaks GraphQL. The request arrives built, the answer leaves
classified, and what a success looks like for each write is its capability's to decide.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from dumpstagram._core.pacer import backoff_delay
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import HTML_APP_SHELL
from dumpstagram._private.transport import WriteRequest
from dumpstagram._private.web.classify import classify
from dumpstagram.errors import OutcomeUnknown, RateLimited, TransportFailure, UpstreamRejected
from dumpstagram.session import Session

__all__ = ["send_write"]


async def send_write(
   sender: PacedSender,
   session: Session,
   write: WriteRequest,
   *,
   recognised_rejections: Collection[str] = (),
) -> Any:
   """Send ``write`` exactly once and return its classified answer.

   ``recognised_rejections`` are the rejection codes a verified finding explains for this
   write. The application shell is always recognised, because what it means is known: the page
   token was refused. Any other code stops later writes when the sender's write policy says to.

   A write the pacer refused, over the budget or after a stop, never departed, so it raises
   the refusal as it is and changes nothing on the account.
   """

   try:
      response = await sender.send_once(write)
      payload = classify(response)
   except TransportFailure as failure:
      raise OutcomeUnknown(
         "the connection failed while a write was in flight, so it may have applied",
         operation=write.operation,
      ) from failure
   except (RateLimited, UpstreamRejected) as failure:
      if sender.pacer.write_departed(write.token):
         _record_answer(sender, session, failure, recognised_rejections)

      raise

   return payload


def _record_answer(
   sender: PacedSender,
   session: Session,
   failure: RateLimited | UpstreamRejected,
   recognised_rejections: Collection[str],
) -> None:
   if isinstance(failure, RateLimited):
      delay = backoff_delay(1, sender.pacer.backoff, retry_after=failure.retry_after)
      sender.pacer.hold(delay)
      return

   if failure.code == HTML_APP_SHELL:
      session.fb_dtsg = None
      return

   is_recognised = failure.code in recognised_rejections
   if not is_recognised:
      sender.pacer.stop_writes()
