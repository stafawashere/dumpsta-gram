"""Gates for the network guard in ``conftest.py``.

The guard exists because a gate once built a real client whose poller reached
www.instagram.com in the middle of a run. These gates prove the guard holds for both kinds of
engine transport, for a bare name lookup, and for a refusal the code under test swallows.

Every address they reach for is one nothing answers, 192.0.2.1 from the documentation range
and a name under ``.invalid``, so a mutation that disables the guard sends nothing to Instagram.
"""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest

from dumpstagram._private.transport import HttpxTransport, Request, Timeouts
from dumpstagram.errors import TransportFailure

UNROUTABLE_HOST = "192.0.2.1"
UNRESOLVABLE_HOST = "network-guard.invalid"
SHORT_TIMEOUTS = Timeouts(connect=0.5, read=0.5, write=0.5, pool=0.5)
CONFTEST = Path(__file__).with_name("conftest.py")

A_TEST_THAT_SWALLOWS_THE_REFUSAL = f"""
import socket


def test_a_connection_whose_failure_is_ignored():
   try:
      socket.create_connection(("{UNROUTABLE_HOST}", 443), timeout=0.5)
   except OSError:
      pass
"""


def engine_transport(kind: str) -> HttpxTransport:
   if kind == "cookieless":
      return HttpxTransport(allowed_host=UNROUTABLE_HOST, cookieless=True, timeouts=SHORT_TIMEOUTS)

   return HttpxTransport(
      cookies={"sessionid": "synthetic"},
      allowed_host=UNROUTABLE_HOST,
      timeouts=SHORT_TIMEOUTS,
   )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["with_cookies", "cookieless"])
async def test_both_engine_transports_are_refused_a_real_connection(
   kind: str, refused_connections: list[str]
) -> None:
   """Catches a guard that the engine's own transport, in either of its kinds, gets past."""

   transport = engine_transport(kind)

   try:
      with pytest.raises(TransportFailure):
         await transport.send(Request(method="GET", url=f"https://{UNROUTABLE_HOST}/"))
   finally:
      await transport.aclose()

   assert refused_connections == [f"connect to {UNROUTABLE_HOST}:443"]

   refused_connections.clear()


def test_a_name_lookup_is_refused(refused_connections: list[str]) -> None:
   """Catches a guard that lets a lookup through, which offline is where a request dies
   quietly."""

   with pytest.raises(ConnectionRefusedError, match="refused a real network connection"):
      socket.getaddrinfo(UNRESOLVABLE_HOST, 443)

   assert refused_connections == [f"name lookup of {UNRESOLVABLE_HOST}:443"]

   refused_connections.clear()


def test_a_refusal_the_test_swallows_still_fails_it(tmp_path: Path) -> None:
   """Catches a guard that only raises, which the listener's retry path absorbs."""

   (tmp_path / "conftest.py").write_text(CONFTEST.read_text(encoding="utf-8"), encoding="utf-8")
   (tmp_path / "test_swallowed.py").write_text(A_TEST_THAT_SWALLOWS_THE_REFUSAL, encoding="utf-8")

   inner = subprocess.run(
      [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path)],
      cwd=tmp_path,
      capture_output=True,
      text=True,
   )

   assert "1 passed, 1 error" in inner.stdout
   assert f"connect to {UNROUTABLE_HOST}:443" in inner.stdout
   assert inner.returncode != 0
