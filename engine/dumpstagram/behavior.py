"""How a client behaves across requests, as distinct from what each request looks like.

ADR-0013 makes browser parity the default and every departure from it a named setting. A
:class:`Behavior` is that configuration for one client, passed when the client is built and
never global, per ADR-0004. The presets below are ordinary instances, so a preset changes
nothing a caller could not set by hand, and ``dataclasses.replace`` derives a variant of one.

Each setting is added here only once the engine can honour it. Spacing was the first, the
feed's first page the second, the profile route the third, a thread's first page the fourth,
the page load companions the fifth and the cookie sync the sixth. The three write settings came
with the write path, before any write capability, because a write is only safe with all three in
place from the first one. The listener's poll interval came with the ``events()`` surface.
Other companion requests and
side effects such as marking a thread read become settings when the requests behind them are
implemented, as new fields with parity defaults.

What every departure costs is in ``engine/docs/rate-limiting-and-safety.md``. There is no floor
on rate: a caller may set spacing to zero, and the engine does not overrule that decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = [
   "EXPORT",
   "FAST",
   "PARITY",
   "Behavior",
   "FeedFirstPage",
   "ProfileRoute",
   "Spacing",
   "ThreadFirstPage",
]


@dataclass(frozen=True)
class Spacing:
   """The gap one account leaves between two requests.

   Each gap is ``floor_seconds`` plus a uniform draw between zero and twice
   ``mean_jitter_seconds``, so the mean gap is the sum of the two. The gap is measured from the
   account's previous request, whichever client sent it.
   """

   floor_seconds: float
   mean_jitter_seconds: float

   def __post_init__(self) -> None:
      has_negative_floor = self.floor_seconds < 0
      has_negative_jitter = self.mean_jitter_seconds < 0

      if has_negative_floor or has_negative_jitter:
         raise ValueError("spacing cannot be negative, zero is the fastest there is")


class FeedFirstPage(Enum):
   """Where the first page of the home timeline is read from.

   ``DOCUMENT`` is what a browser does: it loads the home page, and the server preloads the
   first page into that document. It is one request of about 1.2 MB, four measured loads
   carried 3 or 4 items, and it refreshes the session's page tokens on the way.

   ``QUERY`` asks the pagination query for the first page, which no browser was observed to
   do. It is one request, and the measured pages carried between 5 and 15 items.
   """

   DOCUMENT = "document"
   QUERY = "query"


class ProfileRoute(Enum):
   """How a profile is read from a username.

   ``PAGE`` is what a browser does: it loads the profile page, reads the account id out of it,
   and sends six queries at once, of which the profile query is one. That is seven requests
   inside one action, about 0.8 MB of document and up to 1.5 MB of answers, and it refreshes
   the session's page tokens on the way.

   ``QUERIES`` resolves the username through one post of the account's timeline and then asks
   the profile query, two requests in series, which no browser was observed to do. An account
   with no post visible to the session cannot be found this way.
   """

   PAGE = "page"
   QUERIES = "queries"


class ThreadFirstPage(Enum):
   """How the newest page of a direct thread is read.

   ``DETAIL`` is what a browser does when it opens a thread: it sends the thread detail query,
   which answers with the thread and its newest 20 messages, about 42 kB for 20. Every older
   page then goes through the pagination query.

   ``QUERY`` asks the pagination query for the newest page too, which no browser was observed
   to do. It is one request either way and returns the same messages.

   Neither sends the rest of what a browser's thread load sends, the eleven inbox queries and
   the detail query for fifteen other threads, and neither marks the thread seen, which a
   browser does over a socket nothing here speaks yet.
   """

   DETAIL = "detail"
   QUERY = "query"


@dataclass(frozen=True)
class Behavior:
   """Everything about a client's traffic that is not the shape of a single request.

   The default is :data:`PARITY`. Every field carries its parity value as its default, so a
   ``Behavior`` built with only the fields a caller wants to change departs from parity in
   exactly those fields and nowhere else.

   ``page_load_companions`` sends, after every document the engine loads, the queries a
   browser's page load sends beside its own: the badge count, the chat tabs jewel, the omni
   picker, two quick promotion calls, and on a profile page the stories tray. None of their
   answers is read. Five or six requests inside the document's own action, departing in the
   page's order and grouping. False leaves them out and changes nothing else.

   ``cookie_sync`` runs, after every document the engine loads, the four requests a browser's
   page sends seconds later to keep its ``fr`` in step with facebook.com: two to
   www.facebook.com carrying no cookies and two to www.instagram.com. They go out 4 to 10 s
   after the document, outside any action and without waiting for the next one, and a client
   closed before then sends none of them. False leaves them out, including all traffic to
   facebook.com, and changes nothing else. The page load companions do not govern it.

   ``write_spacing`` is the gap before a write, measured from the account's previous write. It
   does not delay the reads between two writes, and a write still waits out ``spacing`` from
   whatever request went before it. The default, a 30 s floor plus 5 s mean jitter, is a
   placeholder derived from nothing: no human write timing has been measured yet, so the
   parity preset carries the placeholder too until one is.

   ``write_budget_per_hour`` is how many writes may depart in any rolling hour. A write past it
   raises :class:`~dumpstagram.errors.RateLimited` with ``retry_after`` set and sends nothing.
   None removes the budget. The default of 30 is a placeholder like the spacing.

   ``stop_writes_after_unrecognised_rejection`` refuses every later write once a write has been
   rejected with a code nothing recorded explains, raising
   :class:`~dumpstagram.errors.UpstreamRejected` without sending. Reads carry on. It lasts for
   the life of the client and of every client :meth:`~dumpstagram.AsyncClient.with_behavior`
   derives from it, because an unrecognised rejection of a write is the likeliest form an
   action block takes. False lets writes continue after one.

   None of the three can make the engine retry a write. Nothing can.

   ``poll_interval_seconds`` is how long a listener from ``events()`` waits after one poll
   before the next. A browser does not poll, it holds a socket, so any polling departs from
   parity and the default of 60 s is chosen to cost little: one inbox read a minute plus one
   read per thread that changed, beside a read pacer that allows about 21 a minute. Every poll
   passes the pacer as well, so a short interval is still spaced like any other request. Zero
   polls back to back, and a negative interval is a :class:`ValueError`.
   """

   spacing: Spacing = Spacing(floor_seconds=1.3, mean_jitter_seconds=2.0)
   feed_first_page: FeedFirstPage = FeedFirstPage.DOCUMENT
   profile_route: ProfileRoute = ProfileRoute.PAGE
   thread_first_page: ThreadFirstPage = ThreadFirstPage.DETAIL
   page_load_companions: bool = True
   cookie_sync: bool = True
   write_spacing: Spacing = Spacing(floor_seconds=30.0, mean_jitter_seconds=5.0)
   write_budget_per_hour: int | None = 30
   stop_writes_after_unrecognised_rejection: bool = True
   poll_interval_seconds: float = 60.0

   def __post_init__(self) -> None:
      budget = self.write_budget_per_hour
      has_negative_budget = budget is not None and budget < 0

      if has_negative_budget:
         raise ValueError("a write budget cannot be negative, zero refuses every write")

      has_negative_interval = self.poll_interval_seconds < 0

      if has_negative_interval:
         raise ValueError("a poll interval cannot be negative, zero polls back to back")


PARITY = Behavior()
"""Browser parity, the default.

Spacing is a uniform gap between 1.3 s and 5.3 s, mean 3.3 s. It was fitted to one minute of
the owner browsing by hand on 2026-09-23: 19 gaps between actions, median 2.98 s, mean 3.37 s,
shortest 1.33 s outside stories. One person on one day, so it is provisional and moves as more
samples are pooled. The shortest gap is below the 2.5 s the engine used before, because a
person paging a thread is faster than that. The mean is slower.
"""

EXPORT = Behavior(spacing=Spacing(floor_seconds=2.5, mean_jitter_seconds=0.35))
"""The steady rate a real account sustained, 0.351 requests per second over about 650 requests
with no throttling, measured by the prior project. Machine regular rather than human timing.
"""

FAST = Behavior(
   spacing=Spacing(floor_seconds=0.0, mean_jitter_seconds=0.0),
   write_spacing=Spacing(floor_seconds=0.0, mean_jitter_seconds=0.0),
)
"""No spacing at all, for reads or writes. Requests still look like the browser's and still pass
the pacer, which still holds the whole account when the upstream signals a throttle. The write
budget and the write stop stay as they are, since spacing is all this preset names. No human
reaches this rate, and nothing has measured how the upstream treats it.
"""
