"""Gates for per-account pacing and the account-wide backoff.

Each one names the defect it catches. The defects this layer can produce are a floor that
does not hold, two tasks deciding to send at the same instant, a backoff that ignores what
the upstream asked for, and a challenge reaching the retry path.

Every assertion runs on an injected clock. A pacer tested against the wall clock costs
2.5 seconds per gap, which is how a pacing suite ends up with the floor turned down in it.
"""

from __future__ import annotations

import asyncio

import pytest

from dumpstagram._core.pacer import (
   DEFAULT_BACKOFF,
   BackoffPolicy,
   Pacer,
   PacingPolicy,
   backoff_delay,
   run_with_retries,
)
from dumpstagram.errors import CheckpointRequired, RateLimited, TransportFailure


class FakeClock:
   """A monotonic clock that only advances when something sleeps on it."""

   def __init__(self) -> None:
      self.now = 0.0

   def __call__(self) -> float:
      return self.now

   async def sleep(self, seconds: float) -> None:
      self.now += seconds

      await asyncio.sleep(0)


def make_pacer(clock: FakeClock, *, jitter: float = 0.0, **kwargs) -> Pacer:
   return Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: jitter, **kwargs)


@pytest.mark.asyncio
async def test_departures_are_spaced_by_at_least_the_floor() -> None:
   """Catches a floor that does not hold, which is the whole point of the pacer.

   The expected floor is written out rather than read back off the policy, so that turning
   the default down cannot also turn this assertion down.
   """

   clock = FakeClock()
   pacer = make_pacer(clock)
   departures: list[float] = []

   for _ in range(4):
      async with pacer.slot():
         departures.append(clock.now)

   gaps = [later - earlier for earlier, later in zip(departures[:-1], departures[1:], strict=True)]

   assert len(gaps) == 3
   assert all(gap >= 2.5 for gap in gaps), gaps


@pytest.mark.asyncio
async def test_jitter_widens_the_gap_above_the_floor() -> None:
   """Catches a jitter source that is drawn and then discarded."""

   clock = FakeClock()
   pacer = make_pacer(clock, jitter=1.0)
   departures: list[float] = []

   for _ in range(2):
      async with pacer.slot():
         departures.append(clock.now)

   gap = departures[1] - departures[0]
   expected = pacer.pacing.floor_seconds + 2.0 * pacer.pacing.mean_jitter_seconds

   assert gap == pytest.approx(expected)


@pytest.mark.asyncio
async def test_concurrent_tasks_cannot_interleave_the_decision_and_the_send() -> None:
   """Catches the lock being dropped between deciding to send and sending.

   Spacing alone does not catch it. The pacer rechecks its own earliest-departure instant
   after every wait, so unlocked tasks still come out spaced. What the lock uniquely buys is
   that no second task enters a slot while the first is still using the one it was granted,
   and a slot body that awaits is exactly where a real send would be.
   """

   clock = FakeClock()
   pacer = make_pacer(clock)
   occupants = 0
   highest_occupancy = 0

   async def take_a_slot() -> None:
      nonlocal occupants, highest_occupancy

      async with pacer.slot():
         occupants += 1
         highest_occupancy = max(highest_occupancy, occupants)

         await asyncio.sleep(0)

         occupants -= 1

   await asyncio.gather(*(take_a_slot() for _ in range(3)))

   assert highest_occupancy == 1


def test_backoff_sequence_matches_the_inherited_parameters() -> None:
   """Catches a drift in the backoff shape away from the documented parameters."""

   sequence = [backoff_delay(attempt) for attempt in range(1, 7)]

   assert sequence == [4.0, 8.0, 16.0, 32.0, 64.0, 120.0]


def test_backoff_honours_a_larger_retry_after() -> None:
   """Catches an upstream retry-after being computed and then ignored."""

   assert backoff_delay(1, retry_after=30.0) == 30.0


