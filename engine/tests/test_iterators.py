"""Gates on the pagination iterators of E1 item 5, ``client.direct.iter_messages`` and the rest.

Five defect classes live here, each on both surfaces and on every iterator.

A walk can end early. ``has_next_page`` is the only terminator, and a walk that stops on an
empty or short page loses items without an error, the defect ``models/pagination.py`` records.

A walk can end late, reading past the page that said nothing more exists, or reading a page the
``limit`` does not need, which spends a request on the caller's account for nothing.

A walk can lose its place, asking for a page with the wrong cursor, which reads one page again
and again and looks like a connection that never ends.

A page can leave outside the pacer, which is how a caller walking a long thread would hammer
the account the pacer exists to protect.

And a blocking walk closed halfway can leave a read running on the loop thread, which the
caller can neither see nor cancel.

The page reads are replaced by a scripted spy everywhere except the pacing gate, which drives
real comment reads through the paced sender over a scripted transport on a fake clock. Nothing
here touches the network.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest

from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import Request, Response
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY
from dumpstagram.client import SyncClient
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import Page
from dumpstagram.namespaces.direct import AsyncDirect
from dumpstagram.namespaces.feeds import AsyncFeeds
from dumpstagram.namespaces.media import AsyncMedia
from dumpstagram.session import Session
from tests.test_comments import node, page_payload
from tests.test_direct import FakeClock, a_bootstrapped_session, json_response, sent_variables
from tests.test_feed import MEDIA_PK

SURFACES = ["async", "blocking"]

READ_FOR_ITERATOR: dict[str, tuple[type, str, tuple[str, ...]]] = {
   "direct.iter_messages": (AsyncDirect, "messages", ("1234567890123456",)),
   "feeds.iter_home": (AsyncFeeds, "home", ()),
   "media.iter_comments": (AsyncMedia, "comments", (MEDIA_PK,)),
}
"""Each iterator, the async page read it walks, and the positional arguments it needs."""

ITERATORS = sorted(READ_FOR_ITERATOR)


def a_session() -> Session:
   return Session(sessionid="71234567%3AabcdefGHIJKL%3A17", ds_user_id="71234567", csrftoken="t")


def page(*items: str, more: bool, cursor: str | None = None) -> Page[str]:
   return Page(items=tuple(items), has_next_page=more, end_cursor=cursor)


class ScriptedReads:
   """Answers each page read with the next scripted page and records the cursor it was given.
   A read past the script fails the gate, since it is a request the walk should not have sent."""

   def __init__(self, pages: list[Page[str]]) -> None:
      self.pages = list(pages)
      self.cursors: list[str | None] = []

   def install(self, monkeypatch: pytest.MonkeyPatch, qualified: str) -> None:
      read_class, read_name, _ = READ_FOR_ITERATOR[qualified]

      async def read(self_: object, *args: object, after: str | None = None, **_: object) -> Any:
         self.cursors.append(after)

         if not self.pages:
            raise AssertionError(f"{qualified} read a page it did not need, after={after!r}")

         return self.pages.pop(0)

      monkeypatch.setattr(read_class, read_name, read)


async def walk(
   surface: str, qualified: str, *, limit: int | None, after: str | None = None
) -> list[str]:
   namespace, method = qualified.split(".")
   positional = READ_FOR_ITERATOR[qualified][2]

   if surface == "async":
      async with AsyncClient(a_session()) as async_client:
         iterator = getattr(getattr(async_client, namespace), method)(
            *positional, limit=limit, after=after
         )

         return [item async for item in iterator]

   with SyncClient(a_session()) as client:
      return list(
         getattr(getattr(client, namespace), method)(*positional, limit=limit, after=after)
      )


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("qualified", ITERATORS)
async def test_the_walk_ends_on_the_page_whose_has_next_page_is_false(
   qualified: str, surface: str, monkeypatch: pytest.MonkeyPatch
) -> None:
   """Catches a walk that reads past the last page, which the third scripted page, still
   claiming more, would answer."""

   reads = ScriptedReads(
      [
         page("a", "b", more=True, cursor="c1"),
         page("c", more=False),
         page("d", more=True, cursor="c3"),
      ]
   )
   reads.install(monkeypatch, qualified)

   items = await walk(surface, qualified, limit=None)

   assert items == ["a", "b", "c"]
   assert reads.cursors == [None, "c1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("qualified", ITERATORS)
async def test_an_empty_or_short_page_that_says_more_exist_is_followed(
   qualified: str, surface: str, monkeypatch: pytest.MonkeyPatch
) -> None:
   """Catches a walk that takes an empty page, or one shorter than the page before it, as the
   end of the connection."""

   reads = ScriptedReads(
      [
         page("a", "b", more=True, cursor="c1"),
         page(more=True, cursor="c2"),
         page("c", more=True, cursor="c3"),
         page("d", "e", more=False),
      ]
   )
   reads.install(monkeypatch, qualified)

   items = await walk(surface, qualified, limit=None)

   assert items == ["a", "b", "c", "d", "e"]
   assert reads.cursors == [None, "c1", "c2", "c3"]


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("qualified", ITERATORS)
@pytest.mark.parametrize(
   ("limit", "expected_items", "expected_reads"),
   [
      (0, [], 0),
      (1, ["a"], 1),
      (2, ["a", "b"], 1),
      (3, ["a", "b", "c"], 2),
      (4, ["a", "b", "c", "d"], 2),
   ],
)
async def test_the_limit_is_honoured_exactly_without_reading_a_page_it_does_not_use(
   qualified: str,
   surface: str,
   limit: int,
   expected_items: list[str],
   expected_reads: int,
   monkeypatch: pytest.MonkeyPatch,
) -> None:
   """Catches a limit that yields one item too many or too few, and a walk that reads the next
   page after the limit is reached on the last item of a page, or reads anything at zero."""

   reads = ScriptedReads(
      [
         page("a", "b", more=True, cursor="c1"),
         page("c", "d", more=True, cursor="c2"),
         page("e", more=False),
      ]
   )
   reads.install(monkeypatch, qualified)

   items = await walk(surface, qualified, limit=limit)

   assert items == expected_items
   assert len(reads.cursors) == expected_reads


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("qualified", ITERATORS)
async def test_each_page_is_asked_for_with_the_end_cursor_of_the_page_before_it(
   qualified: str, surface: str, monkeypatch: pytest.MonkeyPatch
) -> None:
   """Catches a walk that drops its starting cursor, or asks for page n+1 with anything but
   page n's end cursor."""

   reads = ScriptedReads(
      [
         page("a", more=True, cursor="first-end"),
         page("b", more=True, cursor="second-end"),
         page("c", more=False),
      ]
   )
   reads.install(monkeypatch, qualified)

   items = await walk(surface, qualified, limit=None, after="a-starting-cursor")

   assert items == ["a", "b", "c"]
   assert reads.cursors == ["a-starting-cursor", "first-end", "second-end"]


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("qualified", ITERATORS)
async def test_a_page_that_says_more_exist_without_a_cursor_raises(
   qualified: str, surface: str, monkeypatch: pytest.MonkeyPatch
) -> None:
   """Catches a walk that asks for the next page with no cursor, which reads the first page
   again, or that ends quietly on the contradiction the upstream sent."""

   reads = ScriptedReads([page("a", more=True, cursor=None)])
   reads.install(monkeypatch, qualified)

   with pytest.raises(SchemaChanged):
      await walk(surface, qualified, limit=None)

   assert reads.cursors == [None]


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("qualified", ITERATORS)
async def test_a_negative_limit_is_refused_when_the_iterator_is_made(
   qualified: str, surface: str, monkeypatch: pytest.MonkeyPatch
) -> None:
   """Catches a negative limit that is taken as no limit, which walks a whole thread or an
   endless timeline, and a refusal that waits until the first item is asked for."""

   reads = ScriptedReads([page("a", more=False)])
   reads.install(monkeypatch, qualified)
   namespace, method = qualified.split(".")
   positional = READ_FOR_ITERATOR[qualified][2]

   if surface == "async":
      async with AsyncClient(a_session()) as async_client:
         with pytest.raises(ValueError):
            getattr(getattr(async_client, namespace), method)(*positional, limit=-1)
   else:
      with SyncClient(a_session()) as client:
         with pytest.raises(ValueError):
            getattr(getattr(client, namespace), method)(*positional, limit=-1)

   assert reads.cursors == []


