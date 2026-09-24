"""The mechanism that keeps the two public surfaces in step.

Chosen 2026-09-22 over generating the facade and over review alone. Nothing here names a
capability. Every gate is parametrised over what `AsyncClient` actually carries, so a coroutine
added to it without a `SyncClient` counterpart fails this file the moment it exists, and so does
a counterpart that takes different parameters, forwards them wrongly, runs somewhere other than
the loop thread, or labels its seam note with another method's name.

The capability list is read off the class, and the positive control reads it a second way, off
the committed snapshot, so a discovery that quietly finds nothing cannot leave every
parametrised gate green by running none of them.

Since E1 item 4 the same gates walk the domain namespaces, ``client.direct`` and the rest, which
are discovered as the public properties whose type is a class in ``dumpstagram.namespaces`` and
controlled against the snapshot the same way. The one place a capability is named is
``FLAT_ALIASES``, the table of ruling W19, which is the oracle the alias gates hold the code to:
a flat method and its alias, each on a fresh client over a recording transport, must send the
same requests and end the same way.

Nothing here spends a request. The capability on the async side is replaced by a spy for the
duration of each test, which is the boundary this file is about, and the alias gates answer
every request from the recording transport.
"""

from __future__ import annotations

import inspect
import sys
import threading
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_args, get_origin, get_type_hints

import pytest

from dumpstagram._core.loop_thread import THREAD_NAME, seam_note
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.writes import direct as writes_direct
from dumpstagram._private.transport import Request, Response
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY
from dumpstagram.client import SyncClient
from dumpstagram.listener import EventListener
from dumpstagram.models import NoteAudience, Page, VideoRendition
from dumpstagram.session import Session
from tests.test_direct import FakeClock, a_bootstrapped_session

SNAPSHOT = Path(__file__).resolve().parent / "public_surface.txt"

BLOCKING_NAME_FOR = {"aclose": "close"}
"""The one public name that differs between the surfaces. Dunders are not public names here."""

ASYNC_NAME_FOR = {blocking: awaitable for awaitable, blocking in BLOCKING_NAME_FOR.items()}

SCOPING_METHODS = {"with_behavior"}
"""Methods that build another client rather than read anything. Each surface returns its own
type from them, so they cannot share a capability's return type and have a gate of their own."""

LISTENER_METHODS = {"events"}
"""Methods that start a listener rather than read once. The async one is an async generator, which
discovery by coroutine does not find, and the blocking one takes a handler the async one has no
use for, so they have the listener parity gate below instead of the capability gates."""


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
      is_listener = name in LISTENER_METHODS

      if not is_lifecycle and not is_scoping and not is_listener:
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


def listener_methods_in_the_snapshot() -> set[str]:
   names: set[str] = set()

   for line in SNAPSHOT.read_text(encoding="utf-8").splitlines():
      for prefix in ("def dumpstagram.aio.AsyncClient.", "def dumpstagram.client.SyncClient."):
         if not line.startswith(prefix):
            continue

         name = line[len(prefix) :].split("(", 1)[0]

         if name in LISTENER_METHODS:
            names.add(name)

   return names


def test_every_listener_method_is_in_the_snapshot_on_both_surfaces() -> None:
   """Catches the listener exclusion above hiding a name nothing checks, since each one it
   names has to exist on both surfaces as the contract records them."""

   assert LISTENER_METHODS
   assert listener_methods_in_the_snapshot() == LISTENER_METHODS


@pytest.mark.parametrize("name", sorted(LISTENER_METHODS))
def test_both_listener_methods_share_every_parameter_except_the_handler(name: str) -> None:
   """Catches a parameter added to, renamed on or re-defaulted on one listener method only, a
   blocking method that hands back an async iterator, and an async one that stopped being an
   async generator."""

   blocking = getattr(SyncClient, name)
   awaitable = getattr(AsyncClient, name)

   blocking_parameters = [
      parameter for parameter in parameters_of(blocking) if parameter[0] != "on_event"
   ]
   handler = [parameter for parameter in parameters_of(blocking) if parameter[0] == "on_event"]

   assert blocking_parameters == parameters_of(awaitable)
   assert len(handler) == 1
   assert handler[0][1] is inspect.Parameter.KEYWORD_ONLY
   assert handler[0][2] is None

   assert inspect.isasyncgenfunction(awaitable)
   assert not inspect.iscoroutinefunction(blocking)
   assert not inspect.isasyncgenfunction(blocking)
   assert get_type_hints(blocking)["return"] is EventListener


