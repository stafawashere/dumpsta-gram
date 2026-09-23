"""The polling transport behind ``events()``: one inbox listing read per poll.

Step 23 of ``engine/docs/build-plan.md``, on the first row of the Step 21 table. Each poll reads
the inbox's first page of threads and compares every row's newest message id with what the
previous poll saw. A row whose newest id moved is read back through the thread's scrolling
query, newest page first, until the message the listener last knew in that thread is reached.
That message goes out as ``newer_than_message_id`` on every page of the read, so the upstream
answers only what is newer and ends the read with ``has_next_page`` false at it. Ruling W10 in
``engine/docs/web-parity-plan.md``. Nothing else is sent: no thread open, no mark-seen
mutation, no page load around it. Polling is a departure from parity under ADR-0013 whatever the
preset, because a browser holds a socket.

The messages a row carries are not delivered as they are. Their nodes lack the sender object,
the reactions, ``thread_fbid`` and three flags a :class:`~dumpstagram.models.Message` holds, so
building one from them would fill those with values nobody sent. They place a message id in
time, which is what resolving ``since`` needs, and the thread read supplies the messages.

A row's activity marker moving while its newest message id stays put reads nothing. What moves
the marker without a message is not observed, a reaction is the INFERENCE, and it is not a new
message either way.

The first poll records where every thread stands and delivers nothing, unless the listener was
given ``since``. Then it finds that message among what the rows carry, or failing that on the
newest page of the first :data:`SINCE_SEARCH_THREADS` threads, takes its time as the point to
catch up from, and delivers everything newer in every listed thread. A ``since`` it cannot find
is reported as an :class:`~dumpstagram.models.EventsDropped` with no count and no thread, and
the listener carries on from where the inbox stands, because refusing to start would leave a
consumer that was offline too long with no way back in but dropping its watermark.

Every gap the poller cannot close is reported the same way rather than skipped: a thread whose
known message is not within :data:`THREAD_PAGES_PER_GAP` pages, and an inbox whose first page
ends on a thread that is itself newer than the point being caught up from, since a thread
further down may be newer too.

One attempt per poll, per the pump's contract. A stale token is re-fetched once without a
retry policy, and a poll that fails part of the way through changes nothing here, so the pump's
retry reads the same rows again against the same state.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from dumpstagram._core.realtime.pump import EventSource, Found, SourceContext
from dumpstagram._core.tokens import with_one_token_recovery
from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse import (
   InboxMessage,
   InboxThread,
   parse_inbox_listing,
   parse_inbox_recent_messages,
   parse_thread_message_page,
)
from dumpstagram._private.web.requests import (
   build_inbox_listing_request,
   build_thread_older_page_request,
)
from dumpstagram.models import EventsDropped, Message, Page

__all__ = [
   "SINCE_SEARCH_THREADS",
   "THREAD_PAGES_PER_GAP",
   "InboxPoller",
   "inbox_poller",
]

THREAD_PAGES_PER_GAP = 3
"""How many pages of one thread a poll reads back looking for the last message it knew.

Sixty messages, at the upstream's page size of twenty. A thread that gained more than that
between two polls, a minute apart by default, gets a gap marker instead of more reads.
HYPOTHESIS for the number."""

SINCE_SEARCH_THREADS = 3
"""How many threads the first poll reads looking for a ``since`` no inbox row carries.

The threads are taken in the listing's order, newest activity first, because the thread the
consumer last handled a message in is the likeliest to have moved since. HYPOTHESIS."""

MILLISECONDS_PER_SECOND = 1000


@dataclass(frozen=True)
class KnownThread:
   """Where one thread stood at the last poll that listed it."""

   last_activity_ms: int
   last_message_id: str | None


@dataclass(frozen=True)
class CatchUp:
   """What one thread gained past a known point, and whether the reading reached that point."""

   messages: tuple[Message, ...]
   reached_the_known_point: bool


@dataclass(frozen=True)
class Listing:
   rows: tuple[InboxThread, ...]
   carried: tuple[tuple[InboxMessage, ...], ...]
   has_more_rows: bool


def sent_at_ms(message: Message) -> int:
   return round(message.sent_at.timestamp() * MILLISECONDS_PER_SECOND)


def newest_first(messages: Sequence[Message]) -> list[Message]:
   """The page's messages newest first, whatever order the upstream listed them in."""

   return sorted(messages, key=lambda message: message.sent_at, reverse=True)


