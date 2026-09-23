"""Gates on the page-load cookie sync, the tail a document load leaves behind it.

Every gate runs on a fake clock shared by the pacer, both transports and the tail, so a delay of
seconds costs nothing and the instant each request left is exact. The expected instants are
written out from the captures rather than read from the source's constants.

The defect classes: the four requests missing, extra, out of order, grouped unlike the page or
sent through the wrong transport; the tail sent inside the document's action, timed from the
wrong instant, holding a pacer slot, or setting the gap before the next action; the tail
departing through a throttle or on a checkpointed account; ``fr`` updated by any rule other
than the page's; a tail failure reaching the caller; a tail that outlives its page or its
client; and the behavior setting dropped or tangled with the page load companions.

The documents are synthetic. Nothing in this file touches the network.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from dumpstagram._core.cookie_sync import CookieSync
from dumpstagram._core.feed import read_first_feed_page_from_document
from dumpstagram._core.pacer import Pacer, PacingPolicy
from dumpstagram._core.profiles import read_profile_from_page
from dumpstagram._core.requesting import BackgroundSender, PacedSender
from dumpstagram._private.transport import Request, Response
from dumpstagram._private.web.preload import HOME_DOCUMENT_URL
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import EXPORT, FAST, PARITY, Behavior
from dumpstagram.errors import CheckpointRequired, TransportFailure
from dumpstagram.session import Session
from tests.test_direct import FakeClock, a_bootstrapped_session, html_response, json_response
from tests.test_feed_first_page import a_feed_document
from tests.test_profile_page import PAGE_URL, USERNAME, profile_document
from tests.test_profiles import profile_payload

IFRAME = "GET facebook login_sync"
EXCHANGE = "PolarisAPIGetFrCookieQuery"
FETCH = "GET facebook sync"
POST_BACK = "POST instagram sync"

RECORDED_TAIL = [[IFRAME], [EXCHANGE, FETCH], [POST_BACK]]
"""Every one of the twelve captured loads: the iframe document alone, then the exchange and the
iframe's fetch 8 to 21 ms apart with the exchange first, then the post back once the fetch has
answered."""

IFRAME_LSD = "iframe-lsd-value"
IFRAME_HASTE = "20719.HYP:comet_loggedout_pkg.2.1...0"
IFRAME_HSI = "7688616880443425310"
IFRAME_REVISION = "1048232398"
IFRAME_SPIN_TIME = "1790145617"

IFRAME_DOCUMENT = (
   "<!DOCTYPE html><html><head><script>"
   '["DTSGInitialData",[],{},258],["LSD",[],{"token":"' + IFRAME_LSD + '"},323],'
   '{"haste_session":"' + IFRAME_HASTE + '","hsi":"' + IFRAME_HSI + '",'
   '"server_revision":' + IFRAME_REVISION + ","
   '"__spin_r":' + IFRAME_REVISION + ',"__spin_b":"trunk","__spin_t":' + IFRAME_SPIN_TIME + "}"
   "</script></head><body></body></html>"
)
"""The keys the captured iframe document carries its parameters under, logged out, so its
``DTSGInitialData`` is empty."""

STORED_FR = "stored-fr-value"
ENCRYPTED_DATA = "encrypted-sync-blob"

FR_ROOT = "xdt_api__v1__web__accounts__get_encrypted_credentials"


def fr_answer(fr: str) -> Response:
   return json_response({"data": {FR_ROOT: {"fr": fr}}, "extensions": {"is_final": True}})


def javascript_response(parsed: dict[str, Any], url: str) -> Response:
   return Response(
      status_code=200,
      headers={"content-type": "application/x-javascript; charset=utf-8"},
      content=("for (;;);" + json.dumps(parsed)).encode("utf-8"),
      final_url=url,
   )


def label(request: Request) -> str:
   host = urlsplit(request.url).hostname or ""
   path = urlsplit(request.url).path

   if host == "www.facebook.com":
      return IFRAME if path.endswith("login_sync/") else FETCH

   if path == "/sync/instagram/":
      return POST_BACK

   if request.method == "GET":
      return "GET " + path

   return request.headers["x-fb-friendly-name"]


Answers = dict[str, Response | Exception]


class Wire:
   """Both of one client's transports, recording every request and its instant on one clock.

   A request that arrives while nothing is in flight on either transport opens a new group, and
   each send yields to the loop before answering, so requests sent together share a group.
   """

   def __init__(self, clock: FakeClock, answers: Answers | None = None) -> None:
      self.clock = clock
      self.answers: Answers = {
         "GET /": html_response(a_feed_document(), final_url=HOME_DOCUMENT_URL),
         f"GET /{USERNAME}/": html_response(profile_document(), final_url=PAGE_URL),
         "PolarisProfilePageContentQuery": json_response(profile_payload()),
         IFRAME: html_response(IFRAME_DOCUMENT, final_url="https://www.facebook.com/"),
         EXCHANGE: fr_answer(STORED_FR),
         FETCH: javascript_response(
            {"__ar": 1, "payload": {"data": ENCRYPTED_DATA}, "lid": "1"},
            "https://www.facebook.com/instagram/sync/",
         ),
         POST_BACK: javascript_response(
            {"__ar": 1, "payload": None, "lid": "1"},
            "https://www.instagram.com/sync/instagram/",
         ),
         **(answers or {}),
      }
      self.sent: list[tuple[str, str, Request]] = []
      self.departures: list[tuple[float, str]] = []
      self.groups: list[list[str]] = []
      self.in_flight = 0
      self.instagram = WireEnd(self, "instagram")
      self.facebook = WireEnd(self, "facebook")

   async def send(self, side: str, request: Request) -> Response:
      name = label(request)
      self.sent.append((side, name, request))
      self.departures.append((self.clock.now, name))

      if self.in_flight == 0:
         self.groups.append([])

      self.groups[-1].append(name)
      self.in_flight += 1

      for _ in range(5):
         await asyncio.sleep(0)

      self.in_flight -= 1
      answer = self.answers.get(name, json_response({"data": {}}))

      if isinstance(answer, Exception):
         raise answer

      return answer

   def tail_groups(self) -> list[list[str]]:
      tail_names = {IFRAME, EXCHANGE, FETCH, POST_BACK}

      return [group for group in self.groups if set(group) <= tail_names]

   def departed_at(self, name: str) -> float:
      [instant] = [instant for instant, sent in self.departures if sent == name]

      return instant

   def request(self, name: str) -> Request:
      [request] = [request for _, sent, request in self.sent if sent == name]

      return request

   def side_of(self, name: str) -> str:
      [side] = [side for side, sent, _ in self.sent if sent == name]

      return side


class WireEnd:
   def __init__(self, wire: Wire, side: str) -> None:
      self.wire = wire
      self.side = side

   async def send(self, request: Request) -> Response:
      return await self.wire.send(self.side, request)


def lowest(low: float, high: float) -> float:
   return low


def highest(low: float, high: float) -> float:
   return high


class GatedClock(FakeClock):
   """A fake clock whose sleeps wait for :attr:`gate`, so a sleeper stays asleep until released
   while code that never sleeps runs on."""

   def __init__(self) -> None:
      super().__init__()
      self.gate = asyncio.Event()

   async def sleep(self, seconds: float) -> None:
      await self.gate.wait()
      await super().sleep(seconds)


class Rig:
   """A paced sender and a cookie sync over one wire and one fake clock, as a client builds them."""

   def __init__(
      self,
      answers: Answers | None = None,
      *,
      draw: Callable[[float, float], float] = lowest,
      pacing: PacingPolicy | None = None,
      clock: FakeClock | None = None,
   ) -> None:
      self.clock = clock or FakeClock()
      self.wire = Wire(self.clock, answers)
      self.pacer = Pacer(
         pacing=pacing or PacingPolicy(floor_seconds=0.0, mean_jitter_seconds=0.0),
         clock=self.clock,
         sleep=self.clock.sleep,
         jitter=lambda: 0.0,
      )
      self.sender = PacedSender(self.wire.instagram, self.pacer)
      self.sync = CookieSync(
         self.sender.background(),
         BackgroundSender(self.wire.facebook, self.pacer),
         draw=draw,
      )

   async def load_home(self, session: Session) -> None:
      await read_first_feed_page_from_document(self.sender, session, cookie_sync=self.sync)

   async def settle(self) -> None:
      async with asyncio.timeout(1.0):
         while self.sync.pending:
            await asyncio.sleep(0)


def a_session(fr: str | None = STORED_FR) -> Session:
   session = a_bootstrapped_session()
   session.fr = fr

   return session


def variables_of(request: Request) -> dict[str, Any]:
   body = parse_qs(request.content.decode("utf-8"))

   return json.loads(body["variables"][0])


def form_of(request: Request) -> dict[str, str]:
   body = parse_qs(request.content.decode("utf-8"), keep_blank_values=True)

   return {key: values[0] for key, values in body.items()}


@pytest.mark.asyncio
async def test_a_home_load_leaves_the_recorded_tail() -> None:
   """Catches a tail request missing, extra, out of order, or grouped unlike the page's."""

   rig = Rig()

   await rig.load_home(a_session())
   await rig.settle()

   assert rig.wire.tail_groups() == RECORDED_TAIL


