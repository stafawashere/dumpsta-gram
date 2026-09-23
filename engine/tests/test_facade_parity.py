"""The mechanism that keeps the two public surfaces in step.

Chosen 2026-09-22 over generating the facade and over review alone. Nothing here names a
capability. Every gate is parametrised over what `AsyncClient` actually carries, so a coroutine
added to it without a `SyncClient` counterpart fails this file the moment it exists, and so does
a counterpart that takes different parameters, forwards them wrongly, runs somewhere other than
the loop thread, or labels its seam note with another method's name.

The capability list is read off the class, and the positive control reads it a second way, off
the committed snapshot, so a discovery that quietly finds nothing cannot leave every
parametrised gate green by running none of them.

Nothing here spends a request. The capability on the async side is replaced by a spy for the
duration of each test, which is the boundary this file is about.
"""

from __future__ import annotations

import inspect
import threading
from pathlib import Path
from typing import Any, get_type_hints

import pytest

from dumpstagram._core.loop_thread import THREAD_NAME, seam_note
from dumpstagram.aio import AsyncClient
from dumpstagram.client import SyncClient
from dumpstagram.session import Session

SNAPSHOT = Path(__file__).resolve().parent / "public_surface.txt"

BLOCKING_NAME_FOR = {"aclose": "close"}
"""The one public name that differs between the surfaces. Dunders are not public names here."""

ASYNC_NAME_FOR = {blocking: awaitable for awaitable, blocking in BLOCKING_NAME_FOR.items()}

SCOPING_METHODS = {"with_behavior"}
"""Methods that build another client rather than read anything. Each surface returns its own
type from them, so they cannot share a capability's return type and have a gate of their own."""


def public_names(cls: type) -> set[str]:
   return {name for name in vars(cls) if not name.startswith("_")}


def capabilities_on_the_async_surface() -> list[str]:
   found: list[str] = []

   for name, member in vars(AsyncClient).items():
      is_public = not name.startswith("_")
      is_awaitable = inspect.iscoroutinefunction(member)
      is_lifecycle = name in BLOCKING_NAME_FOR
      is_capability = is_public and is_awaitable and not is_lifecycle

      if is_capability:
         found.append(name)

   return sorted(found)


CAPABILITIES = capabilities_on_the_async_surface()


def capabilities_in_the_snapshot() -> set[str]:
   prefix = "def dumpstagram.aio.AsyncClient."
   names: set[str] = set()

   for line in SNAPSHOT.read_text(encoding="utf-8").splitlines():
      if not line.startswith(prefix):
         continue

      name = line[len(prefix) :].split("(", 1)[0]
      is_lifecycle = name.startswith("_") or name in BLOCKING_NAME_FOR
      is_scoping = name in SCOPING_METHODS

      if not is_lifecycle and not is_scoping:
         names.add(name)

   return names


def a_session() -> Session:
   return Session(sessionid="71234567%3AabcdefGHIJKL%3A17", ds_user_id="71234567", csrftoken="t")


def parameters_of(function: Any) -> list[tuple[str, Any, Any, Any]]:
   signature = inspect.signature(function, eval_str=True)

   return [
      (parameter.name, parameter.kind, parameter.default, parameter.annotation)
      for parameter in signature.parameters.values()
   ]


def distinct_arguments_for(function: Any) -> tuple[list[object], dict[str, object]]:
   """One fresh object per parameter, so a swapped or dropped argument cannot compare equal."""

   positional: list[object] = []
   keyword: dict[str, object] = {}

   for parameter in list(inspect.signature(function).parameters.values())[1:]:
      argument = object()

      if parameter.kind is inspect.Parameter.KEYWORD_ONLY:
         keyword[parameter.name] = argument
      else:
         positional.append(argument)

   return positional, keyword


def test_discovery_finds_every_capability_the_snapshot_lists() -> None:
   """Catches a discovery rule that finds nothing, which would leave every gate below vacuous."""

   assert CAPABILITIES
   assert set(CAPABILITIES) == capabilities_in_the_snapshot()


def test_both_surfaces_expose_the_same_public_names() -> None:
   """Catches a capability, property or constructor added to one surface and not the other."""

   async_names = {BLOCKING_NAME_FOR.get(name, name) for name in public_names(AsyncClient)}

   assert async_names == public_names(SyncClient)


