"""Gates on the token harvest.

The defects this layer can produce are a null token sent as an empty string, a viewer id read
out of the page, and a challenge reported as bad credentials. All three produce a complete and
entirely plausible wrong answer rather than an error, which is the failure class no amount of
reading the output catches.
"""

from __future__ import annotations

import pytest

from dumpstagram._private.transport import Request, Response
from dumpstagram._private.web.bootstrap import (
   BOOTSTRAP_URL,
   DEFAULT_APP_ID,
   bootstrap,
   build_bootstrap_request,
   read_tokens,
)
from dumpstagram.errors import AuthenticationFailed, CheckpointRequired
from dumpstagram.session import Session

FB_DTSG = "NAfteQq3example84characterslong"
LSD = "AVqexample22chars"
BLOKS_VERSION_ID = "62077fc559de123afe03ebeb18194a88ba5d4e6874d9a07873752f3792adb8a0"

PAGE = (
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
   + '{"X-IG-App-ID":"936619743392459"},'
   + '["WebBloksVersioningID",[],{"versioningID":"'
   + BLOKS_VERSION_ID
   + '"},6640],'
   + '{"USER_ID":"0"},{"USER_ID":"0"}</script></html>'
)


class FakeSender:
   def __init__(self, response: Response) -> None:
      self.response = response
      self.sent: list[Request] = []

   async def send(self, request: Request) -> Response:
      self.sent.append(request)

      return self.response


def html_response(body: str, *, final_url: str = BOOTSTRAP_URL) -> Response:
   return Response(
      status_code=200,
      headers={"content-type": "text/html; charset=utf-8"},
      content=body.encode("utf-8"),
      final_url=final_url,
   )


def a_session() -> Session:
   return Session(sessionid="sessionid-value", ds_user_id="1234567890", csrftoken="csrf-value")


def test_the_bootstrap_request_is_shaped_as_a_navigation() -> None:
   """Catches the page load going out shaped as an API call, which no browser does."""
   request = build_bootstrap_request("agent-string")

   assert request.method == "GET"
   assert request.url == BOOTSTRAP_URL
   assert request.headers["sec-fetch-site"] == "none"
   assert request.headers["sec-fetch-dest"] == "document"
   assert request.follow_redirects is True


def test_every_token_is_read_off_the_page() -> None:
   """Catches a pattern that stops matching after a bundle change, field by field."""
   tokens = read_tokens(PAGE)

   assert tokens.fb_dtsg == FB_DTSG
   assert tokens.lsd == LSD
   assert tokens.app_id == "936619743392459"
   assert tokens.spin.revision == "1047996704"
   assert tokens.spin.branch == "trunk"
   assert tokens.spin.timestamp == "1758412345"
   assert tokens.hsi == "7551234567890123456"
   assert tokens.haste_session == "20128.HYP:instagram_web_pkg.2.1...0"
   assert tokens.bloks_version_id == BLOKS_VERSION_ID


def test_a_page_without_a_bloks_version_id_still_bootstraps() -> None:
   """Catches a missing bloks id failing the bootstrap, which would break thread reads too."""
   page_without_bloks = PAGE.replace("WebBloksVersioningID", "SomethingElse")

   tokens = read_tokens(page_without_bloks)

   assert tokens.fb_dtsg == FB_DTSG
   assert tokens.bloks_version_id is None


def test_a_page_without_fb_dtsg_raises_rather_than_yielding_a_null_token() -> None:
   """Catches an empty fb_dtsg being sent, which returns the HTML shell under HTTP 200."""
   without_token = PAGE.replace("DTSGInitialData", "SomethingElse")

   with pytest.raises(AuthenticationFailed) as raised:
      read_tokens(without_token)

   assert "fb_dtsg" in str(raised.value)


def test_a_page_without_lsd_raises_rather_than_yielding_a_null_token() -> None:
   """Positive control for the gate above, on the second token the same risk applies to."""
   without_token = PAGE.replace('"LSD",[]', '"NotLSD",[]')

   with pytest.raises(AuthenticationFailed) as raised:
      read_tokens(without_token)

   assert "lsd" in str(raised.value)


def test_a_missing_app_id_falls_back_to_the_observed_constant() -> None:
   """The app id is not per session, so a fallback here is a constant, not a guess."""
   without_app_id = PAGE.replace("X-IG-App-ID", "X-IG-Renamed")

   assert read_tokens(without_app_id).app_id == DEFAULT_APP_ID


@pytest.mark.asyncio
async def test_bootstrap_never_takes_the_viewer_id_from_the_page() -> None:
   """Catches the inherited bug where the first USER_ID match is the logged-out placeholder.

   Trusting it sets the viewer id to "0", which inverts the outgoing flag on every record
   without raising anything.
   """
   session = a_session()
   sender = FakeSender(html_response(PAGE))

   await bootstrap(sender, session)

   assert session.ds_user_id == "1234567890"


@pytest.mark.asyncio
async def test_bootstrap_writes_every_token_onto_the_session() -> None:
   """Catches a token harvested and then dropped, which the next request sends as empty."""
   session = a_session()
   sender = FakeSender(html_response(PAGE))

   await bootstrap(sender, session)

   assert session.fb_dtsg == FB_DTSG
   assert session.lsd == LSD
   assert session.app_id == "936619743392459"
   assert session.spin is not None
   assert session.spin.branch == "trunk"
   assert session.hsi == "7551234567890123456"
   assert session.haste_session == "20128.HYP:instagram_web_pkg.2.1...0"
   assert session.bloks_version_id == BLOKS_VERSION_ID
   assert session.bootstrapped_at is not None


@pytest.mark.asyncio
async def test_a_challenge_redirect_is_a_checkpoint_and_not_bad_credentials() -> None:
   """Catches a challenge reported as AuthenticationFailed.

   The challenge page carries no fb_dtsg either, so without the ordered check the user is
   told to re-adopt a session that is fine, and the account stays in the challenge.
   """
   session = a_session()
   sender = FakeSender(
      html_response(
         "<!DOCTYPE html><html>challenge</html>",
         final_url="https://www.instagram.com/challenge/?next=/direct/inbox/",
      )
   )

   with pytest.raises(CheckpointRequired):
      await bootstrap(sender, session)