@pytest.mark.asyncio
async def test_each_tail_request_goes_through_its_own_hosts_transport() -> None:
   """Catches the account's cookies sent to facebook.com, or the exchange sent without them."""

   rig = Rig()

   await rig.load_home(a_session())
   await rig.settle()

   assert rig.wire.side_of(IFRAME) == "facebook"
   assert rig.wire.side_of(FETCH) == "facebook"
   assert rig.wire.side_of(EXCHANGE) == "instagram"
   assert rig.wire.side_of(POST_BACK) == "instagram"


@pytest.mark.asyncio
async def test_the_tail_departs_at_the_captured_delays_after_the_document() -> None:
   """Catches the tail sent inside the document's action, or at delays no capture recorded.

   The earliest capture sent the iframe document 3.8 s after the page's and the latest 7.8 s,
   and the iframe was ready 0.15 to 2.45 s after that.
   """

   earliest = Rig(draw=lowest)
   latest = Rig(draw=highest)

   await earliest.load_home(a_session())
   await earliest.settle()
   await latest.load_home(a_session())
   await latest.settle()

   assert earliest.wire.departed_at("GET /") == 0.0
   assert earliest.wire.departed_at(IFRAME) == pytest.approx(3.8)
   assert earliest.wire.departed_at(EXCHANGE) == pytest.approx(3.95)
   assert earliest.wire.departed_at(POST_BACK) == pytest.approx(3.95)
   assert latest.wire.departed_at(IFRAME) == pytest.approx(7.8)
   assert latest.wire.departed_at(EXCHANGE) == pytest.approx(10.25)


