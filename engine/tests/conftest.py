"""Environment guard.

The engine has been broken three times by the same fault, and it is silent every time: the
sync agent on `~/Documents` sets the macOS `UF_HIDDEN` flag on the `.pth` files inside an
in-tree `.venv`, CPython's `site` skips a hidden `.pth`, and the editable install drops off
`sys.path`. Collection then fails with `ModuleNotFoundError: No module named 'dumpstagram'`,
which reads like a packaging mistake rather than a filesystem one.

This guard names the real cause before the first test runs. It checks the interpreter that is
actually executing, so it fires on a fallback environment as loudly as on a flagged one.

Network guard.

No gate may open a connection to anything but loopback. On 2026-09-23 a Step 23 gate built a
real `AsyncClient` by accident, and its poller sent a bootstrap GET to www.instagram.com with a
synthetic session in the middle of `uv run pytest`. The guard sits at the socket layer rather
than in `httpx`, so it holds for `HttpxTransport` in both its kinds, for anything that talks to
`httpcore` or `socket` directly, and for the loop thread as much as for the test's own thread.
A name lookup for anything but localhost is refused as well, because offline the lookup is
where such a request dies, and it would die there quietly.

Refusing is not enough on its own. The engine turns a connection error into `TransportFailure`
and the listener survives that, so a refusal can be swallowed and the test still pass. Every
refusal is therefore recorded, and a test that leaves one behind fails at teardown. A gate that
means to be refused asks for `refused_connections` and clears what it asserted on.
"""

import ipaddress
import os
import socket
import stat
import sys
import sysconfig

import pytest

SYNC_MANAGED_PREFIXES = ("/Users/mahfujm/Documents",)
EXPECTED_ENVIRONMENT = "/Users/mahfujm/venvs/dumpstagram-engine"


def hidden_pth_files(site_packages):
   if not os.path.isdir(site_packages):
      return []

   flagged = []

   for name in sorted(os.listdir(site_packages)):
      if not name.endswith(".pth"):
         continue

      path = os.path.join(site_packages, name)
      flags = getattr(os.stat(path), "st_flags", 0)

      if flags & stat.UF_HIDDEN:
         flagged.append(name)

   return flagged


def pytest_configure(config):
   prefix = os.path.realpath(sys.prefix)
   site_packages = sysconfig.get_paths()["purelib"]

   for managed in SYNC_MANAGED_PREFIXES:
      if prefix.startswith(os.path.realpath(managed)):
         raise pytest.UsageError(
            f"environment {prefix} is inside the sync-managed tree {managed}. "
            f"Export UV_PROJECT_ENVIRONMENT={EXPECTED_ENVIRONMENT} and rerun. "
            "See engine/docs/engineering/project-profile.md"
         )

   flagged = hidden_pth_files(site_packages)

   if flagged:
      names = ", ".join(flagged)

      raise pytest.UsageError(
         "these .pth files carry the macOS hidden flag, so site skipped them and the editable "
         f"install is not on sys.path: {names}. Clear with `chflags nohidden` in "
         f"{site_packages}, and move the environment out of the sync-managed tree so it does "
         "not come back."
      )


LOOPBACK_NAMES = frozenset({"localhost"})


class RealNetworkRefused(ConnectionRefusedError):
   """A test reached for a host that is not loopback."""


def is_loopback_host(host):
   if host is None:
      return True

   if isinstance(host, bytes):
      host = host.decode("ascii", errors="replace")

   if host.lower() in LOOPBACK_NAMES:
      return True

   try:
      return ipaddress.ip_address(host.split("%")[0]).is_loopback
   except ValueError:
      return False


def is_address_literal(host):
   if not isinstance(host, str):
      return False

   try:
      ipaddress.ip_address(host.split("%")[0])
   except ValueError:
      return False

   return True


class NetworkGuard:
   def __init__(self):
      self.refused = []
      self.real_connect = socket.socket.connect
      self.real_connect_ex = socket.socket.connect_ex
      self.real_getaddrinfo = socket.getaddrinfo

   def refuse(self, what):
      self.refused.append(what)

      raise RealNetworkRefused(f"the test suite refused a real network connection: {what}")

   def check_connect(self, sock, address):
      is_local_socket = sock.family == getattr(socket, "AF_UNIX", None)

      if is_local_socket:
         return

      host = address[0]

      if not is_loopback_host(host):
         self.refuse(f"connect to {host}:{address[1]}")

   def check_lookup(self, host, port):
      may_resolve = is_loopback_host(host) or is_address_literal(host)

      if not may_resolve:
         self.refuse(f"name lookup of {host}:{port}")

   def install(self, monkeypatch):
      guard = self

      def guarded_connect(sock, address):
         guard.check_connect(sock, address)

         return guard.real_connect(sock, address)

      def guarded_connect_ex(sock, address):
         guard.check_connect(sock, address)

         return guard.real_connect_ex(sock, address)

      def guarded_getaddrinfo(host, port, *args, **kwargs):
         guard.check_lookup(host, port)

         return guard.real_getaddrinfo(host, port, *args, **kwargs)

      monkeypatch.setattr(socket.socket, "connect", guarded_connect)
      monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
      monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)


@pytest.fixture(scope="session", autouse=True)
def network_guard():
   guard = NetworkGuard()

   with pytest.MonkeyPatch.context() as monkeypatch:
      guard.install(monkeypatch)

      yield guard


@pytest.fixture(autouse=True)
def no_real_network(network_guard):
   network_guard.refused.clear()

   yield

   left_behind = list(network_guard.refused)
   network_guard.refused.clear()

   if left_behind:
      refusals = "; ".join(left_behind)

      pytest.fail(
         f"this test tried to reach the network and the guard refused it: {refusals}",
         pytrace=False,
      )


@pytest.fixture
def refused_connections(network_guard):
   return network_guard.refused
