"""Gates on reading a profile the way a browser's profile page reads it.

Five defect classes live here. The id reader can take an id that is not the page's account,
since the document carries several numbers beside ``profile_id``. The route can send the
wrong requests, or the right ones in series where the page sends them together, or pace each
of them as its own action, any of which a server comparing traffic with a browser's can see.
It can send the queries before the document's tokens are on the session. It can let a
companion the caller never asked about cost the caller the profile, or, the other way, let a
checkpoint in a companion pass unnoticed. And the client can drop the behavior setting on the
way down.

The documents are synthetic and carry no real content. Nothing in this file touches the
network.
"""

from __future__ import annotations

import asyncio

import pytest

from dumpstagram._core.pacer import Pacer
from dumpstagram._core.profiles import read_profile, read_profile_from_page
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import Request, Response
from dumpstagram._private.web.documents import (
   PROFILE_BY_ID,
   PROFILE_HIGHLIGHTS,
   PROFILE_NOTE_BUBBLE,
   PROFILE_POSTS,
   PROFILE_SCHOOL_BADGE,
   PROFILE_SUGGESTED_USERS,
)
from dumpstagram._private.web.preload import read_profile_id
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY, Behavior, ProfileRoute
from dumpstagram.errors import CheckpointRequired, NotFound, SchemaChanged
from tests.test_direct import (
   BOOTSTRAP_PAGE,
   FB_DTSG,
   FakeClock,
   ScriptedTransport,
   a_bootstrapped_session,
   html_response,
   json_response,
   make_paced,
)
from tests.test_profiles import USER_ID, profile_payload, timeline_payload

USERNAME = "an.account_1"
PAGE_URL = f"https://www.instagram.com/{USERNAME}/"

PAGE_ORDER = [
   PROFILE_BY_ID.friendly_name,
   PROFILE_NOTE_BUBBLE.friendly_name,
   PROFILE_HIGHLIGHTS.friendly_name,
   PROFILE_SUGGESTED_USERS.friendly_name,
   PROFILE_SCHOOL_BADGE.friendly_name,
   PROFILE_POSTS.friendly_name,
]


def profile_document(account_id: str = USER_ID) -> str:
   page_block = (
      '{"route":{"params":{"page_id":"profilePage_'
      + account_id
      + '","profile_id":"'
      + account_id
      + '"}},"timeSpentMetaData":{"container_id":"9999999"}}'
   )

   return BOOTSTRAP_PAGE.replace("</html>", "<script>" + page_block * 2 + "</script></html>")


def companion_payload() -> dict[str, object]:
   return {"data": {"companion": {}}, "extensions": {"is_final": True}}


def the_page_answers(document: str | None = None) -> list[Response]:
   return [
      html_response(document or profile_document(), final_url=PAGE_URL),
      json_response(profile_payload()),
      *[json_response(companion_payload()) for _ in range(5)],
   ]


def friendly_name(request: Request) -> str:
   return request.headers["x-fb-friendly-name"]


class TogetherTransport:
   """Answers nothing until every request it expects is in flight at once."""

   def __init__(self, responses: list[Response], together: int) -> None:
      self.responses = list(responses)
      self.sent: list[Request] = []
      self.in_flight = 0
      self.most_in_flight = 0
      self.together = together

   async def send(self, request: Request) -> Response:
      self.sent.append(request)
      response = self.responses.pop(0)

      if request.method == "GET":
         return response

      self.in_flight += 1
      self.most_in_flight = max(self.most_in_flight, self.in_flight)

      for _ in range(50):
         if self.in_flight >= self.together:
            break

         await asyncio.sleep(0)

      await asyncio.sleep(0)
      self.in_flight -= 1

      return response


def test_the_id_reader_takes_the_account_the_page_is_about() -> None:
   """Catches a reader that returns another number from the page, such as a container id."""

   assert read_profile_id(profile_document()) == USER_ID


def test_a_page_about_no_account_reads_as_none() -> None:
   """Catches a missing account read as an id, or as a failure of the page itself."""

   assert read_profile_id(BOOTSTRAP_PAGE) is None


def test_a_page_naming_two_accounts_raises_rather_than_one_being_picked() -> None:
   """Catches a reader that silently returns the first of two disagreeing ids."""

   document = profile_document().replace("</html>", "") + profile_document("123")

   with pytest.raises(SchemaChanged):
      read_profile_id(document)


@pytest.mark.asyncio
async def test_a_username_that_cannot_exist_is_refused_before_any_request() -> None:
   """Catches a username sent as a path, which could point the navigation somewhere else."""

   transport = ScriptedTransport([])

   with pytest.raises(NotFound):
      await read_profile_from_page(make_paced(transport), a_bootstrapped_session(), "../x")

   assert transport.sent == []


@pytest.mark.asyncio
async def test_the_page_route_loads_the_page_then_sends_the_six_queries_in_page_order() -> None:
   """Catches a missing or extra request, or the queries in an order no page sends them."""

   transport = ScriptedTransport(the_page_answers())

   profile = await read_profile_from_page(make_paced(transport), a_bootstrapped_session(), USERNAME)

   assert profile.id == USER_ID
   assert transport.sent[0].method == "GET"
   assert transport.sent[0].url == PAGE_URL
   assert [friendly_name(request) for request in transport.sent[1:]] == PAGE_ORDER


