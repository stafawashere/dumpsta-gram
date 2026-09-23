"""Per-account request pacing and the account-wide backoff policy.

One pacer per account, owned by the client instance. Every outbound request passes it,
including the realtime listener's polling, and there is no bypass. The reasoning and the
measured numbers behind the defaults live in
``engine/docs/rate-limiting-and-safety.md``.

Two properties are structural rather than conventional.

The decision to send and the send itself happen under one lock. They are two steps, and two
tasks interleaving between them produces two departures at the same instant, which defeats
the pacing entirely while every individual computation still looks correct.

The retry helper catches :data:`~dumpstagram.errors.RETRYABLE` and nothing else, so
:class:`~dumpstagram.errors.CheckpointRequired` cannot reach the backoff path. Retrying
around a challenge escalates a soft block into a locked account.

The clock, the sleep, and the jitter source are all injected, because a pacer whose spacing
can only be observed by waiting several real seconds per assertion does not get tested.

Sharing contract. A pacer is sequentially reusable and task safe. It is not thread safe and
it is bound to the loop its lock was first awaited on, which is the engine's loop thread.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from dumpstagram.errors import RETRYABLE, RateLimited

__all__ = [
   "DEFAULT_BACKOFF",
   "DEFAULT_PACING",
   "BackoffPolicy",
   "Pacer",
   "PacingPolicy",
   "backoff_delay",
   "run_with_retries",
]


@dataclass(frozen=True)
class PacingPolicy:
   """Spacing between two departures for one account.

   The defaults are the prior project's measured pair: a 2500 ms floor plus 350 ms of mean
   jitter, which produced 0.351 requests per second across roughly 650 live requests with no
   throttling observed. The real web client was measured at 4.46 requests per second, so this
   runs an order of magnitude below traffic the account has already sustained.
   """

   floor_seconds: float = 2.5
   mean_jitter_seconds: float = 0.35


@dataclass(frozen=True)
class BackoffPolicy:
   """Account-wide backoff, inherited from the prior project and never observed to fire.

   ASSUMPTION rather than FACT. No 429 and no 5xx was seen across the whole measured session,
   so these parameters are a defensible starting posture and nothing stronger.
   """

   initial_seconds: float = 4.0
   ceiling_seconds: float = 120.0
   multiplier: float = 2.0
   max_attempts: int = 5


DEFAULT_PACING = PacingPolicy()
DEFAULT_BACKOFF = BackoffPolicy()


def backoff_delay(
   attempt: int,
   policy: BackoffPolicy = DEFAULT_BACKOFF,
   *,
   retry_after: float | None = None,
) -> float:
   """Seconds to wait before ``attempt + 1``, where ``attempt`` counts from one.

   An upstream ``retry-after`` wins when it is larger than the computed delay, and is not
   clipped by the ceiling. The ceiling bounds what this library invents, not what the
   upstream explicitly asks for.
   """

   exponential = policy.initial_seconds * (policy.multiplier ** (attempt - 1))
   computed = min(exponential, policy.ceiling_seconds)

   if retry_after is None:
      return computed

   upstream_asks_for_longer = retry_after > computed
   if upstream_asks_for_longer:
      return retry_after

   return computed


class Pacer:
   """Spaces departures for one account and holds the whole account during backoff.

   The hold is account-wide on purpose. When the upstream says slow down it is talking about
   the account, so a per-request wait would let queued work sail past the signal.
   """

   def __init__(
      self,
      *,
      pacing: PacingPolicy = DEFAULT_PACING,
      backoff: BackoffPolicy = DEFAULT_BACKOFF,
      clock: Callable[[], float] = time.monotonic,
      sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
      jitter: Callable[[], float] = random.random,
   ) -> None:
      self.pacing = pacing
      self.backoff = backoff

      self._clock = clock
      self._sleep = sleep
      self._jitter = jitter

      self._lock = asyncio.Lock()
      self._last_departure_at = float("-inf")
      self._held_until = float("-inf")

   def now(self) -> float:
      """The pacer's own monotonic instant, which is what a deadline is measured against."""

      return self._clock()

   @asynccontextmanager
   async def slot(self, pacing: PacingPolicy | None = None) -> AsyncIterator[None]:
      """Wait until this account may send again, then hold the account for the send.

      The lock spans the wait and the caller's body together. Releasing it between the two
      is the interleaving this class exists to prevent.

      ``pacing`` is the spacing this departure asks for, measured from the account's previous
      departure whoever sent it. Two clients sharing one pacer with different behavior still
      share one account's history, which is why the gap is the departing request's choice
      and the record is the pacer's.
      """

      async with self._lock:
         await self._wait_until_allowed(pacing or self.pacing)
         yield

   def hold(self, seconds: float) -> None:
      """Stop the whole account for ``seconds``, without waiting here.

      Recording and waiting are separate because they are separate guarantees. The record is
      what makes a hold account-wide: every other task inherits it at its next slot, whether
      or not the task that saw the upstream signal is still around to sleep through it.
      """

      if seconds <= 0:
         return

      resumes_at = self._clock() + seconds
      self._held_until = max(self._held_until, resumes_at)

   async def hold_for(self, seconds: float) -> None:
      """Record an account-wide hold and wait it out here as well.

      The retry path uses this rather than :meth:`hold` alone, so that an operation which
      never reaches a slot still pays the backoff instead of spinning through its budget.
      """

      if seconds <= 0:
         return

      self.hold(seconds)

      await self._sleep(seconds)

   async def wait_out_hold(self) -> None:
      """Wait while the account is held, without taking a slot or recording a departure.

      For traffic a page sends on its own between the user's actions, which a throttle still
      stops and which the next action's gap is not measured from.
      """

      while True:
         remaining = self._held_until - self._clock()
         if remaining <= 0:
            return

         await self._sleep(remaining)

   async def sleep(self, seconds: float) -> None:
      """Sleep on this pacer's clock, so a fake clock covers whoever waits through it."""

      await self._sleep(seconds)

   async def _wait_until_allowed(self, pacing: PacingPolicy) -> None:
      gap = self._gap_seconds(pacing)

      while True:
         spaced_at = self._last_departure_at + gap
         remaining = max(spaced_at, self._held_until) - self._clock()
         if remaining <= 0:
            break

         await self._sleep(remaining)

      self._last_departure_at = self._clock()

   def _gap_seconds(self, pacing: PacingPolicy) -> float:
      spread = 2.0 * pacing.mean_jitter_seconds

      return pacing.floor_seconds + self._jitter() * spread


async def run_with_retries[T](
   operation: Callable[[], Awaitable[T]],
   *,
   pacer: Pacer,
   deadline: float | None = None,
) -> T:
   """Run ``operation``, retrying only the error types listed in ``RETRYABLE``.

   ``deadline`` is a monotonic instant on the pacer's clock. A backoff that would cross it
   is not taken, and the last failure is raised instead of being buried under a timeout of
   this library's own invention.
   """

   attempt = 1

   while True:
      try:
         return await operation()
      except RETRYABLE as failure:
         is_final_attempt = attempt >= pacer.backoff.max_attempts
         if is_final_attempt:
            raise

         retry_after = failure.retry_after if isinstance(failure, RateLimited) else None
         delay = backoff_delay(attempt, pacer.backoff, retry_after=retry_after)

         if deadline is not None:
            crosses_the_deadline = pacer.now() + delay > deadline
            if crosses_the_deadline:
               raise

         await pacer.hold_for(delay)
         attempt += 1