@pytest.mark.parametrize("name", sorted(public_names(SyncClient)))
def test_a_shared_name_is_the_same_kind_of_member_on_both_surfaces(name: str) -> None:
   """Catches a property on one surface that became a method, or a classmethod, on the other."""

   async_name = ASYNC_NAME_FOR.get(name, name)

   blocking_member = vars(SyncClient)[name]
   async_member = vars(AsyncClient)[async_name]

   assert type(blocking_member) is type(async_member)


@pytest.mark.parametrize("name", CAPABILITIES)
def test_a_capability_takes_the_same_parameters_and_returns_the_same_type(name: str) -> None:
   """Catches a parameter added, renamed, reordered or re-defaulted on one surface only."""

   blocking = getattr(SyncClient, name)
   awaitable = getattr(AsyncClient, name)

   assert parameters_of(blocking) == parameters_of(awaitable)
   assert get_type_hints(blocking)["return"] == get_type_hints(awaitable)["return"]


def test_the_constructors_take_the_same_parameters() -> None:
   """Catches a construction option only one surface accepts."""

   assert parameters_of(SyncClient.__init__) == parameters_of(AsyncClient.__init__)
   assert parameters_of(SyncClient.from_session_file) == parameters_of(
      AsyncClient.from_session_file
   )


@pytest.mark.parametrize("name", sorted(SCOPING_METHODS))
def test_a_scoping_method_takes_the_same_parameters_and_returns_its_own_surface(
   name: str,
) -> None:
   """Catches a scoping method missing from one surface, taking different parameters there, or
   handing a blocking caller the async client."""

   blocking = getattr(SyncClient, name)
   awaitable = getattr(AsyncClient, name)

   assert parameters_of(blocking) == parameters_of(awaitable)
   assert get_type_hints(blocking)["return"] is SyncClient
   assert get_type_hints(awaitable)["return"] is AsyncClient

   with SyncClient(a_session()) as client:
      scoped = getattr(client, name)(client.behavior)

      try:
         assert type(scoped) is SyncClient
      finally:
         scoped.close()


@pytest.mark.parametrize("name", CAPABILITIES)
def test_a_blocking_capability_is_not_a_coroutine(name: str) -> None:
   """Catches a facade method declared async, which hands a sync caller an unawaited coroutine."""

   assert not inspect.iscoroutinefunction(getattr(SyncClient, name))


@pytest.mark.parametrize("name", CAPABILITIES)
def test_a_blocking_capability_forwards_every_argument_on_the_loop_thread(
   name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
   """Catches an argument dropped, swapped or defaulted on the way down, and a facade that
   runs the coroutine anywhere but the shared loop thread."""

   original_signature = inspect.signature(getattr(AsyncClient, name))
   result = object()
   calls: list[tuple[dict[str, Any], str]] = []

   async def spy(self: AsyncClient, *args: object, **kwargs: object) -> object:
      bound = original_signature.bind(self, *args, **kwargs)
      bound.apply_defaults()
      received = dict(bound.arguments)
      del received["self"]
      calls.append((received, threading.current_thread().name))

      return result

   monkeypatch.setattr(AsyncClient, name, spy)

   positional, keyword = distinct_arguments_for(getattr(SyncClient, name))
   expected = original_signature.bind(None, *positional, **keyword).arguments
   del expected["self"]

   with SyncClient(a_session()) as client:
      returned = getattr(client, name)(*positional, **keyword)

   assert len(calls) == 1

   received, thread_name = calls[0]

   assert received.keys() == expected.keys()

   for parameter_name, argument in expected.items():
      assert received[parameter_name] is argument, parameter_name

   assert thread_name == THREAD_NAME
   assert returned is result


@pytest.mark.parametrize("name", CAPABILITIES)
def test_a_blocking_capability_raises_the_async_exception_under_its_own_name(
   name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
   """Catches a wrapped exception, and a seam note copied from another method's facade."""

   raised = LookupError("raised by the async side")

   async def spy(self: AsyncClient, *args: object, **kwargs: object) -> object:
      raise raised

   monkeypatch.setattr(AsyncClient, name, spy)

   positional, keyword = distinct_arguments_for(getattr(SyncClient, name))

   with SyncClient(a_session()) as client:
      with pytest.raises(LookupError) as caught:
         getattr(client, name)(*positional, **keyword)

   assert caught.value is raised
   assert seam_note(f"SyncClient.{name}") in getattr(caught.value, "__notes__", [])
