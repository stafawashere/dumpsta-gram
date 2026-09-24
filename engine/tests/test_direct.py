"""Gates on the first capability and on the two facades that expose it.

Three defect classes live here. The capability can return the wrong shape, which is how a raw
dict reaches a caller and the churn boundary stops existing. It can drop a pagination argument,
which reads page one forever and looks like a thread that never grows. And the two facades can
disagree, which is the drift ADR-0011 detects and `test_facade_parity.py` prevents.

Every response is canned. Nothing in this file touches the network.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import parse_qs

import pytest

from dumpstagram import aio
from dumpstagram._core.direct import read_thread_messages
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import Request, Response
from dumpstagram._private.web.bootstrap import BOOTSTRAP_URL
from dumpstagram._private.web.documents.common import API_GRAPHQL_URL
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import ThreadFirstPage
from dumpstagram.client import SyncClient
from dumpstagram.models import Message, Page
from dumpstagram.session import Session, SpinParameters
from tests.test_parse import CURSOR, MESSAGE_ID, THREAD_FBID, node, payload

FB_DTSG = "NAfteQq3example84characterslong"
LSD = "AVqexample22chars"
BLOKS_VERSION_ID = "5f" * 32

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
   + '["WebBloksVersioningID",[],{"versioningID":"'
   + BLOKS_VERSION_ID
   + '"},6640],'
   + '{"X-IG-App-ID":"936619743392459"}</script></html>'
)

APP_SHELL = '<!DOCTYPE html><html><body><div id="mount"></div></body></html>'


class FakeClock:
   def __init__(self) -> None:
      self.now = 0.0

   def __call__(self) -> float:
      return self.now

   async def sleep(self, seconds: float) -> None:
      self.now += seconds

      await asyncio.sleep(0)


class ScriptedTransport:
   def __init__(self, responses: list[Response]) -> None:
      self.responses = list(responses)
      self.sent: list[Request] = []

   async def send(self, request: Request) -> Response:
      self.sent.append(request)

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


def json_response(parsed: dict[str, Any]) -> Response:
   return Response(
      status_code=200,
      headers={"content-type": "application/json; charset=utf-8"},
      content=json.dumps(parsed).encode("utf-8"),
      final_url=API_GRAPHQL_URL,
   )


def a_bootstrapped_session() -> Session:
   session = Session(sessionid="sessionid-value", ds_user_id="1234567890", csrftoken="csrf-value")

   session.fb_dtsg = "an-older-token"
   session.lsd = LSD
   session.app_id = "936619743392459"
   session.spin = SpinParameters(revision="1047996704", branch="trunk", timestamp="1758412345")
   session.bloks_version_id = BLOKS_VERSION_ID

   return session


def make_paced(transport: ScriptedTransport) -> PacedSender:
   clock = FakeClock()
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)

   return PacedSender(transport, pacer)


def sent_variables(request: Request) -> dict[str, Any]:
   body = parse_qs(request.content.decode("utf-8"))

   return json.loads(body["variables"][0])


@pytest.mark.asyncio
async def test_the_capability_returns_typed_models_and_not_a_payload() -> None:
   """Catches a capability that hands the classifier's dict straight back to a caller."""

   transport = ScriptedTransport([json_response(payload([node()], end_cursor=CURSOR))])

   page = await read_thread_messages(make_paced(transport), a_bootstrapped_session(), THREAD_FBID)

   assert isinstance(page, Page)
   assert isinstance(page.items[0], Message)
   assert page.items[0].id == MESSAGE_ID


@pytest.mark.asyncio
async def test_the_cursor_reaches_the_request_body() -> None:
   """Catches a dropped `after`, which silently re-reads the first page of every thread."""

   transport = ScriptedTransport([json_response(payload([node()]))])

   await read_thread_messages(
      make_paced(transport), a_bootstrapped_session(), THREAD_FBID, after=CURSOR
   )

   assert sent_variables(transport.sent[0])["after"] == CURSOR


@pytest.mark.asyncio
async def test_the_newer_than_marker_reaches_the_request_body() -> None:
   """Catches a dropped top-up marker, which turns every poll into a full re-read."""

   transport = ScriptedTransport([json_response(payload([node()]))])

   await read_thread_messages(
      make_paced(transport),
      a_bootstrapped_session(),
      THREAD_FBID,
      newer_than_message_id=MESSAGE_ID,
   )

   assert sent_variables(transport.sent[0])["newer_than_message_id"] == MESSAGE_ID


