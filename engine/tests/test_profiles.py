"""Gates on the profile capability, its mapper, and the two requests it is built from.

Four defect classes live here.

The mapper can fill a default where the upstream renamed a field, which is the failure the
corpus rates worst because it degrades records rather than failing.

The capability can send the wrong identifier. The profile query takes a numeric account id,
the same account carries a different ``fbid`` inside a direct thread, and passing the wrong
one is answered with an error envelope rather than with a wrong profile, so a gate has to
read what went on the wire.

The username route can lose its emptiness. An account with nothing visible resolves to no id
at all, and returning a hollow profile there would be worse than failing.

And the two facades can disagree, which is the drift `test_facade_parity.py` prevents.

Every response is canned. Nothing in this file touches the network.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

import pytest

from dumpstagram._core.profiles import read_profile, read_profile_by_id, resolve_username
from dumpstagram._private.web.documents import PROFILE_BY_ID, PROFILE_POSTS
from dumpstagram._private.web.parse import parse_profile, parse_user_id
from dumpstagram._private.web.requests import (
   RESOLUTION_PAGE_SIZE,
   build_profile_request,
   build_username_resolution_request,
)
from dumpstagram.aio import AsyncClient
from dumpstagram.client import SyncClient
from dumpstagram.errors import NotFound, SchemaChanged
from dumpstagram.models import BioLink, Profile
from tests.test_direct import (
   ScriptedTransport,
   a_bootstrapped_session,
   json_response,
   make_paced,
)

USER_ID = "58435292991"
USERNAME = "an-account"
THREAD_SENDER_FBID = "17841400000000000"


def user(**overrides: Any) -> dict[str, Any]:
   """The key set observed on one live profile response on 2026-09-21, with synthetic values.

   Keys that were null on that response are present and null, because a mapper that only ever
   sees the keys it reads is a mapper whose unknown-field policy is untested.
   """

   built: dict[str, Any] = {
      "pk": USER_ID,
      "id": USER_ID,
      "username": USERNAME,
      "full_name": "a name",
      "biography": "a bio",
      "is_private": True,
      "is_verified": False,
      "follower_count": 80,
      "following_count": 124,
      "media_count": 8,
      "total_clips_count": 1,
      "profile_pic_url": "https://example.invalid/pic.jpg",
      "hd_profile_pic_url_info": {"url": "https://example.invalid/pic-hd.jpg"},
      "external_url": "https://example.invalid/",
      "external_lynx_url": "https://l.instagram.com/?u=https%3A%2F%2Fexample.invalid%2F",
      "bio_links": [
         {
            "image_url": "",
            "is_pinned": False,
            "link_id": "18426517714178042",
            "link_type": "external",
            "lynx_url": "https://l.instagram.com/?u=https%3A%2F%2Fexample.invalid%2F",
            "media_accent_color_hex": "",
            "media_type": "none",
            "title": "a link",
            "url": "https://example.invalid/",
            "creation_source": "profile",
         }
      ],
      "category": None,
      "should_show_category": None,
      "account_type": 1,
      "is_business": False,
      "is_professional_account": False,
      "is_memorialized": False,
      "is_unpublished": False,
      "is_embeds_disabled": True,
      "has_profile_pic": True,
      "has_story_archive": True,
      "friendship_status": None,
      "mutual_followers_count": None,
      "pronouns": [],
      "account_badges": [],
      "biography_with_entities": {"entities": []},
      "regulated_news_in_locations": [],
      "profile_pic_genai_tool_info": [],
      "has_chaining": True,
      "has_longform_media": False,
      "is_regulated_c18": False,
      "is_coppa_enforced": False,
      "latest_reel_media": 0,
      "has_visible_media_notes": True,
   }
   built.update(overrides)

   return built


def profile_payload(**overrides: Any) -> dict[str, Any]:
   return {
      "data": {"user": user(**overrides), "viewer": {"user": {"pk": USER_ID, "id": USER_ID}}},
      "extensions": {"is_final": True},
   }


def timeline_payload(*, author_pk: str | None = USER_ID) -> dict[str, Any]:
   edges = (
      []
      if author_pk is None
      else [
         {
            "node": {
               "pk": "3456789012345678901",
               "code": "Cxxxxxxxxxx",
               "user": {"pk": author_pk, "id": author_pk, "username": USERNAME},
            }
         }
      ]
   )

   return {
      "data": {
         "xdt_api__v1__feed__user_timeline_graphql_connection": {
            "edges": edges,
            "page_info": {"has_next_page": False, "end_cursor": None},
         }
      }
   }


def sent_variables(content: bytes) -> dict[str, Any]:
   import json

   body = parse_qs(content.decode("utf-8"))

   return json.loads(body["variables"][0])


def sent_field(content: bytes, name: str) -> str:
   body = parse_qs(content.decode("utf-8"))

   return body[name][0]


def test_the_mapper_returns_a_typed_profile_and_not_a_payload() -> None:
   """Catches a mapper that hands the classifier's dict back and dissolves the boundary."""

   mapped = parse_profile(profile_payload())

   assert isinstance(mapped, Profile)
   assert mapped.id == USER_ID
   assert mapped.username == USERNAME
   assert mapped.follower_count == 80
   assert mapped.bio_links == (
      BioLink(
         link_id="18426517714178042",
         url="https://example.invalid/",
         lynx_url="https://l.instagram.com/?u=https%3A%2F%2Fexample.invalid%2F",
         title="a link",
         link_type="external",
         is_pinned=False,
      ),
   )


