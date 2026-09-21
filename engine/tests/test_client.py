"""Gates for the two public facades and the lifecycle they share.

Nothing here spends a request, because neither surface carries a capability yet. What it does
carry is ownership, and every defect in ownership is silent: a client that never releases the
loop thread leaves a thread running for the lifetime of the process, a close that fails
half-way leaks the same thread on top of the failure it was already reporting, and a double
close releases a reference the client no longer holds.

The loop-thread assertions read `threading.enumerate` rather than the refcount, for the reason
`test_loop_thread.py` records: `release` clears the count and the handle together, so a gate
reading either stays green when the thread is never stopped.
"""

from __future__ import annotations

import threading

import pytest

from dumpstagram._core.loop_thread import THREAD_NAME, _LoopThread
from dumpstagram.aio import AsyncClient
from dumpstagram.client import SyncClient
from dumpstagram.errors import AuthenticationFailed
from dumpstagram.session import Session

SESSION_ID = "71234567%3AabcdefGHIJKL%3A17"


def a_session() -> Session:
   return Session(sessionid=SESSION_ID, ds_user_id="71234567", csrftoken="tokentokentoken")


def loop_threads_running() -> int:
   return len([thread for thread in threading.enumerate() if thread.name == THREAD_NAME])


def loop_thread_holders() -> int:
   """How many clients currently hold the shared thread.

   Read alongside the thread count rather than instead of it. The count is cleared by
   `release` whether or not the thread actually stopped, and the thread is shared, so a leaked
   reference is invisible to `threading.enumerate` while any other client is alive. Each
   number is blind to a defect the other one sees.
   """

   shared = _LoopThread._shared

   return 0 if shared is None else shared.references


def pool_of(client: SyncClient | AsyncClient) -> object:
   implementation = client._impl if isinstance(client, SyncClient) else client

   return implementation._sender._sender._client


def test_the_caller_keeps_their_session() -> None:
   session = a_session()

   with SyncClient(session) as client:
      assert client.session is session


def test_a_session_without_cookie_material_is_refused_before_a_pool_exists() -> None:
   with pytest.raises(AuthenticationFailed):
      Session(sessionid="", ds_user_id="71234567", csrftoken="tokentokentoken")


def test_closing_stops_the_shared_loop_thread() -> None:
   before = loop_threads_running()
   client = SyncClient(a_session())

   assert loop_threads_running() == before + 1

   client.close()

   assert loop_threads_running() == before


def test_one_thread_serves_two_clients() -> None:
   before = loop_threads_running()
   first = SyncClient(a_session())
   second = SyncClient(a_session())

   try:
      assert loop_threads_running() == before + 1
   finally:
      first.close()
      second.close()

   assert loop_threads_running() == before


def test_closing_twice_is_a_no_op() -> None:
   before = loop_threads_running()
   client = SyncClient(a_session())

   client.close()
   client.close()

   assert client.closed
   assert loop_threads_running() == before
   assert loop_thread_holders() == 0


def test_a_failed_construction_releases_the_thread(monkeypatch: pytest.MonkeyPatch) -> None:
   """The window between acquiring the thread and owning a usable client.

   A construction that raises here and does not release leaks a thread on every attempt, and
   the caller has no object to close.
   """

   before = loop_threads_running()
   holders = loop_thread_holders()

   def refuse(**keywords: object) -> None:
      raise RuntimeError("the pool refused to open")

   monkeypatch.setattr("dumpstagram.aio.HttpxTransport", refuse)

   with pytest.raises(RuntimeError):
      SyncClient(a_session())

   assert loop_threads_running() == before
   assert loop_thread_holders() == holders


def test_the_context_manager_closes_the_pool() -> None:
   with SyncClient(a_session()) as client:
      pool = pool_of(client)

      assert not pool.is_closed  # type: ignore[attr-defined]

   assert pool.is_closed  # type: ignore[attr-defined]
   assert client.closed


def test_closing_releases_the_thread_even_when_the_pool_close_fails(
   monkeypatch: pytest.MonkeyPatch,
) -> None:
   before = loop_threads_running()
   client = SyncClient(a_session())

   async def refuse() -> None:
      raise RuntimeError("the pool refused to close")

   monkeypatch.setattr(client._impl, "aclose", refuse)

   with pytest.raises(RuntimeError):
      client.close()

   assert loop_threads_running() == before


def test_the_user_agent_defaults_to_the_measured_string() -> None:
   from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT

   with SyncClient(a_session()) as client:
      assert client.user_agent == DEFAULT_USER_AGENT

   with SyncClient(a_session(), user_agent="probe/1.0") as client:
      assert client.user_agent == "probe/1.0"


@pytest.mark.asyncio
async def test_the_async_surface_closes_its_own_pool() -> None:
   async with AsyncClient(a_session()) as client:
      pool = pool_of(client)

      assert not pool.is_closed  # type: ignore[attr-defined]

   assert pool.is_closed  # type: ignore[attr-defined]
   assert client.closed


@pytest.mark.asyncio
async def test_the_async_surface_holds_no_loop_thread() -> None:
   before = loop_threads_running()
   holders = loop_thread_holders()

   async with AsyncClient(a_session()):
      assert loop_threads_running() == before
      assert loop_thread_holders() == holders


@pytest.mark.asyncio
async def test_closing_the_async_surface_twice_is_a_no_op() -> None:
   client = AsyncClient(a_session())

   await client.aclose()
   await client.aclose()

   assert client.closed


def test_a_missing_session_file_raises_before_the_thread_is_acquired(tmp_path) -> None:  # type: ignore[no-untyped-def]
   before = loop_threads_running()
   holders = loop_thread_holders()

   with pytest.raises(OSError):
      SyncClient.from_session_file(tmp_path / "absent.json")

   assert loop_threads_running() == before
   assert loop_thread_holders() == holders
