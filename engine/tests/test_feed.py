"""Gates on the home timeline capability, its mapper, and the request it is built from.

Five defect classes live here, and each one is a way this particular surface is unusual.

The request can go to the wrong path. Every other query in the registry answers on
``/api/graphql``, and this one answered there with HTTP 200 carrying a null connection, no
error envelope and nothing for the classifier to catch. That is the worst failure available
on this surface, because it looks like an empty feed.

The mapper can flatten the union. Every item arrives as one object with nine sibling slots of
which exactly one is filled, and a mapper that reads ``media`` directly would turn two thirds
of a real timeline into nulls or into an exception.

The mapper can fill a default where the upstream renamed a field, which degrades records
rather than failing.

The mapper can read the wrong identifier. ``pk`` and ``id`` are two different values on a
media node, unlike everywhere else on this surface, where they are one value under two names.

And pagination can terminate on a length. Measured pages carried 14, 12 and 5 items for the
same request, and every per-edge cursor was null, so only ``page_info`` says anything.

Every response is canned. Nothing in this file touches the network.
"""

from __future__ import annotations

import importlib
import pkgutil
from datetime import UTC, datetime
from typing import Any

import pytest

from dumpstagram._core.feed import read_feed_page
from dumpstagram._private.web import documents
from dumpstagram._private.web.documents.common import (
   API_GRAPHQL_URL,
   GRAPHQL_QUERY_URL,
   PersistedQuery,
)
from dumpstagram._private.web.documents.direct import THREAD_MESSAGE_PAGE
from dumpstagram._private.web.documents.feed import HOME_TIMELINE_FEED
from dumpstagram._private.web.parse.feed import parse_feed_page
from dumpstagram._private.web.requests.direct import build_thread_page_request
from dumpstagram._private.web.requests.feed import FEED_PAGE_SIZE, build_feed_page_request
from dumpstagram.aio import AsyncClient
from dumpstagram.client import SyncClient
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import FeedItem, FeedItemKind, MediaImage, Page, Post
from tests.test_direct import (
   BLOKS_VERSION_ID,
   BOOTSTRAP_PAGE,
   ScriptedTransport,
   a_bootstrapped_session,
   html_response,
   json_response,
   make_paced,
   sent_variables,
)

AUTHOR_ID = "50476469797"
MEDIA_PK = "3757563240116259739"
MEDIA_ID = f"{MEDIA_PK}_{AUTHOR_ID}"
CURSOR = "a" * 156

UNION_SLOTS = (
   "media",
   "ad",
   "explore_story",
   "end_of_feed_demarcator",
   "stories_netego",
   "suggested_users",
   "bloks_netego",
   "abra_icebreakers_in_feed_unit",
   "ad4ad_in_webfeed",
)


def author(**overrides: Any) -> dict[str, Any]:
   built: dict[str, Any] = {
      "__typename": "XDTUserDict",
      "pk": AUTHOR_ID,
      "id": AUTHOR_ID,
      "username": "an-account",
      "full_name": "a name",
      "is_private": False,
      "is_verified": False,
      "profile_pic_url": "https://example.invalid/pic.jpg",
      "hd_profile_pic_url_info": {"url": "https://example.invalid/pic-hd.jpg"},
      "friendship_status": {"following": True, "is_feed_favorite": False},
      "is_embeds_disabled": False,
      "is_unpublished": False,
      "latest_reel_media": 0,
      "live_broadcast_id": None,
      "transparency_label": None,
      "is_ai_user": None,
   }
   built.update(overrides)

   return built