@pytest.mark.parametrize(
   "field",
   [
      "id",
      "username",
      "full_name",
      "biography",
      "is_private",
      "is_verified",
      "follower_count",
      "following_count",
      "media_count",
      "total_clips_count",
      "profile_pic_url",
      "account_type",
      "is_business",
      "has_profile_pic",
   ],
)
def test_a_renamed_field_raises_rather_than_defaulting(field: str) -> None:
   """Catches the permissive mapper: a rename must be loud, not a quietly hollow record."""

   payload = profile_payload()
   del payload["data"]["user"][field]

   with pytest.raises(SchemaChanged) as failure:
      parse_profile(payload)

   assert failure.value.path == f"data.user.{field}"


def test_a_count_that_stops_being_a_number_raises() -> None:
   """Catches a mapper that coerces, which would turn a string count into a silent zero."""

   with pytest.raises(SchemaChanged) as failure:
      parse_profile(profile_payload(follower_count="80"))

   assert failure.value.path == "data.user.follower_count"


def test_a_boolean_sent_as_a_number_raises() -> None:
   """Catches truthiness standing in for a boolean, which would read 0 as a real False."""

   with pytest.raises(SchemaChanged) as failure:
      parse_profile(profile_payload(is_private=1))

   assert failure.value.path == "data.user.is_private"


def test_a_missing_hd_picture_is_null_and_not_an_error() -> None:
   """The wrapper being null is an account state, and the rest of the profile still maps."""

   mapped = parse_profile(profile_payload(hd_profile_pic_url_info=None))

   assert mapped.hd_profile_pic_url is None
   assert mapped.profile_pic_url == "https://example.invalid/pic.jpg"


def test_an_hd_picture_wrapper_of_the_wrong_shape_raises() -> None:
   """A string where an object was is the upstream changing, not a missing picture."""

   with pytest.raises(SchemaChanged) as failure:
      parse_profile(profile_payload(hd_profile_pic_url_info="https://example.invalid/pic.jpg"))

   assert failure.value.path == "data.user.hd_profile_pic_url_info"


def test_a_renamed_bio_link_field_raises() -> None:
   """The link tray is mapped field by field too, so a rename inside it is loud as well."""

   payload = profile_payload()
   del payload["data"]["user"]["bio_links"][0]["lynx_url"]

   with pytest.raises(SchemaChanged) as failure:
      parse_profile(payload)

   assert failure.value.path == "data.user.bio_links[0].lynx_url"