@pytest.mark.asyncio
async def test_a_session_without_a_token_bootstraps_first() -> None:
   """Catches the capability skipping the bootstrap the internal read already gates."""

   transport = ScriptedTransport([html_response(BOOTSTRAP_PAGE), json_response(payload([node()]))])
   session = Session(sessionid="sessionid-value", ds_user_id="1234567890", csrftoken="csrf-value")

   await read_thread_messages(make_paced(transport), session, THREAD_FBID)

   assert [request.url for request in transport.sent] == [BOOTSTRAP_URL, API_GRAPHQL_URL]
   assert session.fb_dtsg == FB_DTSG


@pytest.mark.asyncio
async def test_a_stale_token_is_re_bootstrapped_once_for_the_capability_too() -> None:
   """Catches the token recovery being wired to the internal read and not to the capability."""

   transport = ScriptedTransport(
      [
         html_response(APP_SHELL, final_url=API_GRAPHQL_URL),
         html_response(BOOTSTRAP_PAGE),
         json_response(payload([node()])),
      ]
   )
   session = a_bootstrapped_session()

   page = await read_thread_messages(make_paced(transport), session, THREAD_FBID)

   assert [request.url for request in transport.sent] == [
      API_GRAPHQL_URL,
      BOOTSTRAP_URL,
      API_GRAPHQL_URL,
   ]
   assert session.fb_dtsg == FB_DTSG
   assert page.items[0].id == MESSAGE_ID


class SpyCapability:
   """Records what a facade passed down, and answers with an empty page."""

   def __init__(self) -> None:
      self.calls: list[tuple[Any, ...]] = []

   async def __call__(
      self,
      sender: Any,
      session: Any,
      thread_fbid: str,
      *,
      after: str | None = None,
      newer_than_message_id: str | None = None,
      first_page: ThreadFirstPage = ThreadFirstPage.QUERY,
      user_agent: str = "",
      deadline: float | None = None,
   ) -> Page[Message]:
      self.calls.append(
         (sender, session, thread_fbid, after, newer_than_message_id, first_page, user_agent)
      )

      return Page(items=(), has_next_page=False)


@pytest.mark.asyncio
async def test_the_async_facade_forwards_every_argument(monkeypatch: pytest.MonkeyPatch) -> None:
   """Catches a facade that accepts an argument and never passes it on."""

   spy = SpyCapability()
   monkeypatch.setattr(aio, "read_thread_messages", spy)

   session = a_bootstrapped_session()

   async with AsyncClient(session, user_agent="a-user-agent") as client:
      page = await client.thread_messages(
         THREAD_FBID, after=CURSOR, newer_than_message_id=MESSAGE_ID
      )

   sender, passed_session, thread_fbid, after, newer_than, first_page, user_agent = spy.calls[0]

   assert sender is client._sender
   assert passed_session is session
   assert thread_fbid == THREAD_FBID
   assert after == CURSOR
   assert newer_than == MESSAGE_ID
   assert first_page is ThreadFirstPage.DETAIL
   assert user_agent == "a-user-agent"
   assert page.items == ()


def test_the_sync_facade_forwards_every_argument(monkeypatch: pytest.MonkeyPatch) -> None:
   """Catches the two surfaces drifting on the arguments of this capability."""

   spy = SpyCapability()
   monkeypatch.setattr(aio, "read_thread_messages", spy)

   session = a_bootstrapped_session()

   with SyncClient(session, user_agent="a-user-agent") as client:
      page = client.thread_messages(THREAD_FBID, after=CURSOR, newer_than_message_id=MESSAGE_ID)

   _, passed_session, thread_fbid, after, newer_than, first_page, user_agent = spy.calls[0]

   assert passed_session is session
   assert thread_fbid == THREAD_FBID
   assert after == CURSOR
   assert newer_than == MESSAGE_ID
   assert first_page is ThreadFirstPage.DETAIL
   assert user_agent == "a-user-agent"
   assert page.items == ()


@pytest.mark.asyncio
async def test_a_closed_client_refuses_rather_than_sending(
   monkeypatch: pytest.MonkeyPatch,
) -> None:
   """Catches a read issued through a connection pool that has already been torn down."""

   spy = SpyCapability()
   monkeypatch.setattr(aio, "read_thread_messages", spy)

   client = AsyncClient(a_bootstrapped_session())

   await client.aclose()

   with pytest.raises(RuntimeError):
      await client.thread_messages(THREAD_FBID)

   assert spy.calls == []