NAMESPACE_PACKAGE = "dumpstagram.namespaces"

FLAT_ALIASES = {
   "comment": "media.comment",
   "comments": "media.comments",
   "delete_comment": "media.delete_comment",
   "delete_note": "direct.delete_note",
   "feed": "feeds.home",
   "follow": "social.follow",
   "like": "media.like",
   "notes": "direct.notes",
   "post": "media.by_code",
   "profile": "profiles.by_username",
   "profile_by_id": "profiles.by_id",
   "send_message": "direct.send",
   "set_note": "direct.set_note",
   "thread_messages": "direct.messages",
   "unfollow": "social.unfollow",
   "unlike": "media.unlike",
   "unsend_message": "direct.unsend",
}
"""Every flat capability and the namespace method that answers for it, ruling W19. Written out
rather than read off the source, because it is the thing the alias gates below hold the code
to."""

ARGUMENT_FOR_PARAMETER: dict[str, object] = {
   "after": "a-cursor",
   "audience": NoteAudience.MUTUAL_FOLLOWS,
   "code": "Cxxxxxxxxxx",
   "comment_id": "17890123456789012",
   "message_id": "mid.$abcdefghijklmnop",
   "newer_than_message_id": "mid.$olderthanthatone",
   "note_id": "17901234567890123",
   "overwrite": True,
   "path": "never-written.mp4",
   "post_pk": "3456789012345678901",
   "rendition": VideoRendition(
      url="https://scontent-fixture-1.cdninstagram.com/v/fixture.mp4",
      width=720,
      height=1280,
      version_type=101,
   ),
   "text": "a text",
   "thread_fbid": "1234567890123456",
   "user_id": "71234567",
   "username": "someone",
}
"""One well-formed value per parameter name, each passing the checks a capability runs before it
sends, and a keyword default overridden so a dropped keyword changes what is sent."""


def namespaces_on(cls: type) -> dict[str, type]:
   """Every public property of a client whose annotated type is a namespace class."""

   found: dict[str, type] = {}

   for name, member in vars(cls).items():
      is_public_property = not name.startswith("_") and isinstance(member, property)

      if not is_public_property:
         continue

      returns = get_type_hints(member.fget).get("return")
      is_a_class = isinstance(returns, type)
      is_a_namespace = is_a_class and returns.__module__.startswith(f"{NAMESPACE_PACKAGE}.")

      if is_a_namespace:
         found[name] = returns

   return found


def namespace_methods(cls: type) -> set[str]:
   return {
      name
      for name, member in vars(cls).items()
      if not name.startswith("_") and inspect.isfunction(member)
   }


ASYNC_NAMESPACES = namespaces_on(AsyncClient)
SYNC_NAMESPACES = namespaces_on(SyncClient)

ITERATOR_PREFIX = "iter_"
"""The prefix of a namespace method that walks a paged read, E1 item 5. Those are held by the
iterator gates at the end of this file, and every other namespace method by the coroutine gates."""

ALL_NAMESPACE_METHODS = sorted(
   f"{namespace}.{method}"
   for namespace, cls in ASYNC_NAMESPACES.items()
   for method in namespace_methods(cls)
)

NAMESPACE_METHODS = [
   qualified
   for qualified in ALL_NAMESPACE_METHODS
   if not qualified.split(".")[1].startswith(ITERATOR_PREFIX)
]

ITERATOR_METHODS = [
   qualified
   for qualified in ALL_NAMESPACE_METHODS
   if qualified.split(".")[1].startswith(ITERATOR_PREFIX)
]


def namespace_methods_in_the_snapshot() -> set[str]:
   property_prefix = "property dumpstagram.aio.AsyncClient."
   method_prefix = f"def {NAMESPACE_PACKAGE}."
   lines = SNAPSHOT.read_text(encoding="utf-8").splitlines()
   namespace_of_class: dict[str, str] = {}
   found: set[str] = set()

   for line in lines:
      if line.startswith(property_prefix):
         name, _, returns = line[len(property_prefix) :].partition(" -> ")
         namespace_of_class[returns] = name

   for line in lines:
      if not line.startswith(method_prefix):
         continue

      class_name, method = line[len("def ") :].split("(", 1)[0].split(".")[-2:]
      is_public = not method.startswith("_")
      is_on_the_async_client = class_name in namespace_of_class

      if is_public and is_on_the_async_client:
         found.add(f"{namespace_of_class[class_name]}.{method}")

   return found


