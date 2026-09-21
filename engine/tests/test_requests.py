"""Gates on the GraphQL request shape.

Three items out of roughly 38 are validated upstream, and everything else is sent to avoid
being distinguishable from a browser. So these gates cover two different things: that the
three validated items are present, and that the padding around them has not quietly eroded.

The body here is asserted against the request that was observed live on 2026-09-20 and again
on 2026-09-21, and recorded as `direct-thread-message-page` in the knowledge base.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs

import pytest

from dumpstagram._private.transport import Request
from dumpstagram._private.web.documents import THREAD_MESSAGE_PAGE
from dumpstagram._private.web.requests import (
   GRAPHQL_URL,
   PAGE_SIZE,
   VALIDATED_BODY_FIELDS,
   VALIDATED_HEADERS,
   build_thread_page_request,
   jazoest_for,
)
from dumpstagram.errors import AuthenticationFailed
from dumpstagram.session import Session, SpinParameters

THREAD_FBID = "17945046917948992"
FB_DTSG = "NAfteQq3example84characterslong"


def bootstrapped_session() -> Session:
   return Session(
      sessionid="sessionid-value",
      ds_user_id="1234567890",
      csrftoken="csrf-value",
      fb_dtsg=FB_DTSG,
      lsd="AVqexample22chars",
      app_id="936619743392459",
      spin=SpinParameters(revision="1047996704", branch="trunk", timestamp="1758412345"),
      hsi="7551234567890123456",
      haste_session="20128.HYP:instagram_web_pkg.2.1...0",
   )


def body_of(request: Request) -> dict[str, str]:
   assert request.content is not None

   return {key: values[0] for key, values in parse_qs(request.content.decode("utf-8")).items()}


def test_jazoest_is_two_followed_by_the_sum_of_the_character_codes() -> None:
   """Catches a drift in the one computed field, which a browser always sends correctly."""
   assert jazoest_for("ab") == "2195"
   assert jazoest_for(FB_DTSG) == "2" + str(sum(ord(character) for character in FB_DTSG))


def test_every_validated_item_is_sent() -> None:
   """Catches the loss of one of the three items the upstream actually checks.

   Dropping fb_dtsg returns the HTML application shell under HTTP 200, so nothing downstream
   reports a missing field.
   """
   request = build_thread_page_request(bootstrapped_session(), THREAD_FBID)
   body = body_of(request)

   for field in VALIDATED_BODY_FIELDS:
      assert body.get(field), field

   for header in VALIDATED_HEADERS:
      assert request.headers.get(header), header


def test_the_body_carries_the_full_browser_shaped_field_set() -> None:
   """Catches the padding eroding field by field until the request is identifiable.

   A request carrying only the three validated items is one no browser has ever sent.
   """
   request = build_thread_page_request(bootstrapped_session(), THREAD_FBID)

   assert set(body_of(request)) == {
      "av",
      "__d",
      "__user",
      "__a",
      "__req",
      "__hs",
      "dpr",
      "__ccg",
      "__rev",
      "__hsi",
      "__comet_req",
      "fb_dtsg",
      "jazoest",
      "lsd",
      "__spin_r",
      "__spin_b",
      "__spin_t",
      "fb_api_caller_class",
      "fb_api_req_friendly_name",
      "server_timestamps",
      "doc_id",
      "variables",
   }


def test_the_header_set_matches_the_observed_request() -> None:
   """Catches a header quietly dropped, for the same fingerprinting reason as the body."""
   request = build_thread_page_request(bootstrapped_session(), THREAD_FBID)

   assert set(request.headers) == {
      "content-type",
      "sec-fetch-site",
      "sec-fetch-mode",
      "sec-fetch-dest",
      "user-agent",
      "x-ig-app-id",
      "x-csrftoken",
      "x-fb-lsd",
      "x-fb-friendly-name",
      "x-asbd-id",
      "origin",
      "referer",
      "accept",
      "accept-language",
   }


def test_the_persisted_query_comes_from_the_registry() -> None:
   """Catches a doc_id written inline at a call site, where rotation cannot be tracked."""
   request = build_thread_page_request(bootstrapped_session(), THREAD_FBID)
   body = body_of(request)

   assert request.url == GRAPHQL_URL
   assert body["doc_id"] == THREAD_MESSAGE_PAGE.doc_id
   assert body["fb_api_req_friendly_name"] == THREAD_MESSAGE_PAGE.friendly_name
   assert request.headers["x-fb-friendly-name"] == THREAD_MESSAGE_PAGE.friendly_name


def test_the_recorded_doc_id_is_the_one_that_was_observed() -> None:
   """Catches an edit to the registry that nothing replayed against the live surface."""
   assert THREAD_MESSAGE_PAGE.doc_id == "27502152406082940"
   assert THREAD_MESSAGE_PAGE.friendly_name == "useIGDMessageListPaginationQuery"


def test_the_variables_carry_the_thread_and_the_capped_page_size() -> None:
   """Catches a page size raised in the hope of fewer requests, which the server ignores."""
   request = build_thread_page_request(bootstrapped_session(), THREAD_FBID)
   variables = json.loads(body_of(request)["variables"])

   assert PAGE_SIZE == 20
   assert variables["id"] == THREAD_FBID
   assert variables["first"] == 20
   assert variables["after"] is None
   assert variables["newer_than_message_id"] is None


def test_a_cursor_and_a_watermark_reach_the_variables() -> None:
   """Catches pagination and top-up arguments being accepted and then not sent."""
   request = build_thread_page_request(
      bootstrapped_session(),
      THREAD_FBID,
      after="cursor-value",
      newer_than_message_id="mid.$abc",
   )
   variables = json.loads(body_of(request)["variables"])

   assert variables["after"] == "cursor-value"
   assert variables["newer_than_message_id"] == "mid.$abc"


def test_the_referer_names_the_thread_being_read() -> None:
   """Catches a referer that does not match the page such a request comes from."""
   request = build_thread_page_request(bootstrapped_session(), THREAD_FBID)

   assert request.headers["referer"] == f"https://www.instagram.com/direct/t/{THREAD_FBID}/"


def test_a_session_with_no_fb_dtsg_raises_rather_than_sending_an_empty_one() -> None:
   """Catches a reloaded session being used before it has been bootstrapped.

   An empty fb_dtsg returns the HTML shell under HTTP 200, which reaches the caller as a
   schema failure and sends them looking in the wrong place.
   """
   session = bootstrapped_session()
   session.fb_dtsg = None

   with pytest.raises(AuthenticationFailed) as raised:
      build_thread_page_request(session, THREAD_FBID)

   assert "fb_dtsg" in str(raised.value)


def test_the_request_does_not_follow_redirects() -> None:
   """Catches a challenge redirect being followed, which hides it from the URL scan."""
   request = build_thread_page_request(bootstrapped_session(), THREAD_FBID)

   assert request.follow_redirects is False
