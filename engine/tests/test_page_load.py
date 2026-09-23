"""Gates on the companion requests a page load sends after its document.

The parity gates compare what the engine sends against the burst a browser sent in a recorded
cold load, group by group, where a group is the requests in flight together. The recorded
bursts are written out below rather than read from the captures, because the captures are
local to one machine. What the gates leave out of the recording is named beside it.

The defect classes: a companion missing, extra, or out of the page's order; a group sent one
request at a time or two groups merged; a companion keyed on a device id the document did not
carry; a companion's failure costing the caller the read, or a checkpoint on one passing
unnoticed; the companions paced as actions of their own; and the behavior setting dropped on
the way down.

The documents are synthetic. Nothing in this file touches the network.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import parse_qs

import pytest

from dumpstagram._core.feed import read_first_feed_page_from_document
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.profiles import read_profile_from_page
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import Request, Response
from dumpstagram._private.web.documents import (
   BADGE_COUNT,
   CHAT_TABS_JEWEL,
   OMNI_PICKER_NULL_STATE,
   PROFILE_BY_ID,
   PROFILE_HIGHLIGHTS,
   PROFILE_NOTE_BUBBLE,
   PROFILE_POSTS,
   PROFILE_SCHOOL_BADGE,
   PROFILE_SUGGESTED_USERS,
   QUICK_PROMOTION,
   STORIES_TRAY,
)
from dumpstagram._private.web.preload import HOME_DOCUMENT_URL, read_iris_device_id
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY, Behavior
from dumpstagram.errors import CheckpointRequired
from tests.test_direct import FakeClock, a_bootstrapped_session, html_response, json_response
from tests.test_feed_first_page import a_feed_document
from tests.test_profile_page import PAGE_URL, USERNAME, profile_document
from tests.test_profiles import USER_ID, profile_payload

DEVICE_ID = "3ec93bbe-2ca0-4e7b-be75-f83b7ebc731b"
DEVICE_ID_BLOCK = '["IGDMqttWebDeviceID",[],{"clientId":"' + DEVICE_ID + '"},8312]'

PAGE_SURFACES = "quick promotion: page surfaces"
LOGIN_SURFACE = "quick promotion: login interstitial"

HOME_RECORDED_BURST = [
   ["GET /"],
   [BADGE_COUNT.friendly_name],
   [CHAT_TABS_JEWEL.friendly_name, OMNI_PICKER_NULL_STATE.friendly_name],
   [PAGE_SURFACES],
   [LOGIN_SURFACE],
]
"""The home cold load of ``run-2026-09-23-003559``: the document at 0 ms, the badge count at
748, the jewel and omni picker at 1035 and 1035, the page surfaces at 1846 and the login
interstitial at 2149. Left out of it: ``/data/manifest.json`` at 329 and ``fxcal`` at 662,
which have no verified finding, and the cookie sync from 5244, which is a later step."""

PROFILE_RECORDED_BURST = [
   [f"GET /{USERNAME}/"],
   [
      PROFILE_BY_ID.friendly_name,
      PROFILE_NOTE_BUBBLE.friendly_name,
      PROFILE_HIGHLIGHTS.friendly_name,
      PROFILE_SUGGESTED_USERS.friendly_name,
      PROFILE_SCHOOL_BADGE.friendly_name,
      PROFILE_POSTS.friendly_name,
   ],
   [STORIES_TRAY.friendly_name],
   [CHAT_TABS_JEWEL.friendly_name, OMNI_PICKER_NULL_STATE.friendly_name],
   [BADGE_COUNT.friendly_name],
   [PAGE_SURFACES, LOGIN_SURFACE],
]
"""The other profile cold load of ``run-2026-09-23-004555``: the document at 0 ms, the six at
599 to 603, the stories tray at 871, the jewel and omni picker at 877 and 877, the badge count
at 1042, and both quick promotion calls at 1329 and 1333. Left out of it: the feed timeline
prefetch at 870, which has no finding of its own, ``/data/manifest.json`` and ``fxcal``, and
the cookie sync."""


def with_device_id(document: str) -> str:
   return document.replace("</html>", "<script>" + DEVICE_ID_BLOCK + "</script></html>")


def variables_of(request: Request) -> dict[str, Any]:
   body = parse_qs(request.content.decode("utf-8"))

   return json.loads(body["variables"][0])


def label(request: Request) -> str:
   if request.method == "GET":
      return "GET " + request.url.removeprefix("https://www.instagram.com")

   name = request.headers["x-fb-friendly-name"]

   if name != QUICK_PROMOTION.friendly_name:
      return name

   surfaces = variables_of(request)["surface_nux_ids"]
   is_login_surface = surfaces == ["INSTAGRAM_FOR_WEB_LOGIN_INTERSTITIAL_QP"]

   return LOGIN_SURFACE if is_login_surface else PAGE_SURFACES


def companion_payload() -> dict[str, Any]:
   return {"data": {"companion": {}}, "extensions": {"is_final": True}}


class BurstTransport:
   """Answers by request, and records which requests were in flight together.

   A request that arrives while nothing is in flight opens a new group. Each send yields to the
   loop several times before answering, so requests sent together are all in flight before the
   first of them returns.
   """

   def __init__(self, document: Response, answers: dict[str, Response] | None = None) -> None:
      self.document = document
      self.answers = answers or {}
      self.sent: list[Request] = []
      self.groups: list[list[str]] = []
      self.in_flight = 0

   async def send(self, request: Request) -> Response:
      self.sent.append(request)

      if self.in_flight == 0:
         self.groups.append([])

      self.groups[-1].append(label(request))
      self.in_flight += 1

      for _ in range(5):
         await asyncio.sleep(0)

      self.in_flight -= 1

      if request.method == "GET":
         return self.document

      return self.answers.get(label(request), json_response(companion_payload()))


def home_transport(document: str | None = None, **answers: Response) -> BurstTransport:
   page = document or with_device_id(a_feed_document())

   return BurstTransport(html_response(page, final_url=HOME_DOCUMENT_URL), answers)


def profile_transport(document: str | None = None) -> BurstTransport:
   page = document or with_device_id(profile_document())
   answers = {PROFILE_BY_ID.friendly_name: json_response(profile_payload())}

   return BurstTransport(html_response(page, final_url=PAGE_URL), answers)


def paced(transport: BurstTransport) -> tuple[PacedSender, FakeClock]:
   clock = FakeClock()
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)

   return PacedSender(transport, pacer), clock


async def load_home(transport: BurstTransport) -> None:
   sender, _ = paced(transport)

   await read_first_feed_page_from_document(sender, a_bootstrapped_session(), companions=True)


async def load_profile(transport: BurstTransport) -> None:
   sender, _ = paced(transport)

   await read_profile_from_page(sender, a_bootstrapped_session(), USERNAME, companions=True)


def test_the_device_id_reader_takes_the_documents_client_id() -> None:
   """Catches a reader that misses the id, so the two queries keyed on it silently vanish."""

   assert read_iris_device_id(with_device_id(a_feed_document())) == DEVICE_ID


def test_a_document_without_a_device_id_reads_as_none() -> None:
   """Catches a reader that makes an id up when the document carries none."""

   assert read_iris_device_id(a_feed_document()) is None


@pytest.mark.asyncio
async def test_a_home_load_sends_the_recorded_burst_in_its_groups() -> None:
   """Catches a companion missing, extra, out of order, or grouped unlike the recorded load."""

   transport = home_transport()

   await load_home(transport)

   assert transport.groups == HOME_RECORDED_BURST


@pytest.mark.asyncio
async def test_a_profile_load_sends_the_recorded_burst_in_its_groups() -> None:
   """Catches the same on a profile page, whose order and grouping differ from home's."""

   transport = profile_transport()

   await load_profile(transport)

   assert transport.groups == PROFILE_RECORDED_BURST


