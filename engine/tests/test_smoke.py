"""Gates on the internal end-to-end read.

This is the first code that puts the pacer, the adapter, the transport and the classifier in
one line, so the defects it can produce are joins rather than units: a bootstrap that never
happens, a bootstrap that happens on every call, a re-bootstrap loop that spends a live request
per attempt, and a challenge reaching the retry path through a composition the pacer's own
suite never sees.

Every response here is canned. Nothing in this file touches the network.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.smoke import read_one_thread_page
from dumpstagram._private.transport import Request, Response
from dumpstagram._private.web.bootstrap import BOOTSTRAP_URL
from dumpstagram._private.web.documents.common import API_GRAPHQL_URL
from dumpstagram.errors import CheckpointRequired, UpstreamRejected
from dumpstagram.session import Session, SpinParameters

THREAD_FBID = "17945046917948992"

FB_DTSG = "NAfteQq3example84characterslong"
LSD = "AVqexample22chars"

BOOTSTRAP_PAGE = (
   "<!DOCTYPE html><html><script>"
   + '__d("DTSGInitialData",[],{"token":"'
   + FB_DTSG
   + '"},137);'
   + '__d("LSD",[],{"token":"'
   + LSD
   + '"},138);'
   + '{"__spin_r":1047996704,"__spin_b":"trunk","__spin_t":1758412345,'
   + '"server_revision":1047996704,"hsi":"7551234567890123456",'
   + '"haste_session":"20128.HYP:instagram_web_pkg.2.1...0"},'
   + '{"X-IG-App-ID":"936619743392459"}</script></html>'
)

APP_SHELL = '<!DOCTYPE html><html><body><div id="mount"></div></body></html>'

PAGE_PAYLOAD = {
   "data": {
      "fetch__SlideThread": {
         "as_ig_direct_thread": {
            "slide_messages": {
               "edges": [{"node": {"id": "message-id-one"}}],
               "page_info": {"has_next_page": False, "end_cursor": None},
            }
         }
      }
   }
}


class FakeClock:
   def __init__(self) -> None:
      self.now = 0.0

   def __call__(self) -> float:
      return self.now

   async def sleep(self, seconds: float) -> None:
      self.now += seconds

      await asyncio.sleep(0)


class ScriptedTransport:
   """Answers each request from a queue, and records what it was asked for and when."""

   def __init__(self, clock: FakeClock, responses: list[Response]) -> None:
      self.clock = clock
      self.responses = list(responses)
      self.sent: list[Request] = []
      self.departures: list[float] = []

   async def send(self, request: Request) -> Response:
      self.sent.append(request)
      self.departures.append(self.clock.now)

      if not self.responses:
         raise AssertionError(f"unscripted request to {request.url}")

      return self.responses.pop(0)


def html_response(body: str, *, final_url: str = BOOTSTRAP_URL) -> Response:
   return Response(
      status_code=200,
      headers={"content-type": "text/html; charset=utf-8"},
      content=body.encode("utf-8"),
      final_url=final_url,
   )


def json_response(payload: dict) -> Response:
   return Response(
      status_code=200,
      headers={"content-type": "application/json; charset=utf-8"},
      content=json.dumps(payload).encode("utf-8"),
      final_url=API_GRAPHQL_URL,
   )


def checkpoint_response() -> Response:
   return Response(
      status_code=200,
      headers={"content-type": "text/html; charset=utf-8"},
      content=b"<!DOCTYPE html><html></html>",
      final_url="https://www.instagram.com/challenge/?next=/direct/inbox/",
   )


def an_unbootstrapped_session() -> Session:
   return Session(sessionid="sessionid-value", ds_user_id="1234567890", csrftoken="csrf-value")


def a_bootstrapped_session() -> Session:
   session = an_unbootstrapped_session()

   session.fb_dtsg = "an-older-token"
   session.lsd = LSD
   session.app_id = "936619743392459"
   session.spin = SpinParameters(revision="1047996704", branch="trunk", timestamp="1758412345")

   return session


def make_paced(clock: FakeClock, transport: ScriptedTransport) -> PacedSender:
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)

   return PacedSender(transport, pacer)


@pytest.mark.asyncio
async def test_an_unbootstrapped_session_costs_two_requests() -> None:
   """Catches a read that skips the bootstrap and sends an empty token.

   The upstream answers that with the HTML shell under HTTP 200, so without this the failure
   arrives as a schema complaint rather than as a missing token.
   """
   clock = FakeClock()
   transport = ScriptedTransport(
      clock, [html_response(BOOTSTRAP_PAGE), json_response(PAGE_PAYLOAD)]
   )
   session = an_unbootstrapped_session()

   parsed = await read_one_thread_page(make_paced(clock, transport), session, THREAD_FBID)

   assert [request.url for request in transport.sent] == [BOOTSTRAP_URL, API_GRAPHQL_URL]
   assert transport.sent[1].method == "POST"
   assert session.fb_dtsg == FB_DTSG
   assert parsed == PAGE_PAYLOAD


@pytest.mark.asyncio
async def test_a_bootstrapped_session_costs_one_request() -> None:
   """Catches a bootstrap on every call, which doubles the live cost of every operation."""
   clock = FakeClock()
   transport = ScriptedTransport(clock, [json_response(PAGE_PAYLOAD)])
   session = a_bootstrapped_session()

   parsed = await read_one_thread_page(make_paced(clock, transport), session, THREAD_FBID)

   assert [request.url for request in transport.sent] == [API_GRAPHQL_URL]
   assert parsed == PAGE_PAYLOAD


@pytest.mark.asyncio
async def test_both_requests_pass_the_pacer() -> None:
   """Catches the composition reaching the raw transport for one of its two requests.

   The floor is written out rather than read off the policy, so turning the default down
   cannot also turn this assertion down.
   """
   clock = FakeClock()
   transport = ScriptedTransport(
      clock, [html_response(BOOTSTRAP_PAGE), json_response(PAGE_PAYLOAD)]
   )

   await read_one_thread_page(
      make_paced(clock, transport), an_unbootstrapped_session(), THREAD_FBID
   )

   assert transport.departures == [0.0, 2.5]


@pytest.mark.asyncio
async def test_a_stale_token_is_re_bootstrapped_once() -> None:
   """Catches a read that gives up on the failure a fresh token fixes.

   Token lifetime is bounded below at 16 minutes and not above, so a session loaded from disk
   is expected to carry a token the upstream will no longer accept.
   """
   clock = FakeClock()
   transport = ScriptedTransport(
      clock,
      [
         html_response(APP_SHELL, final_url=API_GRAPHQL_URL),
         html_response(BOOTSTRAP_PAGE),
         json_response(PAGE_PAYLOAD),
      ],
   )
   session = a_bootstrapped_session()

   parsed = await read_one_thread_page(make_paced(clock, transport), session, THREAD_FBID)

   assert [request.url for request in transport.sent] == [
      API_GRAPHQL_URL,
      BOOTSTRAP_URL,
      API_GRAPHQL_URL,
   ]
   assert session.fb_dtsg == FB_DTSG
   assert parsed == PAGE_PAYLOAD


@pytest.mark.asyncio
async def test_a_freshly_fetched_token_is_not_re_bootstrapped() -> None:
   """Catches a re-bootstrap loop, which spends a live request per attempt.

   A token fetched seconds ago and refused immediately is not stale, so fetching another one
   cannot help and the refusal is the answer.
   """
   clock = FakeClock()
   transport = ScriptedTransport(
      clock, [html_response(BOOTSTRAP_PAGE), html_response(APP_SHELL, final_url=API_GRAPHQL_URL)]
   )

   with pytest.raises(UpstreamRejected) as raised:
      await read_one_thread_page(
         make_paced(clock, transport), an_unbootstrapped_session(), THREAD_FBID
      )

   assert raised.value.code == "html_app_shell"
   assert len(transport.sent) == 2


@pytest.mark.asyncio
async def test_a_challenge_stops_the_read_immediately() -> None:
   """Catches a challenge reaching the retry path through this composition.

   Retrying around a challenge escalates a soft block into a locked account, and the read is
   the first place the retry helper and the classifier meet.
   """
   clock = FakeClock()
   transport = ScriptedTransport(clock, [checkpoint_response()])

   with pytest.raises(CheckpointRequired):
      await read_one_thread_page(
         make_paced(clock, transport), an_unbootstrapped_session(), THREAD_FBID
      )

   assert len(transport.sent) == 1