@pytest.mark.asyncio
async def test_the_delay_is_measured_from_the_documents_departure() -> None:
   """Catches the delay counted from the end of the action, which adds the action's length."""

   rig = Rig()
   rig.sync.start(a_session(), HOME_DOCUMENT_URL, loaded_at=0.0)
   rig.clock.now = 2.0

   await rig.settle()

   assert rig.wire.departed_at(IFRAME) == pytest.approx(3.8)


@pytest.mark.asyncio
async def test_the_tail_holds_no_pacer_slot() -> None:
   """Catches the tail paced as an action of its own, which a held slot would stall forever."""

   rig = Rig()
   rig.sync.start(a_session(), HOME_DOCUMENT_URL, loaded_at=0.0)

   async with rig.sender.action():
      await rig.settle()

   assert rig.wire.tail_groups() == RECORDED_TAIL


@pytest.mark.asyncio
async def test_the_next_action_is_spaced_from_the_document_and_not_from_the_tail() -> None:
   """Catches the tail recording departures, which would push the user's next action back."""

   rig = Rig(pacing=PacingPolicy(floor_seconds=12.0, mean_jitter_seconds=0.0))

   await rig.load_home(a_session())
   await rig.settle()
   await rig.sender.send(Request(method="GET", url="https://www.instagram.com/next/"))

   assert rig.wire.departed_at(POST_BACK) == pytest.approx(3.95)
   assert rig.wire.departed_at("GET /next/") == pytest.approx(12.0)


@pytest.mark.asyncio
async def test_the_tail_waits_out_a_throttle_hold() -> None:
   """Catches the tail departing while the account is held for a throttle."""

   rig = Rig()
   rig.pacer.hold(20.0)
   rig.sync.start(a_session(), HOME_DOCUMENT_URL, loaded_at=0.0)

   await rig.settle()

   assert rig.wire.departed_at(IFRAME) == pytest.approx(20.0)


@pytest.mark.asyncio
async def test_a_checkpointed_session_departs_nothing() -> None:
   """Catches the tail sending on an account the user has to clear first."""

   rig = Rig()
   session = a_session()
   session.checkpoint_active = True
   rig.sync.start(session, HOME_DOCUMENT_URL, loaded_at=0.0)

   await rig.settle()

   assert rig.wire.sent == []


@pytest.mark.asyncio
async def test_a_checkpoint_on_the_exchange_is_recorded_and_stops_the_post_back() -> None:
   """Catches a checkpoint on a request nobody reads going unrecorded, or sent through."""

   rig = Rig({EXCHANGE: json_response({"error": "challenge_required"})})
   session = a_session()

   await rig.load_home(session)
   await rig.settle()

   assert session.checkpoint_active is True
   assert POST_BACK not in [name for _, name in rig.wire.departures]