def media(**overrides: Any) -> dict[str, Any]:
   """The key set observed on a live media node on 2026-09-21, with synthetic values.

   Keys that were null on that page are present and null, because a mapper that only ever
   sees the keys it reads is a mapper whose unknown-field policy is untested.
   """

   built: dict[str, Any] = {
      "pk": MEDIA_PK,
      "id": MEDIA_ID,
      "code": "Cxxxxxxxxxx",
      "taken_at": 1789902875,
      "media_type": 8,
      "product_type": "carousel_container",
      "like_count": 41,
      "comment_count": 3,
      "has_liked": False,
      "is_seen": True,
      "caption": {"pk": "18000000000000000", "text": "a caption", "has_translation": False},
      "accessibility_caption": "a description",
      "original_width": 1440,
      "original_height": 1800,
      "carousel_media_count": 4,
      "image_versions2": {
         "candidates": [
            {"url": "https://example.invalid/1024.jpg", "width": 1024, "height": 1280},
            {"url": "https://example.invalid/640.jpg", "width": 640, "height": 800},
         ]
      },
      "is_paid_partnership": False,
      "like_and_view_counts_disabled": False,
      "user": author(),
      "owner_id": {"pk": AUTHOR_ID, "id": AUTHOR_ID},
      "carousel_media": None,
      "clips_metadata": None,
      "video_versions": None,
      "has_audio": None,
      "view_count": None,
      "location": None,
      "usertags": None,
      "comments_disabled": None,
      "has_viewer_saved": None,
      "media_repost_count": 0,
      "logging_info_token": "a-token",
      "organic_tracking_token": "another-token",
      "inventory_source": "media_or_ad",
      "coauthor_producers": [],
      "top_likers": [],
      "facepile_top_likers": [],
      "social_context": [],
      "floating_context_items": [],
      "media_notes": {"items": []},
   }
   built.update(overrides)

   return built


def item(slot: str = "media", **overrides: Any) -> dict[str, Any]:
   """One union wrapper with exactly one slot filled, the way the upstream sends it."""

   node: dict[str, Any] = {"__typename": "XDTFeedItem"}

   for name in UNION_SLOTS:
      node[name] = None

   node[slot] = media(**overrides) if slot == "media" else {"id": f"a-{slot}"}

   return {"node": node, "cursor": None}


def payload(
   edges: list[dict[str, Any]] | None = None,
   *,
   has_next_page: bool = False,
   end_cursor: str | None = None,
) -> dict[str, Any]:
   return {
      "data": {
         "xdt_api__v1__feed__timeline__connection": {
            "pagination_source": None,
            "edges": [item()] if edges is None else edges,
            "page_info": {
               "has_next_page": has_next_page,
               "has_previous_page": False,
               "start_cursor": None,
               "end_cursor": end_cursor,
            },
         }
      },
      "extensions": {"is_final": True},
      "status": "ok",
   }


def test_the_feed_request_goes_to_the_path_this_query_answers_on() -> None:
   """Catches the silent empty feed: the other path answers 200 with a null connection."""

   request = build_feed_page_request(a_bootstrapped_session())

   assert request.url == GRAPHQL_QUERY_URL
   assert request.url != API_GRAPHQL_URL
   assert HOME_TIMELINE_FEED.url == GRAPHQL_QUERY_URL


def test_the_feed_request_carries_its_document_and_the_cursor_it_was_given() -> None:
   """Catches a rotated document id and a cursor that never reaches the wire."""

   from urllib.parse import parse_qs

   request = build_feed_page_request(a_bootstrapped_session(), after=CURSOR)
   body = parse_qs(request.content.decode("utf-8"))

   assert body["doc_id"][0] == HOME_TIMELINE_FEED.doc_id
   assert body["fb_api_req_friendly_name"][0] == HOME_TIMELINE_FEED.friendly_name

   variables = sent_variables(request)

   assert variables["after"] == CURSOR
   assert variables["first"] == FEED_PAGE_SIZE
   assert variables["variant"] == "home"


def test_the_first_page_is_the_same_query_with_a_null_cursor() -> None:
   """Catches a first-page special case, which the upstream does not have and cannot need."""

   first = build_feed_page_request(a_bootstrapped_session())
   later = build_feed_page_request(a_bootstrapped_session(), after=CURSOR)

   assert first.url == later.url
   assert sent_variables(first)["after"] is None
   assert sent_variables(later)["after"] == CURSOR


def test_the_feed_request_carries_the_two_headers_its_path_carries() -> None:
   """Catches the feed request going out without the headers its path always carried."""

   request = build_feed_page_request(a_bootstrapped_session(), after=CURSOR)

   assert request.headers["x-bloks-version-id"] == BLOKS_VERSION_ID
   assert request.headers["x-root-field-name"] == "xdt_api__v1__feed__timeline__connection"


def test_a_query_on_the_other_path_carries_neither_header() -> None:
   """Catches the two headers leaking onto /api/graphql, where no browser request sent them."""

   request = build_thread_page_request(a_bootstrapped_session(), "340282366841710300")

   assert THREAD_MESSAGE_PAGE.url == API_GRAPHQL_URL
   assert "x-bloks-version-id" not in request.headers
   assert "x-root-field-name" not in request.headers


