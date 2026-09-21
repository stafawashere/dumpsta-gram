"""Gates on the paced request path.

The pacer's own suite proves the pacer spaces correctly when it is used. This one proves it
is used, which is a different claim and the only one that matters at the point requests leave
the process. The defect it catches is a bypass: any code path that reaches a raw sender
instead of the paced one produces departures that are individually correct and collectively
unpaced.
"""

from __future__ import annotations

import asyncio

import pytest

from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import Request, Response, Sender


class FakeClock:
   """A monotonic clock that only advances when something sleeps on it."""

   def __init__(self) -> None:
      self.now = 0.0

   def __call__(self) -> float:
      return self.now

   async def sleep(self, seconds: float) -> None:
      self.now += seconds

      await asyncio.sleep(0)


class CountingTransport:
   """Records the clock reading at every departure, and nothing else."""

   def __init__(self, clock: FakeClock) -> None:
      self.clock = clock
      self.departures: list[float] = []
      self.closed = False

   async def send(self, request: Request) -> Response:
      self.departures.append(self.clock.now)

      return Response(
         status_code=200,
         headers={"content-type": "application/json"},
         content=b"{}",
         final_url=request.url,
      )

   async def aclose(self) -> None:
      self.closed = True


class SenderWithoutClose:
   def __init__(self) -> None:
      self.sent = 0

   async def send(self, request: Request) -> Response:
      self.sent += 1

      return Response(status_code=200, headers={}, content=b"{}", final_url=request.url)


def a_request(url: str = "https://example.invalid/page") -> Request:
   return Request(method="GET", url=url)


def make_paced(clock: FakeClock, transport: CountingTransport) -> PacedSender:
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)

   return PacedSender(transport, pacer)


def test_the_paced_sender_is_a_sender() -> None:
   """Catches a wrapper that cannot stand in for the thing it wraps.

   The substitution is what removes the bypass. If code above has to unwrap this to send,
   the unpaced sender is back in reach.
   """
   clock = FakeClock()
   transport = CountingTransport(clock)

   assert isinstance(make_paced(clock, transport), Sender)


@pytest.mark.asyncio
async def test_every_outbound_request_is_spaced_at_the_transport() -> None:
   """Catches a bypass, measured where requests actually leave rather than at the pacer.

   The floor is written out rather than read off the policy, so turning the default down
   cannot also turn this assertion down.
   """
   clock = FakeClock()
   transport = CountingTransport(clock)
   paced = make_paced(clock, transport)

   for _ in range(4):
      await paced.send(a_request())

   gaps = [
      later - earlier
      for earlier, later in zip(transport.departures[:-1], transport.departures[1:], strict=True)
   ]

   assert len(transport.departures) == 4
   assert gaps == [2.5, 2.5, 2.5]


@pytest.mark.asyncio
async def test_concurrent_callers_cannot_depart_together() -> None:
   """Catches the interleaving being reintroduced outside the pacer.

   Holding the slot around the decision but releasing it before the send puts two departures
   at the same instant while every individual computation still looks correct.
   """
   clock = FakeClock()
   transport = CountingTransport(clock)
   paced = make_paced(clock, transport)

   await asyncio.gather(*(paced.send(a_request()) for _ in range(3)))

   assert sorted(transport.departures) == [0.0, 2.5, 5.0]


@pytest.mark.asyncio
async def test_closing_the_paced_sender_closes_the_transport() -> None:
   """Catches a wrapper that silently leaks the connection pool it was handed."""
   clock = FakeClock()
   transport = CountingTransport(clock)

   async with make_paced(clock, transport) as paced:
      await paced.send(a_request())

   assert transport.closed is True


@pytest.mark.asyncio
async def test_a_sender_without_aclose_is_not_an_error() -> None:
   """Catches the wrapper demanding more of the Sender protocol than the protocol states."""
   clock = FakeClock()
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)
   bare = SenderWithoutClose()

   async with PacedSender(bare, pacer) as paced:
      await paced.send(a_request())

   assert bare.sent == 1