def test_backoff_ignores_a_smaller_retry_after() -> None:
   """Positive control for the previous gate, so it cannot pass by always returning the hint."""

   assert backoff_delay(3, retry_after=1.0) == 16.0


def test_backoff_does_not_clip_a_retry_after_to_the_ceiling() -> None:
   """The ceiling bounds what this library invents, not what the upstream asks for."""

   assert backoff_delay(1, retry_after=300.0) == 300.0


@pytest.mark.asyncio
async def test_a_checkpoint_is_never_retried() -> None:
   """Catches a challenge reaching the backoff path, which escalates it into a lock-out."""

   clock = FakeClock()
   pacer = make_pacer(clock)
   attempts = 0

   async def operation() -> None:
      nonlocal attempts
      attempts += 1

      raise CheckpointRequired("challenge", required_action="confirm")

   with pytest.raises(CheckpointRequired):
      await run_with_retries(operation, pacer=pacer)

   assert attempts == 1
   assert clock.now == 0.0


@pytest.mark.asyncio
async def test_a_retryable_failure_is_retried_up_to_the_attempt_budget() -> None:
   """Positive control for the gate above, proving the retry path is reachable at all."""

   clock = FakeClock()
   pacer = make_pacer(clock)
   attempts = 0

   async def operation() -> None:
      nonlocal attempts
      attempts += 1

      raise TransportFailure("connection reset")

   with pytest.raises(TransportFailure):
      await run_with_retries(operation, pacer=pacer)

   assert attempts == DEFAULT_BACKOFF.max_attempts
   assert clock.now == pytest.approx(4.0 + 8.0 + 16.0 + 32.0)


@pytest.mark.asyncio
async def test_a_backoff_that_would_cross_the_deadline_is_not_taken() -> None:
   """Catches a retry budget that outlives the deadline the caller actually asked for."""

   clock = FakeClock()
   pacer = make_pacer(clock)
   attempts = 0

   async def operation() -> None:
      nonlocal attempts
      attempts += 1

      raise RateLimited("slow down", retry_after=60.0)

   with pytest.raises(RateLimited):
      await run_with_retries(operation, pacer=pacer, deadline=10.0)

   assert attempts == 1
   assert clock.now == 0.0


@pytest.mark.asyncio
async def test_a_recorded_hold_delays_the_next_slot_on_the_account() -> None:
   """Catches a backoff that is slept through rather than recorded on the account.

   The hold is recorded by a task that does no waiting of its own, so the only thing that
   can delay the next departure is the record itself. If the hold lives in the holding
   task's stack, every other task sails straight through the signal the upstream just sent.
   """

   clock = FakeClock()
   pacer = make_pacer(clock)
   pacer.hold(20.0)

   async with pacer.slot():
      departed_at = clock.now

   assert departed_at >= 20.0


@pytest.mark.asyncio
async def test_the_retry_path_waits_out_the_backoff_it_recorded() -> None:
   """Catches a retry loop that records a hold and then spins through its budget.

   An operation that never reaches a slot has nothing to enforce the record for it.
   """

   clock = FakeClock()
   pacer = make_pacer(clock, backoff=BackoffPolicy(initial_seconds=20.0, max_attempts=2))

   async def operation() -> None:
      raise TransportFailure("connection reset")

   with pytest.raises(TransportFailure):
      await run_with_retries(operation, pacer=pacer)

   assert clock.now == pytest.approx(20.0)


@pytest.mark.asyncio
async def test_pacing_policy_defaults_match_the_measured_anchor() -> None:
   """Catches a default quietly widened away from the rate the account has sustained."""

   policy = PacingPolicy()
   mean_gap = policy.floor_seconds + policy.mean_jitter_seconds

   assert policy.floor_seconds == 2.5
   assert policy.mean_jitter_seconds == 0.35
   assert 1.0 / mean_gap == pytest.approx(0.351, abs=0.001)
