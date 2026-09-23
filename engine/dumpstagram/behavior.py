"""How a client behaves across requests, as distinct from what each request looks like.

ADR-0013 makes browser parity the default and every departure from it a named setting. A
:class:`Behavior` is that configuration for one client, passed when the client is built and
never global, per ADR-0004. The presets below are ordinary instances, so a preset changes
nothing a caller could not set by hand, and ``dataclasses.replace`` derives a variant of one.

Each setting is added here only once the engine can honour it. Spacing was the first, the
feed's first page the second and the profile route the third. Other companion requests and
side effects such as marking a thread read become settings when the requests behind them are
implemented, as new fields with parity defaults.

What every departure costs is in ``engine/docs/rate-limiting-and-safety.md``. There is no floor
on rate: a caller may set spacing to zero, and the engine does not overrule that decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = ["EXPORT", "FAST", "PARITY", "Behavior", "FeedFirstPage", "ProfileRoute", "Spacing"]


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


@dataclass(frozen=True)
class Behavior:
   """Everything about a client's traffic that is not the shape of a single request.

   The default is :data:`PARITY`. Every field carries its parity value as its default, so a
   ``Behavior`` built with only the fields a caller wants to change departs from parity in
   exactly those fields and nowhere else.
   """

   spacing: Spacing = Spacing(floor_seconds=1.3, mean_jitter_seconds=2.0)
   feed_first_page: FeedFirstPage = FeedFirstPage.DOCUMENT
   profile_route: ProfileRoute = ProfileRoute.PAGE


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

FAST = Behavior(spacing=Spacing(floor_seconds=0.0, mean_jitter_seconds=0.0))
"""No spacing at all. Requests still look like the browser's and still pass the pacer, which
still holds the whole account when the upstream signals a throttle. No human reaches this rate,
and nothing has measured how the upstream treats it.
"""