def test_the_resolver_reads_the_author_id_off_the_first_post() -> None:
   assert parse_user_id(timeline_payload()) == USER_ID


def test_an_empty_timeline_resolves_to_nothing_rather_than_to_a_wrong_id() -> None:
   """Catches a resolver that reaches into an empty list and invents an answer."""

   assert parse_user_id(timeline_payload(author_pk=None)) is None


def test_the_profile_request_carries_the_account_id_and_its_document() -> None:
   """Catches the identifier confusion the two ids on one account make easy."""

   request = build_profile_request(a_bootstrapped_session(), USER_ID)

   assert sent_field(request.content, "doc_id") == PROFILE_BY_ID.doc_id
   assert sent_field(request.content, "fb_api_req_friendly_name") == PROFILE_BY_ID.friendly_name
   assert sent_variables(request.content)["id"] == USER_ID
   assert "username" not in sent_variables(request.content)


def test_the_resolution_request_asks_for_one_post_and_names_the_username() -> None:
   """Catches a resolver that inherits the web client's twelve and moves 200 kB for an id."""

   request = build_username_resolution_request(a_bootstrapped_session(), USERNAME)
   variables = sent_variables(request.content)

   assert sent_field(request.content, "doc_id") == PROFILE_POSTS.doc_id
   assert variables["username"] == USERNAME
   assert variables["data"]["count"] == RESOLUTION_PAGE_SIZE


@pytest.mark.asyncio
async def test_reading_by_id_spends_one_request() -> None:
   """The whole reason `profile_by_id` exists is that it skips the resolution."""

   transport = ScriptedTransport([json_response(profile_payload())])

   mapped = await read_profile_by_id(make_paced(transport), a_bootstrapped_session(), USER_ID)

   assert isinstance(mapped, Profile)
   assert len(transport.sent) == 1


@pytest.mark.asyncio
async def test_reading_by_username_resolves_first_and_then_reads_by_the_resolved_id() -> None:
   """Catches a capability that sends the username where the id belongs."""

   transport = ScriptedTransport(
      [json_response(timeline_payload()), json_response(profile_payload())]
   )

   mapped = await read_profile(make_paced(transport), a_bootstrapped_session(), USERNAME)

   assert mapped.id == USER_ID
   assert len(transport.sent) == 2
   assert sent_variables(transport.sent[0].content)["username"] == USERNAME
   assert sent_variables(transport.sent[1].content)["id"] == USER_ID


@pytest.mark.asyncio
async def test_an_unresolvable_username_raises_not_found_and_spends_no_second_request() -> None:
   """Catches a capability that reads a profile for an id it never actually got."""

   transport = ScriptedTransport([json_response(timeline_payload(author_pk=None))])

   with pytest.raises(NotFound):
      await resolve_username(make_paced(transport), a_bootstrapped_session(), USERNAME)

   assert len(transport.sent) == 1


@pytest.mark.asyncio
async def test_the_username_route_does_not_read_a_profile_after_a_failed_resolution() -> None:
   transport = ScriptedTransport([json_response(timeline_payload(author_pk=None))])

   with pytest.raises(NotFound):
      await read_profile(make_paced(transport), a_bootstrapped_session(), USERNAME)

   assert len(transport.sent) == 1


@pytest.mark.asyncio
async def test_the_async_facade_delegates_rather_than_reimplementing() -> None:
   transport = ScriptedTransport([json_response(profile_payload())])
   client = AsyncClient(a_bootstrapped_session())
   client._sender = make_paced(transport)

   try:
      mapped = await client.profile_by_id(USER_ID)
   finally:
      await client.aclose()

   assert mapped.id == USER_ID


def test_both_facades_expose_the_same_profile_methods() -> None:
   """Catches the drift where one surface grows a capability and the other does not."""

   for name in ("profile", "profile_by_id"):
      assert hasattr(AsyncClient, name)
      assert hasattr(SyncClient, name)