@pytest.mark.asyncio
async def test_every_query_is_keyed_on_the_id_the_page_carried() -> None:
   """Catches a query built before the id was read, or from some other id."""

   transport = ScriptedTransport(the_page_answers())

   await read_profile_from_page(make_paced(transport), a_bootstrapped_session(), USERNAME)

   companions_keyed_on_the_id = [
      request for request in transport.sent[1:] if USER_ID in request.content.decode("utf-8")
   ]

   assert len(companions_keyed_on_the_id) == 5
   assert all(request.headers["referer"] == PAGE_URL for request in transport.sent[1:])


@pytest.mark.asyncio
async def test_the_six_queries_are_in_flight_together() -> None:
   """Catches the queries sent one after another, where the page sends them within 5 ms."""

   transport = TogetherTransport(the_page_answers(), together=6)

   await read_profile_from_page(make_paced(transport), a_bootstrapped_session(), USERNAME)

   assert transport.most_in_flight == 6


@pytest.mark.asyncio
async def test_the_page_load_is_paced_as_one_action() -> None:
   """Catches each of the seven requests waiting out its own gap, seconds where a page takes ms."""

   clock = FakeClock()
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)
   sender = PacedSender(ScriptedTransport(the_page_answers()), pacer)

   await read_profile_from_page(sender, a_bootstrapped_session(), USERNAME)
   seconds_spent_waiting = clock.now

   assert seconds_spent_waiting == 0.0


@pytest.mark.asyncio
async def test_the_queries_carry_the_tokens_the_page_carried() -> None:
   """Catches the queries built from the session's old token rather than the page's fresh one."""

   transport = ScriptedTransport(the_page_answers())
   session = a_bootstrapped_session()

   await read_profile_from_page(make_paced(transport), session, USERNAME)

   assert session.fb_dtsg == FB_DTSG
   assert all(FB_DTSG in request.content.decode("utf-8") for request in transport.sent[1:])


@pytest.mark.asyncio
async def test_a_page_about_no_account_is_not_found_and_sends_no_query() -> None:
   """Catches a missing account reported as a changed page, or queried for anyway."""

   transport = ScriptedTransport([html_response(BOOTSTRAP_PAGE, final_url=PAGE_URL)])

   with pytest.raises(NotFound):
      await read_profile_from_page(make_paced(transport), a_bootstrapped_session(), USERNAME)

   assert len(transport.sent) == 1


@pytest.mark.asyncio
async def test_a_companion_the_upstream_rejects_does_not_cost_the_profile() -> None:
   """Catches a rejected companion, which the caller never asked for, failing the read."""

   answers = the_page_answers()
   answers[3] = json_response({"errors": [{"code": 1675004, "message": "rejected"}]})
   transport = ScriptedTransport(answers)

   profile = await read_profile_from_page(make_paced(transport), a_bootstrapped_session(), USERNAME)

   assert profile.id == USER_ID


@pytest.mark.asyncio
async def test_a_checkpoint_in_a_companion_is_raised() -> None:
   """Catches a checkpoint hidden because it arrived on a request whose answer is not read."""

   answers = the_page_answers()
   answers[4] = json_response({"error": "challenge_required"})
   transport = ScriptedTransport(answers)

   with pytest.raises(CheckpointRequired):
      await read_profile_from_page(make_paced(transport), a_bootstrapped_session(), USERNAME)


def test_parity_reads_a_profile_from_its_page() -> None:
   """Catches the parity preset defaulting to the departure."""

   assert PARITY.profile_route is ProfileRoute.PAGE
   assert Behavior().profile_route is ProfileRoute.PAGE


@pytest.mark.asyncio
async def test_the_core_keeps_the_queries_route_unless_told_otherwise() -> None:
   """Catches callers below the client moved onto the page route without choosing it."""

   transport = ScriptedTransport(
      [json_response(timeline_payload()), json_response(profile_payload())]
   )

   await read_profile(make_paced(transport), a_bootstrapped_session(), USERNAME)

   assert [friendly_name(request) for request in transport.sent] == [
      PROFILE_POSTS.friendly_name,
      PROFILE_BY_ID.friendly_name,
   ]


async def client_over(transport: ScriptedTransport, behavior: Behavior) -> AsyncClient:
   client = AsyncClient(a_bootstrapped_session(), behavior=behavior)
   await client._sender.aclose()

   scripted: PacedSender = make_paced(transport)
   client._sender = scripted

   return client


@pytest.mark.asyncio
async def test_the_client_loads_the_page_under_the_default_behavior() -> None:
   """Catches a client that drops the behavior setting and falls back to the queries."""

   page_load_companions = 4
   answers = the_page_answers() + [json_response(companion_payload())] * page_load_companions
   transport = ScriptedTransport(answers)
   client = await client_over(transport, PARITY)

   await client.profile(USERNAME)

   assert transport.sent[0].url == PAGE_URL
   assert [friendly_name(request) for request in transport.sent[1:7]] == PAGE_ORDER
   assert len(transport.sent) == 7 + page_load_companions


@pytest.mark.asyncio
async def test_the_client_sends_two_queries_when_the_behavior_names_the_departure() -> None:
   """Catches a departure the configuration names and the client does not honour."""

   transport = ScriptedTransport(
      [json_response(timeline_payload()), json_response(profile_payload())]
   )
   client = await client_over(transport, Behavior(profile_route=ProfileRoute.QUERIES))

   await client.profile(USERNAME)

   assert [friendly_name(request) for request in transport.sent] == [
      PROFILE_POSTS.friendly_name,
      PROFILE_BY_ID.friendly_name,
   ]