def split(qualified: str) -> tuple[str, str]:
   namespace, method = qualified.split(".")

   return namespace, method


def test_namespace_discovery_finds_every_namespace_method_the_snapshot_lists() -> None:
   """Catches a namespace discovery rule that finds nothing, which would leave every namespace
   gate below vacuous."""

   assert NAMESPACE_METHODS
   assert ITERATOR_METHODS
   assert set(ALL_NAMESPACE_METHODS) == namespace_methods_in_the_snapshot()
   assert set(NAMESPACE_METHODS) | set(ITERATOR_METHODS) == set(ALL_NAMESPACE_METHODS)


def test_both_surfaces_carry_the_same_namespaces_with_the_same_methods() -> None:
   """Catches a namespace, or a method on one, that exists on one surface only."""

   assert ASYNC_NAMESPACES.keys() == SYNC_NAMESPACES.keys()

   for namespace, async_class in ASYNC_NAMESPACES.items():
      sync_class = SYNC_NAMESPACES[namespace]

      assert sync_class is not async_class, namespace
      assert namespace_methods(sync_class) == namespace_methods(async_class), namespace


@pytest.mark.asyncio
async def test_each_surface_hands_out_its_own_namespaces() -> None:
   """Catches a blocking client handing its caller the async namespace it wraps, whose methods
   return coroutines a blocking caller never awaits."""

   async with AsyncClient(a_session()) as async_client:
      for namespace, async_class in ASYNC_NAMESPACES.items():
         assert type(getattr(async_client, namespace)) is async_class, namespace

   with SyncClient(a_session()) as blocking_client:
      for namespace, sync_class in SYNC_NAMESPACES.items():
         assert type(getattr(blocking_client, namespace)) is sync_class, namespace


@pytest.mark.parametrize("qualified", NAMESPACE_METHODS)
def test_a_namespace_method_takes_the_same_parameters_and_returns_the_same_type(
   qualified: str,
) -> None:
   """Catches a namespace method whose parameters or return type differ between surfaces, an
   async one that is not a coroutine, and a blocking one that is."""

   namespace, method = split(qualified)
   blocking = getattr(SYNC_NAMESPACES[namespace], method)
   awaitable = getattr(ASYNC_NAMESPACES[namespace], method)

   assert parameters_of(blocking) == parameters_of(awaitable)
   assert get_type_hints(blocking)["return"] == get_type_hints(awaitable)["return"]
   assert inspect.iscoroutinefunction(awaitable)
   assert not inspect.iscoroutinefunction(blocking)


@pytest.mark.parametrize("qualified", NAMESPACE_METHODS)
def test_a_blocking_namespace_method_forwards_every_argument_on_the_loop_thread(
   qualified: str, monkeypatch: pytest.MonkeyPatch
) -> None:
   """Catches an argument dropped, swapped or defaulted on the way down a blocking namespace
   method, and one that runs its coroutine anywhere but the shared loop thread."""

   namespace, method = split(qualified)
   async_class = ASYNC_NAMESPACES[namespace]
   original_signature = inspect.signature(getattr(async_class, method))
   result = object()
   calls: list[tuple[dict[str, Any], str]] = []

   async def spy(self: object, *args: object, **kwargs: object) -> object:
      bound = original_signature.bind(self, *args, **kwargs)
      bound.apply_defaults()
      received = dict(bound.arguments)
      del received["self"]
      calls.append((received, threading.current_thread().name))

      return result

   monkeypatch.setattr(async_class, method, spy)

   positional, keyword = distinct_arguments_for(getattr(SYNC_NAMESPACES[namespace], method))
   expected = original_signature.bind(None, *positional, **keyword).arguments
   del expected["self"]

   with SyncClient(a_session()) as client:
      returned = getattr(getattr(client, namespace), method)(*positional, **keyword)

   assert len(calls) == 1

   received, thread_name = calls[0]

   assert received.keys() == expected.keys()

   for parameter_name, argument in expected.items():
      assert received[parameter_name] is argument, parameter_name

   assert thread_name == THREAD_NAME
   assert returned is result