def test_every_query_on_the_graphql_query_path_names_its_root_field() -> None:
   """Catches a new query on that path sending an empty x-root-field-name."""

   registry = [
      importlib.import_module(f"{documents.__name__}.{module.name}")
      for module in pkgutil.iter_modules(documents.__path__)
   ]
   queries_on_that_path = [
      value
      for module in registry
      for value in vars(module).values()
      if isinstance(value, PersistedQuery) and value.sends_path_headers
   ]

   assert HOME_TIMELINE_FEED in queries_on_that_path
   assert all(query.root_field for query in queries_on_that_path)


def test_the_feed_request_refuses_a_session_with_no_bloks_version_id() -> None:
   """Catches the header going out empty when the page stopped carrying the id."""

   session = a_bootstrapped_session()
   session.bloks_version_id = None

   with pytest.raises(SchemaChanged):
      build_feed_page_request(session, after=CURSOR)


@pytest.mark.asyncio
async def test_a_session_saved_before_the_bloks_id_existed_bootstraps_before_the_feed() -> None:
   """Catches a reloaded session with page tokens but no bloks id failing, not refreshing."""

   session = a_bootstrapped_session()
   session.bloks_version_id = None
   transport = ScriptedTransport([html_response(BOOTSTRAP_PAGE), json_response(payload())])

   await read_feed_page(make_paced(transport), session, after=CURSOR)

   assert [request.url for request in transport.sent][-1] == GRAPHQL_QUERY_URL
   assert len(transport.sent) == 2
   assert transport.sent[1].headers["x-bloks-version-id"] == BLOKS_VERSION_ID


def test_the_mapper_returns_typed_items_and_not_a_payload() -> None:
   """Catches a mapper that hands the classifier's dict back and dissolves the boundary."""

   mapped = parse_feed_page(payload())

   assert isinstance(mapped, Page)
   assert isinstance(mapped.items[0], FeedItem)
   assert isinstance(mapped.items[0].post, Post)


def test_every_union_slot_is_reported_by_name_rather_than_dropped() -> None:
   """Catches a mapper that reads ``media`` directly and loses two thirds of a real page."""

   edges = [item("media"), item("ad"), item("explore_story"), item("ad")]
   mapped = parse_feed_page(payload(edges))

   assert [entry.kind for entry in mapped.items] == [
      FeedItemKind.POST,
      FeedItemKind.AD,
      FeedItemKind.EXPLORE_STORY,
      FeedItemKind.AD,
   ]
   assert [entry.post is not None for entry in mapped.items] == [True, False, False, False]


def test_an_item_with_no_filled_slot_raises_rather_than_being_skipped() -> None:
   """Catches a union that stopped being a union while the page still looks complete."""

   empty = {"node": {"__typename": "XDTFeedItem", **{name: None for name in UNION_SLOTS}}}

   with pytest.raises(SchemaChanged):
      parse_feed_page(payload([empty]))


def test_an_item_with_two_filled_slots_raises_rather_than_picking_one() -> None:
   """Catches a mapper that would silently prefer one slot when the upstream filled two."""

   both = item("media")
   both["node"]["ad"] = {"id": "an-ad"}

   with pytest.raises(SchemaChanged):
      parse_feed_page(payload([both]))


def test_a_union_slot_this_version_does_not_know_raises() -> None:
   """Catches a tenth slot arriving and being reported as a kind nobody defined."""

   unknown = item("media")
   unknown["node"]["media"] = None
   unknown["node"]["a_new_slot"] = {"id": "something"}

   with pytest.raises(SchemaChanged) as failure:
      parse_feed_page(payload([unknown]))

   assert "a_new_slot" in str(failure.value)


def test_the_post_carries_both_identifiers_because_they_differ_here() -> None:
   """Catches ``pk`` and ``id`` being treated as one value, which they are not on media."""

   post = parse_feed_page(payload()).items[0].post

   assert post is not None
   assert post.pk == MEDIA_PK
   assert post.id == MEDIA_ID
   assert post.pk != post.id


def test_the_author_comes_from_the_user_object_and_not_from_owner_id() -> None:
   """Catches a mapper reading the bare-looking ``owner_id``, which is an object here."""

   post = parse_feed_page(payload([item(user=author(username="someone-else"))])).items[0].post

   assert post is not None
   assert post.author.username == "someone-else"
   assert post.author.id == AUTHOR_ID
   assert post.author.is_following is True
   assert post.author.is_favorite is False


