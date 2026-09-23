"""Gates for the behavior configuration and the scoped client built from it.

The defects this layer can produce are all silent. A client that drops its behavior sends at
the wrong spacing with nothing failing. A scoped client with a pacer of its own lets two
clients over one account depart together. A scoped client that closes the pool it borrowed
breaks the client that owns it. Nothing here spends a request.

Expected spacings are written out as literals rather than read off the presets, so a preset
changed by accident cannot carry its own assertion along with it.
"""

from __future__ import annotations

import asyncio

import pytest

from dumpstagram._core.loop_thread import _LoopThread
from dumpstagram._core.pacer import Pacer, PacingPolicy
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import Request, Response
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import EXPORT, FAST, PARITY, Behavior, Spacing
from dumpstagram.client import SyncClient
from dumpstagram.session import Session


class FakeClock:
   def __init__(self) -> None:
      self.now = 0.0

   def __call__(self) -> float:
      return self.now

   async def sleep(self, seconds: float) -> None:
      self.now += seconds

      await asyncio.sleep(0)


class RecordingTransport:
   def __init__(self, clock: FakeClock) -> None:
      self.clock = clock
      self.departures: list[float] = []
      self.closed = False

   async def send(self, request: Request) -> Response:
      self.departures.append(self.clock.now)

      return Response(status_code=200, headers={}, content=b"{}", final_url=request.url)

   async def aclose(self) -> None:
      self.closed = True


def a_session() -> Session:
   return Session(sessionid="71234567%3AabcdefGHIJKL%3A17", ds_user_id="71234567", csrftoken="t")


def a_request() -> Request:
   return Request(method="GET", url="https://example.invalid/page")


async def client_on_a_fake_account(
   behavior: Behavior,
) -> tuple[AsyncClient, RecordingTransport]:
   client = AsyncClient(a_session(), behavior=behavior)
   await client._sender.aclose()

   clock = FakeClock()
   transport = RecordingTransport(clock)
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)
   client._sender = PacedSender(transport, pacer, client._sender.pacing)

   return client, transport


def test_parity_spacing_is_the_measured_human_fit() -> None:
   """Catches the default drifting away from the numbers fitted to the owner's browsing."""

   assert PARITY.spacing == Spacing(floor_seconds=1.3, mean_jitter_seconds=2.0)
   assert Behavior() == PARITY


def test_the_export_preset_is_the_sustained_measured_rate() -> None:
   """Catches the export preset drifting from the 0.351 requests per second anchor."""

   mean_gap = EXPORT.spacing.floor_seconds + EXPORT.spacing.mean_jitter_seconds

   assert 1.0 / mean_gap == pytest.approx(0.351, abs=0.001)


def test_negative_spacing_is_refused() -> None:
   """Catches a sign error in a caller's configuration reaching the pacer unnoticed."""

   with pytest.raises(ValueError):
      Spacing(floor_seconds=-1.0, mean_jitter_seconds=0.0)


@pytest.mark.asyncio
async def test_the_departing_request_chooses_its_own_gap() -> None:
   """Catches a pacer that spaces by its own policy and ignores the one it was handed."""

   clock = FakeClock()
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)
   departures = []

   for policy in (PacingPolicy(4.0, 0.0), PacingPolicy(4.0, 0.0), PacingPolicy(0.0, 0.0)):
      async with pacer.slot(policy):
         departures.append(clock.now)

   assert departures == [0.0, 4.0, 4.0]


@pytest.mark.asyncio
async def test_a_client_spaces_by_its_behavior() -> None:
   """Catches a client that accepts a behavior and then paces by the old fixed default."""

   client, transport = await client_on_a_fake_account(PARITY)

   for _ in range(3):
      await client._sender.send(a_request())

   assert transport.departures == [0.0, 1.3, 2.6]


@pytest.mark.asyncio
async def test_a_scoped_client_shares_the_account_pacer() -> None:
   """Catches a scoped client built with a pacer of its own.

   Pacing is per account. Two pacers over one account let a request from each client leave
   at the same instant, which is exactly what the scoped client exists not to do.
   """

   client, transport = await client_on_a_fake_account(PARITY)
   scoped = client.with_behavior(EXPORT)

   await client._sender.send(a_request())
   await scoped._sender.send(a_request())
   await client._sender.send(a_request())

   assert transport.departures == [0.0, 2.5, 3.8]
   assert scoped.behavior == EXPORT
   assert client.behavior == PARITY


@pytest.mark.asyncio
async def test_closing_a_scoped_client_leaves_the_pool_open() -> None:
   """Catches a scoped client closing the pool it borrowed from its owner."""

   client, transport = await client_on_a_fake_account(PARITY)
   scoped = client.with_behavior(FAST)

   await scoped.aclose()

   assert scoped.closed
   assert not client.closed
   assert not transport.closed


@pytest.mark.asyncio
async def test_closing_the_owner_stops_its_scoped_clients() -> None:
   """Catches a scoped client still accepting calls after the pool behind it is gone."""

   client, transport = await client_on_a_fake_account(PARITY)
   scoped = client.with_behavior(FAST)

   await client.aclose()

   assert transport.closed
   assert scoped.closed

   with pytest.raises(RuntimeError):
      await scoped.feed()


def test_a_blocking_scoped_client_holds_and_releases_its_own_thread_reference() -> None:
   """Catches a blocking scoped client that leaks a loop thread reference, or drops one it
   never took and so stops the thread under its owner.
   """

   client = SyncClient(a_session())
   held_by_owner = _LoopThread._shared.references if _LoopThread._shared else 0

   scoped = client.with_behavior(FAST)
   held_with_scoped = _LoopThread._shared.references if _LoopThread._shared else 0

   scoped.close()
   held_after_scoped_close = _LoopThread._shared.references if _LoopThread._shared else 0

   assert held_with_scoped == held_by_owner + 1
   assert held_after_scoped_close == held_by_owner
   assert not client.closed
   assert scoped.behavior == FAST

   client.close()
