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

Writes pass the same pacer and take the same slot, with three more rules on top: a wider gap
measured from the account's previous write, a budget of writes per rolling hour, and a stop
that refuses every later write once one was rejected in a way nothing recorded explains. All
three are account state, so a client derived with a different behavior inherits what the
account already spent and already saw.

The budget and the stop are judged against the account's write record in a
:class:`~dumpstagram._core.ledger.WriteLedger`. By default that is a memory ledger, which lives
as long as the pacer. A client built from a session file swaps in the ledger file beside it,
and then every process on the account spends one budget and honours one stop. The record is
read afresh under the file's lock for every judgement, once before the write waits for its
turn and again, recording the departure, just before it leaves.

The clock, the sleep, and the jitter source are all injected, because a pacer whose spacing
can only be observed by waiting several real seconds per assertion does not get tested.

Sharing contract. A pacer is sequentially reusable and task safe. It is not thread safe and
it is bound to the loop its lock was first awaited on, which is the engine's loop thread.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial

from dumpstagram._core.ledger import LedgerUnreadable, MemoryLedger, WriteLedger, WriteRecord
from dumpstagram.errors import RETRYABLE, RateLimited, UpstreamRejected

__all__ = [
   "DEFAULT_BACKOFF",
   "DEFAULT_PACING",
   "DEFAULT_WRITES",
   "WRITES_STOPPED",
   "WRITE_BUDGET_WINDOW_SECONDS",
   "BackoffPolicy",
   "Pacer",
   "PacingPolicy",
   "WritePolicy",
   "backoff_delay",
   "run_with_retries",
]

WRITES_STOPPED = "writes_stopped"
"""The code of the rejection a stopped account's writes get, which is this library's own and
never one the upstream sent."""

WRITE_BUDGET_WINDOW_SECONDS = 3600.0

_logger = logging.getLogger("dumpstagram")


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


@dataclass(frozen=True)
class WritePolicy:
   """The rules a write departs under, beyond the spacing every request keeps.

   Every number is a placeholder chosen to be cautious and derived from nothing, because no
   write rate has been measured on this project. ``budget_per_hour`` of None means no budget.
   """

   spacing: PacingPolicy = PacingPolicy(floor_seconds=30.0, mean_jitter_seconds=5.0)
   budget_per_hour: int | None = 30
   stop_after_unrecognised_rejection: bool = True