@pytest.mark.asyncio
async def test_a_failing_tail_never_reaches_the_caller() -> None:
   """Catches a tail failure surfacing as an exception from the loop or the next await."""

   rig = Rig(
      {
         IFRAME: html_response(IFRAME_DOCUMENT, final_url="https://www.facebook.com/"),
         FETCH: TransportFailure("connection reset"),
         EXCHANGE: TransportFailure("connection reset"),
      }
   )
   session = a_session()

   await rig.load_home(session)
   await rig.settle()

   assert rig.sync._tail is not None
   assert rig.sync._tail.exception() is None
   assert session.checkpoint_active is False


@pytest.mark.parametrize(
   ("stored", "answer", "kept"),
   [
      (STORED_FR, STORED_FR, STORED_FR),
      (STORED_FR, "", None),
      (None, "fresh-fr-value", "fresh-fr-value"),
      (STORED_FR, "fresh-fr-value", "fresh-fr-value"),
   ],
)
@pytest.mark.asyncio
async def test_fr_follows_the_pages_rule(stored: str | None, answer: str, kept: str | None) -> None:
   """Catches ``fr`` updated by any rule but the page's: an equal answer keeps it, an empty one
   removes it, and any other is stored."""

   rig = Rig({EXCHANGE: fr_answer(answer)})
   session = a_session(stored)

   await rig.load_home(session)
   await rig.settle()

   assert variables_of(rig.wire.request(EXCHANGE)) == {"_request_data": {}, "payload": stored}
   assert session.fr == kept


@pytest.mark.asyncio
async def test_a_failed_exchange_removes_fr_and_a_failed_fetch_does_not() -> None:
   """Catches ``fr`` kept after the exchange failed, or cleared by a failure on the other flow."""

   exchange_failed = Rig({EXCHANGE: json_response({"errors": [{"code": 1675004}]})})
   fetch_failed = Rig({FETCH: TransportFailure("connection reset")})
   first = a_session()
   second = a_session()

   await exchange_failed.load_home(first)
   await exchange_failed.settle()
   await fetch_failed.load_home(second)
   await fetch_failed.settle()

   assert first.fr is None
   assert second.fr == STORED_FR
   assert POST_BACK not in [name for _, name in fetch_failed.wire.departures]


@pytest.mark.asyncio
async def test_the_facebook_requests_carry_the_iframe_documents_parameters() -> None:
   """Catches the iframe's fetch keyed on the instagram page's tokens, or shaped unlike a
   browser's iframe."""

   rig = Rig()

   await rig.load_home(a_session())
   await rig.settle()

   document = rig.wire.request(IFRAME)
   fetch = rig.wire.request(FETCH)
   query = parse_qs(urlsplit(fetch.url).query, keep_blank_values=True)

   assert document.headers["referer"] == "https://www.instagram.com/"
   assert document.headers["sec-fetch-site"] == "cross-site"
   assert document.headers["sec-fetch-dest"] == "iframe"
   assert urlsplit(fetch.url).query.startswith("fb_dtsg_ag&")
   assert fetch.headers["x-fb-lsd"] == IFRAME_LSD
   assert fetch.headers["referer"] == "https://www.facebook.com/instagram/login_sync/"
   assert query["__hs"] == [IFRAME_HASTE]
   assert query["__hsi"] == [IFRAME_HSI]
   assert query["__rev"] == [IFRAME_REVISION]
   assert query["__spin_t"] == [IFRAME_SPIN_TIME]
   assert query["__comet_req"] == ["15"]


@pytest.mark.asyncio
async def test_the_post_back_carries_the_fetched_blob_in_the_page_envelope() -> None:
   """Catches the blob lost between the two hosts, or the post shaped as a GraphQL query."""

   rig = Rig()
   session = a_session()

   await rig.load_home(session)
   await rig.settle()

   post = rig.wire.request(POST_BACK)
   form = form_of(post)

   assert form["encrypted_data"] == ENCRYPTED_DATA
   assert form["fb_dtsg"] == session.fb_dtsg
   assert "av" not in form
   assert "doc_id" not in form
   assert "x-csrftoken" not in post.headers
   assert "x-ig-app-id" not in post.headers
   assert post.headers["referer"] == HOME_DOCUMENT_URL