class ClockedTransport:
   """Answers each comment page from a script and records the fake clock at each departure."""

   def __init__(self, clock: FakeClock, responses: list[Response]) -> None:
      self.clock = clock
      self.responses = list(responses)
      self.sent: list[Request] = []
      self.departed_at: list[float] = []

   async def send(self, request: Request) -> Response:
      self.sent.append(request)
      self.departed_at.append(self.clock.now)

      if not self.responses:
         raise AssertionError(f"unscripted request to {request.url}")

      return self.responses.pop(0)

   async def aclose(self) -> None:
      return None


def three_comment_pages() -> list[Response]:
   return [
      json_response(
         page_payload([node(pk="18000000000000001")], has_next_page=True, end_cursor="k1")
      ),
      json_response(page_payload([], has_next_page=True, end_cursor="k2")),
      json_response(
         page_payload([node(pk="18000000000000003")], has_next_page=False, end_cursor=None)
      ),
   ]


SCRIPTED_BEHAVIOR = replace(PARITY, cookie_sync=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", SURFACES)
async def test_every_page_of_a_walk_departs_through_the_pacer_spaced_like_a_read(
   surface: str,
) -> None:
   """Catches a walk that reads its pages around the paced sender, or in parallel, which would
   let them leave back to back instead of a read's spacing apart."""

   clock = FakeClock()
   transport = ClockedTransport(clock, three_comment_pages())
   floor = SCRIPTED_BEHAVIOR.spacing.floor_seconds

   def paced(client: AsyncClient) -> PacedSender:
      pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)

      return PacedSender(transport, pacer, client._sender.pacing, client._sender.writes)

   if surface == "async":
      async_client = AsyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR)
      await async_client._sender.aclose()
      async_client._sender = paced(async_client)

      try:
         comments = [
            comment async for comment in async_client.media.iter_comments(MEDIA_PK, limit=None)
         ]
      finally:
         await async_client.aclose()
   else:
      with SyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR) as client:
         client._loop.run(client._impl._sender.aclose(), operation="the scripted sender swap")
         client._impl._sender = paced(client._impl)
         comments = list(client.media.iter_comments(MEDIA_PK, limit=None))

   assert [comment.id for comment in comments] == ["18000000000000001", "18000000000000003"]
   assert [sent_variables(request)["after"] for request in transport.sent] == [None, "k1", "k2"]

   gaps = [
      later - earlier
      for earlier, later in zip(transport.departed_at, transport.departed_at[1:], strict=False)
   ]

   assert floor > 0
   assert len(gaps) == 2
   assert all(gap >= floor for gap in gaps), gaps