@pytest.mark.parametrize("qualified", NAMESPACE_METHODS)
def test_a_blocking_namespace_method_raises_the_async_exception_under_its_own_name(
   qualified: str, monkeypatch: pytest.MonkeyPatch
) -> None:
   """Catches a wrapped exception, and a seam note naming the flat twin or a neighbour rather
   than the namespace method the caller called."""

   namespace, method = split(qualified)
   raised = LookupError("raised by the async side")

   async def spy(self: object, *args: object, **kwargs: object) -> object:
      raise raised

   monkeypatch.setattr(ASYNC_NAMESPACES[namespace], method, spy)

   positional, keyword = distinct_arguments_for(getattr(SYNC_NAMESPACES[namespace], method))

   with SyncClient(a_session()) as client:
      with pytest.raises(LookupError) as caught:
         getattr(getattr(client, namespace), method)(*positional, **keyword)

   assert caught.value is raised
   assert seam_note(f"SyncClient.{namespace}.{method}") in getattr(caught.value, "__notes__", [])


def test_every_flat_capability_has_exactly_one_namespace_alias() -> None:
   """Catches a flat capability added with no namespace method answering for it, and an alias
   table naming a namespace method that does not exist."""

   assert set(FLAT_ALIASES) == set(CAPABILITIES)
   assert set(FLAT_ALIASES.values()) <= set(NAMESPACE_METHODS)
   assert len(set(FLAT_ALIASES.values())) == len(FLAT_ALIASES)


class RecordingTransport:
   """Records every request and answers each with the same body, which carries no data."""

   def __init__(self) -> None:
      self.sent: list[Request] = []

   async def send(self, request: Request) -> Response:
      self.sent.append(request)

      return Response(
         status_code=200,
         headers={"content-type": "application/json; charset=utf-8"},
         content=b"{}",
         final_url=request.url,
      )

   async def aclose(self) -> None:
      return None


def a_scripted_session() -> Session:
   session = a_bootstrapped_session()
   session.actor_id = "17841400000000000"

   return session


def paced_on_a_fake_clock(transport: RecordingTransport) -> PacedSender:
   clock = FakeClock()

   return PacedSender(transport, Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0))


def arguments_for(function: Any) -> tuple[list[object], dict[str, object]]:
   positional: list[object] = []
   keyword: dict[str, object] = {}

   for parameter in list(inspect.signature(function).parameters.values())[1:]:
      argument = ARGUMENT_FOR_PARAMETER[parameter.name]

      if parameter.kind is inspect.Parameter.KEYWORD_ONLY:
         keyword[parameter.name] = argument
      else:
         positional.append(argument)

   return positional, keyword


Outcome = tuple[str, str]


def outcome_of(call: Any) -> Outcome:
   try:
      returned = call()
   except Exception as error:
      return (type(error).__qualname__, str(error))

   return ("returned", repr(returned))


async def async_answer(pick: Any, function: Any) -> tuple[list[Request], Outcome]:
   transport = RecordingTransport()
   client = AsyncClient(a_scripted_session(), behavior=SCRIPTED_BEHAVIOR)
   await client._sender.aclose()
   client._sender = paced_on_a_fake_clock(transport)
   positional, keyword = arguments_for(function)

   try:
      try:
         returned = await pick(client)(*positional, **keyword)
         outcome: Outcome = ("returned", repr(returned))
      except Exception as error:
         outcome = (type(error).__qualname__, str(error))
   finally:
      await client.aclose()

   return transport.sent, outcome


def blocking_answer(pick: Any, function: Any) -> tuple[list[Request], Outcome]:
   transport = RecordingTransport()
   positional, keyword = arguments_for(function)

   with SyncClient(a_scripted_session(), behavior=SCRIPTED_BEHAVIOR) as client:
      client._loop.run(client._impl._sender.aclose(), operation="the scripted sender swap")
      client._impl._sender = paced_on_a_fake_clock(transport)

      outcome = outcome_of(lambda: pick(client)(*positional, **keyword))

   return transport.sent, outcome


SCRIPTED_BEHAVIOR = replace(PARITY, cookie_sync=False)
"""The cookie sync tail would leave through the transport the client was built with, so it is
off here. Nothing else departs from the default behavior."""


@pytest.fixture
def fixed_send_identity(monkeypatch: pytest.MonkeyPatch) -> None:
   """A text send draws a fresh threading id from the clock and a random number on every call,
   the one request that differs between two identical calls. Both are pinned here."""

   monkeypatch.setattr(writes_direct, "time", SimpleNamespace(time=lambda: 1758412345.0))
   monkeypatch.setattr(writes_direct, "secrets", SimpleNamespace(randbits=lambda bits: 12345))