DEFAULT_PACING = PacingPolicy()
DEFAULT_BACKOFF = BackoffPolicy()
DEFAULT_WRITES = WritePolicy()


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
      ledger: WriteLedger | None = None,
   ) -> None:
      self.pacing = pacing
      self.backoff = backoff

      self._clock = clock
      self._sleep = sleep
      self._jitter = jitter

      self.ledger: WriteLedger = ledger or MemoryLedger(clock)
      """Where the account's write budget and write stop are kept. Replaced only before the
      first write, by the client that knows the session file."""

      self._lock = asyncio.Lock()
      self._last_departure_at = float("-inf")
      self._held_until = float("-inf")

      self._last_write_at = float("-inf")
      self._departed_write_tokens: set[str] = set()
      self._writes_stopped = False
      self._writes_built = 0

   def next_write_number(self) -> int:
      """One more than the number of writes built on this account so far, starting at 1.

      A browser tab numbers its mutations the same way, and a write sends the number as its
      ``client_mutation_id``. It counts writes built rather than departed, because the number
      goes into the request before the pacer decides whether the request may leave.
      """

      self._writes_built += 1

      return self._writes_built

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

   @asynccontextmanager
   async def write_slot(
      self,
      token: str,
      writes: WritePolicy,
      pacing: PacingPolicy | None = None,
   ) -> AsyncIterator[None]:
      """Wait until this account may write, then hold the account for the write's one send.

      Every refusal happens before any wait and before the token is recorded, so a refused
      write has not departed and says so by raising. A token already recorded is a defect in
      the caller rather than an upstream condition, and is raised as one.

      The account's record is judged twice. The first judgement refuses before the wait. The
      second, after it, refuses what another process spent or stopped meanwhile, and records
      the departure in the same locked update, so two processes cannot both take the last
      slot of a budget.
      """

      async with self._lock:
         self._refuse_a_second_departure(token)
         await self._judge_write(writes, record_departure=False)

         write_spaced_at = self._last_write_at + self._gap_seconds(writes.spacing)
         departs_at = await self._wait_for_turn(pacing or self.pacing, not_before=write_spaced_at)

         await self._judge_write(writes, record_departure=True)

         self._last_departure_at = departs_at
         self._last_write_at = departs_at
         self._departed_write_tokens.add(token)

         yield

   def write_departed(self, token: str) -> bool:
      """Whether a write with ``token`` has left, which a refused write never has."""

      return token in self._departed_write_tokens

   def stop_writes(self) -> None:
      """Refuse every later write on this account, for as long as this pacer lives.

      Recorded whatever the policy of the write that saw the rejection, and enforced for each
      write by that write's own policy.
      """

      self._writes_stopped = True

   async def share_write_stop(self) -> None:
      """Write this pacer's stop into the account's ledger, so every process sees it.

      Nothing to share when this pacer has not stopped. An unreadable ledger already refuses
      every write in every process, so it is left as it is. A ledger that cannot be written
      leaves the stop in this process only, and says so in the log.
      """

      if not self._writes_stopped:
         return

      try:
         await self.ledger.update(_mark_stopped)
      except LedgerUnreadable:
         return
      except OSError:
         _logger.warning("the write stop could not be kept in the pacing ledger file")

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

   def _refuse_a_second_departure(self, token: str) -> None:
      if token in self._departed_write_tokens:
         raise RuntimeError("this write request has already departed once and cannot again")

   async def _judge_write(self, writes: WritePolicy, *, record_departure: bool) -> None:
      judgement = partial(self._judge_record, writes, record_departure)

      try:
         await self.ledger.update(judgement)
      except LedgerUnreadable as unreadable:
         raise UpstreamRejected(
            f"{unreadable}, so writes are refused until a person inspects and removes it",
            code=WRITES_STOPPED,
         ) from unreadable

   def _judge_record(
      self,
      writes: WritePolicy,
      record_departure: bool,
      record: WriteRecord,
      now: float,
   ) -> None:
      record.forget_before(now - WRITE_BUDGET_WINDOW_SECONDS)

      self._refuse_when_writes_are_stopped(writes, record)
      self._refuse_past_the_budget(writes, record, now)

      if record_departure:
         record.departures.append(now)

   def _refuse_when_writes_are_stopped(self, writes: WritePolicy, record: WriteRecord) -> None:
      account_is_stopped = self._writes_stopped or record.writes_stopped
      is_stopped = account_is_stopped and writes.stop_after_unrecognised_rejection

      if is_stopped:
         raise UpstreamRejected(
            "writes are stopped on this account after a rejection nothing recorded explains",
            code=WRITES_STOPPED,
         )

   def _refuse_past_the_budget(self, writes: WritePolicy, record: WriteRecord, now: float) -> None:
      if writes.budget_per_hour is None:
         return

      budget_is_spent = len(record.departures) >= writes.budget_per_hour
      if not budget_is_spent:
         return

      if not record.departures:
         raise RateLimited("this account's write budget is zero, so no write departs")

      frees_at = min(record.departures) + WRITE_BUDGET_WINDOW_SECONDS

      raise RateLimited(
         "this account's write budget for the hour is spent",
         retry_after=frees_at - now,
      )

   async def _wait_until_allowed(
      self,
      pacing: PacingPolicy,
      *,
      not_before: float = float("-inf"),
   ) -> None:
      self._last_departure_at = await self._wait_for_turn(pacing, not_before=not_before)

   async def _wait_for_turn(
      self,
      pacing: PacingPolicy,
      *,
      not_before: float = float("-inf"),
   ) -> float:
      gap = self._gap_seconds(pacing)

      while True:
         spaced_at = self._last_departure_at + gap
         remaining = max(spaced_at, self._held_until, not_before) - self._clock()
         if remaining <= 0:
            break

         await self._sleep(remaining)

      return self._clock()

   def _gap_seconds(self, pacing: PacingPolicy) -> float:
      spread = 2.0 * pacing.mean_jitter_seconds

      return pacing.floor_seconds + self._jitter() * spread


def _mark_stopped(record: WriteRecord, now: float) -> None:
   if record.writes_stopped:
      return

   record.writes_stopped = True
   record.stopped_at = now


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