@pytest.mark.asyncio
async def test_the_iris_queries_carry_the_documents_device_id() -> None:
   """Catches a device id stored, generated, or taken from anything but this document."""

   transport = home_transport()

   await load_home(transport)

   iris_names = {BADGE_COUNT.friendly_name, CHAT_TABS_JEWEL.friendly_name}
   iris_requests = [request for request in transport.sent if label(request) in iris_names]

   assert len(iris_requests) == 2
   assert all(
      variables_of(request) == {"device_id_for_iris_subscription": DEVICE_ID}
      for request in iris_requests
   )


@pytest.mark.asyncio
async def test_a_document_without_a_device_id_leaves_out_only_the_iris_queries() -> None:
   """Catches a made-up id sent in the document's place, or the whole burst dropped with it."""

   transport = home_transport(a_feed_document())

   await load_home(transport)

   assert transport.groups == [
      ["GET /"],
      [OMNI_PICKER_NULL_STATE.friendly_name],
      [PAGE_SURFACES],
      [LOGIN_SURFACE],
   ]


@pytest.mark.asyncio
async def test_the_page_surfaces_name_the_profile_on_a_profile_page_only() -> None:
   """Catches the profile's trigger context lost, or sent from the home page as well."""

   profile = profile_transport()
   home = home_transport()

   await load_profile(profile)
   await load_home(home)

   def page_surfaces_trigger(transport: BurstTransport) -> object:
      [request] = [request for request in transport.sent if label(request) == PAGE_SURFACES]

      return variables_of(request)["trigger_context"]

   assert page_surfaces_trigger(profile) == {
      "context_data_tuples": [{"context_key": "profile_igid", "context_value": USER_ID}]
   }
   assert page_surfaces_trigger(home) is None