@pytest.mark.asyncio
@pytest.mark.parametrize("flat", sorted(FLAT_ALIASES))
async def test_a_flat_method_and_its_alias_send_the_same_requests_and_answer_alike_async(
   flat: str, fixed_send_identity: None
) -> None:
   """Catches an alias delegating to another capability's core function, and either of the pair
   dropping, swapping or defaulting an argument, on the awaitable surface."""

   namespace, method = split(FLAT_ALIASES[flat])
   flat_function = getattr(AsyncClient, flat)

   flat_sent, flat_outcome = await async_answer(lambda client: getattr(client, flat), flat_function)
   alias_sent, alias_outcome = await async_answer(
      lambda client: getattr(getattr(client, namespace), method), flat_function
   )

   assert flat_sent
   assert alias_sent == flat_sent
   assert alias_outcome == flat_outcome


@pytest.mark.parametrize("flat", sorted(FLAT_ALIASES))
def test_a_flat_method_and_its_alias_send_the_same_requests_and_answer_alike_blocking(
   flat: str, fixed_send_identity: None
) -> None:
   """The same gate on the blocking surface, whose flat method and alias reach the async one by
   different routes."""

   namespace, method = split(FLAT_ALIASES[flat])
   flat_function = getattr(SyncClient, flat)

   flat_sent, flat_outcome = blocking_answer(lambda client: getattr(client, flat), flat_function)
   alias_sent, alias_outcome = blocking_answer(
      lambda client: getattr(getattr(client, namespace), method), flat_function
   )

   assert flat_sent
   assert alias_sent == flat_sent
   assert alias_outcome == flat_outcome


CORE_FUNCTION_FOR_ALIAS = {
   "direct.delete_note": "dumpstagram._core.writes.notes.delete_note",
   "direct.messages": "dumpstagram._core.direct.read_thread_messages",
   "direct.notes": "dumpstagram._core.notes.read_notes",
   "direct.send": "dumpstagram._core.writes.direct.send_message",
   "direct.set_note": "dumpstagram._core.writes.notes.set_note",
   "direct.unsend": "dumpstagram._core.writes.direct.unsend_message",
   "feeds.home": "dumpstagram._core.feed.read_feed_page",
   "media.by_code": "dumpstagram._core.posts.read_post",
   "media.comment": "dumpstagram._core.writes.comments.create_comment",
   "media.comments": "dumpstagram._core.comments.read_comment_page",
   "media.delete_comment": "dumpstagram._core.writes.comments.delete_comment",
   "media.download": "dumpstagram._core.downloads.download_rendition",
   "media.like": "dumpstagram._core.writes.likes.like_post",
   "media.unlike": "dumpstagram._core.writes.likes.unlike_post",
   "profiles.by_id": "dumpstagram._core.profiles.read_profile_by_id",
   "profiles.by_username": "dumpstagram._core.profiles.read_profile",
   "social.follow": "dumpstagram._core.writes.follows.follow_user",
   "social.unfollow": "dumpstagram._core.writes.follows.unfollow_user",
}
"""The core capability each namespace method delegates to. The flat and alias gates above cannot
see an alias reaching the wrong one, since a flat method answers through its alias, so this
table is the independent half."""


class ReachedTheCore(Exception):
   pass


def test_every_namespace_method_names_the_core_capability_it_reaches() -> None:
   """Catches a namespace method added without saying which core capability answers for it,
   which would leave it outside the gate below."""

   assert set(CORE_FUNCTION_FOR_ALIAS) == set(NAMESPACE_METHODS)