class InboxPoller:
   """One listener's view of the inbox, polled through the client's paced sender.

   Holds the device id a browser mints per inbox document, one for the listener's lifetime as
   one open inbox would have, and the last known state of every thread it has listed.
   """

   def __init__(self, context: SourceContext, *, device_id: str | None = None) -> None:
      self._sender = context.sender
      self._session = context.session
      self._user_agent = context.user_agent
      self._since = context.since
      self._device_id = device_id or str(uuid.uuid4())
      self._known: dict[str, KnownThread] = {}
      self._newest_activity_ms: int | None = None

   async def poll(self) -> Sequence[Found]:
      listing = await self._read_listing()
      newest_before = self._newest_activity_ms

      if newest_before is None:
         found = await self._first_poll(listing)
      else:
         found = await self._later_poll(listing, newest_before)

      self._remember(listing)

      return found

   async def _first_poll(self, listing: Listing) -> list[Found]:
      if self._since is None:
         return []

      searched_pages: dict[str, Page[Message]] = {}
      since_ms = carried_time_of(self._since, listing)

      if since_ms is None:
         since_ms = await self._search_threads_for_since(listing, searched_pages)

      if since_ms is None:
         return [EventsDropped(count=None)]

      found: list[Found] = []

      for row in listing.rows:
         is_newer_than_since = row.last_activity_ms > since_ms

         if not is_newer_than_since:
            continue

         catch_up = await self._catch_up(
            row.thread_fbid,
            known_message_id=self._since,
            known_ms=since_ms,
            first_page=searched_pages.get(row.thread_fbid),
         )
         found.extend(gained(row.thread_fbid, catch_up))

      if may_hide_newer_threads(listing, since_ms):
         found.append(EventsDropped(count=None))

      return found

   async def _later_poll(self, listing: Listing, newest_before: int) -> list[Found]:
      found: list[Found] = []

      for row in listing.rows:
         known = self._known.get(row.thread_fbid)

         if known is None:
            is_newer_than_the_last_poll = row.last_activity_ms > newest_before

            if not is_newer_than_the_last_poll:
               continue

            catch_up = await self._catch_up(
               row.thread_fbid, known_message_id=None, known_ms=newest_before
            )
            found.extend(gained(row.thread_fbid, catch_up))

            continue

         newest_id_moved = row.last_message_id != known.last_message_id
         has_a_newest_message = row.last_message_id is not None
         gained_a_message = newest_id_moved and has_a_newest_message

         if not gained_a_message:
            continue

         catch_up = await self._catch_up(
            row.thread_fbid,
            known_message_id=known.last_message_id,
            known_ms=known.last_activity_ms,
            newer_than_message_id=known.last_message_id,
         )
         found.extend(gained(row.thread_fbid, catch_up))

      if may_hide_newer_threads(listing, newest_before):
         found.append(EventsDropped(count=None))

      return found

   async def _search_threads_for_since(
      self,
      listing: Listing,
      searched_pages: dict[str, Page[Message]],
   ) -> int | None:
      for row in listing.rows[:SINCE_SEARCH_THREADS]:
         page = await self._thread_page(row.thread_fbid, after=None)
         searched_pages[row.thread_fbid] = page

         for message in page.items:
            if message.id == self._since:
               return sent_at_ms(message)

      return None

   async def _catch_up(
      self,
      thread_fbid: str,
      *,
      known_message_id: str | None,
      known_ms: int,
      first_page: Page[Message] | None = None,
      newer_than_message_id: str | None = None,
   ) -> CatchUp:
      """Read one thread back from its newest message to the known point.

      The known point is reached at ``known_message_id``, or at the first message older than
      ``known_ms``, which is how a known message that was since removed still closes the gap.
      A message sent in the same millisecond as the known one counts as new unless it is that
      message, since the upstream gives no finer order.

      ``newer_than_message_id`` goes on every page. Only a message of this same thread is
      passed, since a base from another thread has never been sent. The upstream then answers
      the newest twenty past the base and pages back to it, so the read ends on
      ``has_next_page`` and the checks above only matter if the filter is ever ignored.
      """

      gathered: list[Message] = []
      page = first_page
      cursor: str | None = None

      for _ in range(THREAD_PAGES_PER_GAP):
         if page is None:
            page = await self._thread_page(
               thread_fbid, after=cursor, newer_than_message_id=newer_than_message_id
            )

         for message in newest_first(page.items):
            is_the_known_message = message.id == known_message_id
            is_older_than_the_known_point = sent_at_ms(message) < known_ms

            if is_the_known_message or is_older_than_the_known_point:
               return CatchUp(messages=tuple(gathered), reached_the_known_point=True)

            gathered.append(message)

         if not page.has_next_page:
            return CatchUp(messages=tuple(gathered), reached_the_known_point=True)

         cursor = page.end_cursor
         page = None

         if cursor is None:
            break

      return CatchUp(messages=tuple(gathered), reached_the_known_point=False)

   def _remember(self, listing: Listing) -> None:
      for row in listing.rows:
         self._known[row.thread_fbid] = KnownThread(
            last_activity_ms=row.last_activity_ms,
            last_message_id=row.last_message_id,
         )

      activity = [row.last_activity_ms for row in listing.rows]

      if self._newest_activity_ms is not None:
         activity.append(self._newest_activity_ms)

      self._newest_activity_ms = max(activity, default=0)

   async def _read_listing(self) -> Listing:
      def build() -> Request:
         return build_inbox_listing_request(
            self._session, device_id=self._device_id, user_agent=self._user_agent
         )

      def parse(payload: Any) -> Listing:
         page = parse_inbox_listing(payload)

         return Listing(
            rows=page.items,
            carried=parse_inbox_recent_messages(payload),
            has_more_rows=page.has_next_page,
         )

      return await self._read(build, parse)

   async def _thread_page(
      self,
      thread_fbid: str,
      *,
      after: str | None,
      newer_than_message_id: str | None = None,
   ) -> Page[Message]:
      def build() -> Request:
         return build_thread_older_page_request(
            self._session,
            thread_fbid,
            after=after,
            newer_than_message_id=newer_than_message_id,
            user_agent=self._user_agent,
         )

      return await self._read(build, parse_thread_message_page)

   async def _read[T](self, build: Callable[[], Request], parse: Callable[[Any], T]) -> T:
      async def attempt() -> T:
         if not self._session.fb_dtsg:
            await bootstrap(self._sender, self._session, user_agent=self._user_agent)

         response = await self._sender.send(build())

         return parse(classify(response))

      return await with_one_token_recovery(attempt, session=self._session)


def inbox_poller(context: SourceContext) -> EventSource:
   """The source every client's ``events()`` polls through."""

   return InboxPoller(context)


def carried_time_of(message_id: str, listing: Listing) -> int | None:
   for carried in listing.carried:
      for message in carried:
         if message.id == message_id:
            return message.sent_at_ms

   return None


def gained(thread_fbid: str, catch_up: CatchUp) -> list[Found]:
   found: list[Found] = list(catch_up.messages)

   if not catch_up.reached_the_known_point:
      found.insert(0, EventsDropped(count=None, thread_fbid=thread_fbid))

   return found


def may_hide_newer_threads(listing: Listing, point_ms: int) -> bool:
   """Whether a thread past the inbox's first page may hold messages newer than ``point_ms``.

   Rows come newest activity first, so every row past the page is no newer than the last one
   on it. Only when that last row is itself newer than the point can a hidden one be too.
   """

   is_the_whole_inbox = not listing.has_more_rows
   is_empty = not listing.rows

   if is_empty or is_the_whole_inbox:
      return False

   return listing.rows[-1].last_activity_ms > point_ms