@pytest.mark.asyncio
async def test_a_profile_load_leaves_the_tail_with_the_profile_as_referer() -> None:
   """Catches the profile route leaving no tail, or the tail claiming the home page."""

   rig = Rig()

   await read_profile_from_page(rig.sender, a_session(), USERNAME, cookie_sync=rig.sync)
   await rig.settle()

   assert rig.wire.tail_groups() == RECORDED_TAIL
   assert rig.wire.request(EXCHANGE).headers["referer"] == PAGE_URL
   assert rig.wire.request(POST_BACK).headers["referer"] == PAGE_URL
   assert rig.wire.request(IFRAME).headers["referer"] == "https://www.instagram.com/"


@pytest.mark.asyncio
async def test_a_page_the_sync_exempts_starts_nothing() -> None:
   """Catches the path rule dropped, which matters because a profile path is a username."""

   rig = Rig()
   rig.sync.start(a_session(), "https://www.instagram.com/determs/", loaded_at=0.0)

   await rig.settle()

   assert rig.wire.sent == []


@pytest.mark.asyncio
async def test_a_newer_load_replaces_a_pending_tail() -> None:
   """Catches two tails running for one client, which no single tab produces."""

   rig = Rig()
   rig.sync.start(a_session(), HOME_DOCUMENT_URL, loaded_at=0.0)
   rig.sync.start(a_session(), PAGE_URL, loaded_at=0.0)

   await rig.settle()

   assert rig.wire.tail_groups() == RECORDED_TAIL
   assert rig.wire.request(EXCHANGE).headers["referer"] == PAGE_URL


@pytest.mark.asyncio
async def test_closing_cancels_a_pending_tail_and_starts_no_more() -> None:
   """Catches a tail that outlives its client, which is traffic after the tab closed."""

   rig = Rig()
   rig.sync.start(a_session(), HOME_DOCUMENT_URL, loaded_at=0.0)

   await rig.sync.aclose()
   rig.sync.start(a_session(), HOME_DOCUMENT_URL, loaded_at=0.0)
   await rig.settle()

   assert rig.wire.sent == []


def test_every_preset_runs_the_cookie_sync() -> None:
   """Catches the parity default flipped, or a preset departing without being named."""

   assert Behavior().cookie_sync is True
   assert PARITY.cookie_sync is True
   assert EXPORT.cookie_sync is True
   assert FAST.cookie_sync is True


async def client_over(rig: Rig, behavior: Behavior) -> AsyncClient:
   client = AsyncClient(a_session(), behavior=behavior)
   await client.aclose()

   client._closed = False
   client._sender = rig.sender
   client._cookie_sync = rig.sync

   return client


@pytest.mark.asyncio
async def test_the_client_leaves_a_tail_after_both_document_routes() -> None:
   """Catches a client that drops the setting on the way down to either route."""

   home = Rig()
   profile = Rig()

   await (await client_over(home, PARITY)).feed()
   await home.settle()
   await (await client_over(profile, PARITY)).profile(USERNAME)
   await profile.settle()

   assert home.wire.tail_groups() == RECORDED_TAIL
   assert profile.wire.tail_groups() == RECORDED_TAIL


@pytest.mark.asyncio
async def test_the_departure_drops_the_tail_and_nothing_else() -> None:
   """Catches the setting ignored, or tied to the page load companions either way round."""

   without_sync = Rig()
   without_companions = Rig()

   await (await client_over(without_sync, Behavior(cookie_sync=False))).feed()
   await without_sync.settle()
   await (await client_over(without_companions, Behavior(page_load_companions=False))).feed()
   await without_companions.settle()

   without_sync_names = [name for _, name in without_sync.wire.departures]

   assert without_sync.wire.tail_groups() == []
   assert "QuickPromotionSupportIGSchemaBatchFetchQuery" in without_sync_names
   assert without_companions.wire.tail_groups() == RECORDED_TAIL
   assert without_companions.wire.groups[0] == ["GET /"]


@pytest.mark.asyncio
async def test_a_checkpoint_on_a_later_call_drops_the_pending_tail() -> None:
   """Catches a tail from an earlier page still departing after the account hit a checkpoint."""

   clock = GatedClock()
   checkpoint = json_response({"error": "challenge_required"})
   rig = Rig({"PolarisProfilePageContentQuery": checkpoint}, clock=clock)
   client = await client_over(rig, PARITY)

   await client.feed()

   with pytest.raises(CheckpointRequired):
      await client.profile_by_id("1234567890")

   clock.gate.set()
   await rig.settle()

   assert rig.wire.tail_groups() == []