@pytest.mark.asyncio
@pytest.mark.parametrize("qualified", sorted(CORE_FUNCTION_FOR_ALIAS))
async def test_a_namespace_method_reaches_the_core_capability_the_table_names(
   qualified: str, monkeypatch: pytest.MonkeyPatch
) -> None:
   """Catches an alias delegating to another capability's core function, such as an unlike
   that likes, which every other gate in this file would pass."""

   namespace, method = split(qualified)
   namespace_module = sys.modules[ASYNC_NAMESPACES[namespace].__module__]
   reached: list[str] = []

   def spy_for(qualified_core_name: str) -> Any:
      def spy(*args: object, **kwargs: object) -> object:
         reached.append(qualified_core_name)

         raise ReachedTheCore(qualified_core_name)

      return spy

   for name, member in list(vars(namespace_module).items()):
      is_a_core_function = inspect.isfunction(member) and member.__module__.startswith(
         "dumpstagram._core."
      )

      if is_a_core_function:
         monkeypatch.setattr(
            namespace_module, name, spy_for(f"{member.__module__}.{member.__name__}")
         )

   awaitable = getattr(ASYNC_NAMESPACES[namespace], method)
   positional, keyword = arguments_for(awaitable)

   async with AsyncClient(a_session()) as client:
      with pytest.raises(ReachedTheCore):
         await getattr(getattr(client, namespace), method)(*positional, **keyword)

   assert reached == [CORE_FUNCTION_FOR_ALIAS[qualified]]


PAGE_METHOD_FOR_ITERATOR = {
   "direct.iter_messages": "direct.messages",
   "feeds.iter_home": "feeds.home",
   "media.iter_comments": "media.comments",
}
"""Every iterator and the page read it walks, E1 item 5 and ruling W23. Written out rather than
read off the source, because it is what the iterator gates hold the code to."""


def a_scripted_walk() -> list[Page[object]]:
   """Two pages with an empty one between them, so a walk that forwards the wrong cursor or
   stops on the empty page yields something else."""

   return [
      Page(items=(object(), object()), has_next_page=True, end_cursor="cursor-1"),
      Page(items=(), has_next_page=True, end_cursor="cursor-2"),
      Page(items=(object(),), has_next_page=False, end_cursor=None),
   ]


def returned_item_type(function: Any) -> Any:
   return get_args(get_type_hints(function)["return"])[0]


def test_iterator_discovery_finds_exactly_the_iterators_the_table_names() -> None:
   """Catches an iterator added, renamed or dropped without the table saying which read it walks,
   and a table naming a page read that is not a namespace method."""

   assert ITERATOR_METHODS
   assert set(ITERATOR_METHODS) == set(PAGE_METHOD_FOR_ITERATOR)
   assert set(PAGE_METHOD_FOR_ITERATOR.values()) <= set(NAMESPACE_METHODS)


def test_every_paged_read_has_an_iterator() -> None:
   """Catches a namespace read returning a Page that ships without its iter_ companion."""

   paged_reads = {
      qualified
      for qualified in NAMESPACE_METHODS
      if get_origin(
         get_type_hints(getattr(ASYNC_NAMESPACES[split(qualified)[0]], split(qualified)[1]))[
            "return"
         ]
      )
      is Page
   }

   assert paged_reads
   assert paged_reads == set(PAGE_METHOD_FOR_ITERATOR.values())


@pytest.mark.parametrize("qualified", sorted(PAGE_METHOD_FOR_ITERATOR))
def test_an_iterator_takes_its_reads_parameters_plus_a_required_limit_on_both_surfaces(
   qualified: str,
) -> None:
   """Catches a parameter added, dropped or re-defaulted on one surface's iterator, a limit that
   became optional, an iterator yielding another type than its read's page holds, and an async
   iterator declared async, which hands its caller a coroutine that ``async for`` refuses."""

   namespace, method = split(qualified)
   page_namespace, page_method = split(PAGE_METHOD_FOR_ITERATOR[qualified])
   blocking = getattr(SYNC_NAMESPACES[namespace], method)
   awaitable = getattr(ASYNC_NAMESPACES[namespace], method)
   read = getattr(ASYNC_NAMESPACES[page_namespace], page_method)

   limit = ("limit", inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.empty, int | None)
   read_parameters = parameters_of(read)
   first_keyword = next(
      index
      for index, parameter in enumerate(read_parameters)
      if parameter[1] is inspect.Parameter.KEYWORD_ONLY
   )
   expected = [*read_parameters[:first_keyword], limit, *read_parameters[first_keyword:]]

   assert parameters_of(awaitable) == expected
   assert parameters_of(blocking) == expected

   item_type = returned_item_type(read)

   assert get_type_hints(awaitable)["return"] == AsyncIterator[item_type]
   assert get_type_hints(blocking)["return"] == Iterator[item_type]

   for function in (awaitable, blocking):
      assert not inspect.iscoroutinefunction(function)
      assert not inspect.isasyncgenfunction(function)