async def an_event() -> asyncio.Event:
   return asyncio.Event()


async def unfinished_tasks() -> list[asyncio.Task[Any]]:
   current = asyncio.current_task()

   return [task for task in asyncio.all_tasks() if task is not current and not task.done()]


@pytest.mark.parametrize("qualified", ITERATORS)
def test_closing_a_blocking_iterator_early_leaves_nothing_running_on_the_loop(
   qualified: str, monkeypatch: pytest.MonkeyPatch
) -> None:
   """Catches a blocking walk that reads ahead of its caller, whose read is left running on the
   loop thread when the caller stops after the first item."""

   read_class, read_name, positional = READ_FOR_ITERATOR[qualified]
   namespace, method = qualified.split(".")
   cursors: list[str | None] = []

   async def read(self_: object, *args: object, after: str | None = None, **_: object) -> Any:
      cursors.append(after)

      if after is None:
         return page("a", "b", more=True, cursor="c1")

      await asyncio.Event().wait()

      raise AssertionError("a page that never answers answered")

   monkeypatch.setattr(read_class, read_name, read)

   with SyncClient(a_session()) as client:
      loop = client._loop._loop
      assert loop is not None

      release = client._loop.run(an_event(), operation="the control's event")
      control = asyncio.run_coroutine_threadsafe(release.wait(), loop)
      seen_with_the_control = client._loop.run(unfinished_tasks(), operation="the control")
      loop.call_soon_threadsafe(release.set)
      control.result(timeout=5)

      assert len(seen_with_the_control) == 1

      iterator = getattr(getattr(client, namespace), method)(*positional, limit=None)
      first = next(iterator)
      iterator.close()

      left_running = client._loop.run(unfinished_tasks(), operation="the check")

   assert first == "a"
   assert left_running == []
   assert cursors == [None]