def test_taken_at_is_read_as_whole_seconds_and_not_as_milliseconds() -> None:
   """Catches the unit borrowed from a direct message, which would date a post to 1970."""

   post = parse_feed_page(payload()).items[0].post

   assert post is not None
   assert post.taken_at == datetime(2026, 9, 20, 11, 14, 35, tzinfo=UTC)


def test_taken_at_sent_as_a_string_raises_rather_than_being_coerced() -> None:
   """Catches a converter that accepts whatever the upstream sends and guesses the unit."""

   with pytest.raises(SchemaChanged) as failure:
      parse_feed_page(payload([item(taken_at="1789902875")]))

   assert failure.value.path.endswith(".taken_at")


@pytest.mark.parametrize(
   "field",
   ["id", "pk", "code", "media_type", "product_type", "like_count", "comment_count", "has_liked"],
)
def test_a_renamed_media_field_raises_rather_than_defaulting(field: str) -> None:
   """Catches the permissive mapper: a rename must be loud, not a quietly hollow record."""

   edge = item()
   del edge["node"]["media"][field]

   with pytest.raises(SchemaChanged) as failure:
      parse_feed_page(payload([edge]))

   assert failure.value.path.endswith(f".{field}")


def test_a_count_that_stops_being_a_number_raises() -> None:
   """Catches a mapper that coerces, which would turn a string count into a silent zero."""

   with pytest.raises(SchemaChanged) as failure:
      parse_feed_page(payload([item(like_count="41")]))

   assert failure.value.path.endswith(".like_count")


def test_a_post_with_no_caption_maps_rather_than_failing() -> None:
   """A caption is optional, so its absence is an account's choice and not a schema change."""

   post = parse_feed_page(payload([item(caption=None)])).items[0].post

   assert post is not None
   assert post.caption is None
   assert post.code == "Cxxxxxxxxxx"


def test_every_image_rendition_is_kept_in_the_order_it_arrived() -> None:
   """Catches a mapper picking one crop, which would make the other aspect ratios unreachable."""

   post = parse_feed_page(payload()).items[0].post

   assert post is not None
   assert post.images == (
      MediaImage(url="https://example.invalid/1024.jpg", width=1024, height=1280),
      MediaImage(url="https://example.invalid/640.jpg", width=640, height=800),
   )


def test_the_cursor_comes_from_page_info_and_never_from_an_edge() -> None:
   """Catches a reader taking the per-edge cursor, which was null on every measured edge."""

   mapped = parse_feed_page(payload(has_next_page=True, end_cursor=CURSOR))

   assert mapped.has_next_page is True
   assert mapped.end_cursor == CURSOR


def test_a_short_page_claiming_a_successor_is_reported_as_it_arrived() -> None:
   """Catches a length heuristic: a five-item page with more behind it is the normal case."""

   mapped = parse_feed_page(
      payload([item(), item("ad"), item("explore_story")], has_next_page=True, end_cursor=CURSOR)
   )

   assert len(mapped.items) == 3
   assert mapped.has_next_page is True


@pytest.mark.asyncio
async def test_the_capability_returns_typed_models_and_spends_one_request() -> None:
   """Catches a capability that hands the classifier's dict back, or pays for a bootstrap."""

   transport = ScriptedTransport([json_response(payload(has_next_page=True, end_cursor=CURSOR))])

   page = await read_feed_page(make_paced(transport), a_bootstrapped_session())

   assert isinstance(page, Page)
   assert isinstance(page.items[0], FeedItem)
   assert [request.url for request in transport.sent] == [GRAPHQL_QUERY_URL]


@pytest.mark.asyncio
async def test_the_capability_passes_the_cursor_it_was_given_to_the_wire() -> None:
   """Catches a cursor accepted by the signature and dropped before the request is built."""

   transport = ScriptedTransport([json_response(payload())])

   await read_feed_page(make_paced(transport), a_bootstrapped_session(), after=CURSOR)

   assert sent_variables(transport.sent[0])["after"] == CURSOR


def test_both_facades_carry_the_feed_with_the_same_signature() -> None:
   """Catches the asymmetric drift ADR-0011 detects, for this capability by name."""

   from inspect import signature

   assert (
      signature(AsyncClient.feed).parameters.keys() == signature(SyncClient.feed).parameters.keys()
   )