def spy_on_the_read(
   monkeypatch: pytest.MonkeyPatch, qualified: str, pages: list[Page[object]]
) -> list[tuple[dict[str, Any], str]]:
   page_namespace, page_method = split(PAGE_METHOD_FOR_ITERATOR[qualified])
   read_class = ASYNC_NAMESPACES[page_namespace]
   read_signature = inspect.signature(getattr(read_class, page_method))
   script = list(pages)
   calls: list[tuple[dict[str, Any], str]] = []

   async def spy(self: object, *args: object, **kwargs: object) -> Page[object]:
      bound = read_signature.bind(self, *args, **kwargs)
      bound.apply_defaults()
      received = dict(bound.arguments)
      del received["self"]
      calls.append((received, threading.current_thread().name))

      if not script:
         raise AssertionError(f"{qualified} asked for a page nobody scripted")

      return script.pop(0)

   monkeypatch.setattr(read_class, page_method, spy)

   return calls


def iterator_arguments(function: Any) -> tuple[list[object], dict[str, object]]:
   positional, keyword = distinct_arguments_for(function)
   keyword["limit"] = None

   return positional, keyword


@pytest.mark.asyncio
@pytest.mark.parametrize("qualified", sorted(PAGE_METHOD_FOR_ITERATOR))
async def test_both_iterators_forward_every_argument_and_yield_the_same_items(
   qualified: str, monkeypatch: pytest.MonkeyPatch
) -> None:
   """Catches an argument dropped, swapped or defaulted on the way to the read on either
   surface, a cursor other than the previous page's end cursor, the two surfaces yielding
   different items from the same pages, and a blocking walk reading anywhere but the loop
   thread."""

   namespace, method = split(qualified)
   pages = a_scripted_walk()
   scripted_items = [item for page in pages for item in page.items]
   positional, keyword = iterator_arguments(getattr(SYNC_NAMESPACES[namespace], method))
   forwarded = {name: argument for name, argument in keyword.items() if name != "limit"}

   blocking_calls = spy_on_the_read(monkeypatch, qualified, pages)

   with SyncClient(a_session()) as blocking_client:
      blocking_items = list(
         getattr(getattr(blocking_client, namespace), method)(*positional, **keyword)
      )

   monkeypatch.undo()
   async_calls = spy_on_the_read(monkeypatch, qualified, pages)

   async with AsyncClient(a_session()) as async_client:
      iterator = getattr(getattr(async_client, namespace), method)(*positional, **keyword)
      async_items = [item async for item in iterator]

   assert [id(item) for item in blocking_items] == [id(item) for item in scripted_items]
   assert [id(item) for item in async_items] == [id(item) for item in scripted_items]

   for calls in (blocking_calls, async_calls):
      assert [received["after"] for received, _ in calls] == [
         forwarded["after"],
         "cursor-1",
         "cursor-2",
      ]

      for received, _ in calls:
         held = [value for name, value in received.items() if name != "after"]
         given = [
            argument
            for argument in [*positional, *forwarded.values()]
            if argument is not forwarded["after"]
         ]

         assert [id(value) for value in held] == [id(argument) for argument in given]

   assert {thread_name for _, thread_name in blocking_calls} == {THREAD_NAME}


@pytest.mark.parametrize("qualified", sorted(PAGE_METHOD_FOR_ITERATOR))
def test_a_blocking_iterator_raises_the_async_exception_under_its_own_name(
   qualified: str, monkeypatch: pytest.MonkeyPatch
) -> None:
   """Catches a wrapped exception, and a seam note naming the page read or a neighbour rather
   than the iterator the caller walked."""

   namespace, method = split(qualified)
   page_namespace, page_method = split(PAGE_METHOD_FOR_ITERATOR[qualified])
   raised = LookupError("raised by the async side")

   async def spy(self: object, *args: object, **kwargs: object) -> object:
      raise raised

   monkeypatch.setattr(ASYNC_NAMESPACES[page_namespace], page_method, spy)

   positional, keyword = iterator_arguments(getattr(SYNC_NAMESPACES[namespace], method))

   with SyncClient(a_session()) as client:
      iterator = getattr(getattr(client, namespace), method)(*positional, **keyword)

      with pytest.raises(LookupError) as caught:
         next(iterator)

   assert caught.value is raised
   assert seam_note(f"SyncClient.{namespace}.{method}") in getattr(caught.value, "__notes__", [])