@pytest.mark.asyncio
async def test_every_companion_names_its_page_as_referer() -> None:
   """Catches a companion claiming to come from a page other than the one loaded."""

   profile = profile_transport()
   home = home_transport()

   await load_profile(profile)
   await load_home(home)

   assert {request.headers["referer"] for request in profile.sent[1:]} == {PAGE_URL}
   assert {request.headers["referer"] for request in home.sent[1:]} == {HOME_DOCUMENT_URL}


@pytest.mark.asyncio
async def test_a_rejected_companion_does_not_cost_the_feed_page() -> None:
   """Catches a companion nobody reads failing the read the caller asked for."""

   rejected = json_response({"errors": [{"code": 1675004, "message": "rejected"}]})
   transport = home_transport(**{BADGE_COUNT.friendly_name: rejected})
   sender, _ = paced(transport)

   page = await read_first_feed_page_from_document(
      sender, a_bootstrapped_session(), companions=True
   )

   assert page.items


@pytest.mark.asyncio
async def test_a_checkpoint_on_a_companion_is_raised() -> None:
   """Catches a checkpoint hidden because it arrived on a request whose answer is not read."""

   checkpoint = json_response({"error": "challenge_required"})
   transport = home_transport(**{LOGIN_SURFACE: checkpoint})

   with pytest.raises(CheckpointRequired):
      await load_home(transport)


@pytest.mark.asyncio
async def test_the_burst_is_paced_as_part_of_the_document_action() -> None:
   """Catches each companion group waiting out its own gap, seconds where the page takes ms."""

   transport = home_transport()
   sender, clock = paced(transport)

   await read_first_feed_page_from_document(sender, a_bootstrapped_session(), companions=True)

   assert len(transport.sent) == 6
   assert clock.now == 0.0


def test_parity_sends_the_page_load_companions() -> None:
   """Catches the parity preset defaulting to the departure."""

   assert PARITY.page_load_companions is True
   assert Behavior().page_load_companions is True


async def client_over(transport: BurstTransport, behavior: Behavior) -> AsyncClient:
   client = AsyncClient(a_bootstrapped_session(), behavior=behavior)
   await client._sender.aclose()

   client._sender, _ = paced(transport)

   return client


@pytest.mark.asyncio
async def test_the_client_sends_the_burst_under_the_default_behavior() -> None:
   """Catches a client that drops the setting on the way down to either route."""

   home = home_transport()
   profile = profile_transport()

   await (await client_over(home, PARITY)).feed()
   await (await client_over(profile, PARITY)).profile(USERNAME)

   assert home.groups == HOME_RECORDED_BURST
   assert profile.groups == PROFILE_RECORDED_BURST


@pytest.mark.asyncio
async def test_the_departure_drops_the_companions_and_nothing_else() -> None:
   """Catches a departure the configuration names and the client does not honour, or one that
   also drops the page's own requests."""

   departure = Behavior(page_load_companions=False)
   home = home_transport()
   profile = profile_transport()

   await (await client_over(home, departure)).feed()
   await (await client_over(profile, departure)).profile(USERNAME)

   assert home.groups == HOME_RECORDED_BURST[:1]
   assert profile.groups == PROFILE_RECORDED_BURST[:2]
