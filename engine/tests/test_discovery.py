"""Gates on E2 batch 7, discovery: the explore grid, a place's header and posts, and the new posts
check.

Five defect classes live here.

A mapper can read a field from the wrong key or invent one the answer does not carry. The explore
grid's posts arrive in the REST media shape, which leaves out keys a GraphQL node sends null, so
an absent key can be misread; a place's grid sends an author without a full name, so its posts
are thumbnails.

A block of the grid can go missing. A section carrying something the mapper does not know must
raise rather than drop the posts it holds, and a REST refusal must not read as an empty grid.

A request can go to the wrong path, carry other variables or another referer, or accept an
identifier or a tab it should refuse before sending.

A read can page where nothing verified that paging advances. The grid's next page query answered
the first page's cursor with that same cursor, so nothing may send it (W79).

And a command can take a name where an id is meant, or drop posts in either output form.

The payloads are the recorded answers of 2026-09-27, pseudonymised by
``scripts/build_discovery_fixtures.py``. Nothing in this file touches the network.
"""

from __future__ import annotations

import copy
import io
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import pytest

from dumpstagram._cli.main import main
from dumpstagram._core.discovery import (
   read_explore_grid,
   read_location_info,
   read_location_posts,
   read_new_feed_posts,
)
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.web.documents.catalog import (
   COMPANION_QUERIES,
   READ_QUERIES,
   WRITE_QUERIES,
)
from dumpstagram._private.web.parse.discovery import (
   parse_explore_grid,
   parse_location_info,
   parse_location_posts,
   parse_new_feed_posts,
)
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY
from dumpstagram.client import SyncClient
from dumpstagram.errors import SchemaChanged, UpstreamRejected
from dumpstagram.models import ExploreGrid, LocationPosts, LocationTab, Place, PostThumbnail
from dumpstagram.session import Session
from tests.test_direct import (
   FakeClock,
   ScriptedTransport,
   a_bootstrapped_session,
   json_response,
   make_paced,
   sent_variables,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "discovery"

GRAPHQL_QUERY = "https://www.instagram.com/graphql/query"
API_GRAPHQL = "https://www.instagram.com/api/graphql"
EXPLORE_URL = "https://www.instagram.com/api/v1/discover/web/explore_grid/"
EXPLORE_PAGE = "https://www.instagram.com/explore/"
SITE_ROOT = "https://www.instagram.com/"
LOCATION_INFO_DOC_ID = "28572807415659320"
LOCATION_POSTS_DOC_ID = "28211016731901625"
NEW_FEED_POSTS_DOC_ID = "29095516470048516"
NEXT_PAGE_NAME = "PolarisLocationPageTabContentQuery_connection"
TAB_ROOT = "xdt_location_get_web_info_tab"
SHORT_DRAMA = "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider"
READ_HEADERS = {
   "accept",
   "accept-language",
   "referer",
   "sec-fetch-dest",
   "sec-fetch-mode",
   "sec-fetch-site",
   "user-agent",
   "x-asbd-id",
   "x-csrftoken",
   "x-ig-app-id",
   "x-ig-max-touch-points",
   "x-requested-with",
   "x-web-session-id",
}

SCRIPTED_BEHAVIOR = replace(PARITY, cookie_sync=False)


def recorded(name: str) -> Any:
   return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def location_id() -> str:
   place: dict[str, Any] = recorded("location_info.json")["data"]["xdt_location_get_web_info"]

   return str(place["native_location_data"]["location_info"]["location_id"])


def section_media(grid: dict[str, Any]) -> list[tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
   """Each section's featured and fill media nodes, read straight off the answer."""

   return [
      (
         [item["media"] for item in section["layout_content"]["one_by_two_item"]["clips"]["items"]],
         [item["media"] for item in section["layout_content"]["fill_items"]],
      )
      for section in grid["sectional_items"]
   ]


def grid_nodes() -> list[dict[str, Any]]:
   return [edge["node"] for edge in recorded("location_posts.json")["data"][TAB_ROOT]["edges"]]


def sent_field(request: Any, name: str) -> str:
   return parse_qs(request.content.decode("utf-8"))[name][0]


def test_the_explore_grid_maps_every_section_with_its_featured_and_fill_posts_in_order() -> None:
   """Catches a section dropped, the large tile's posts swapped with the fill tiles, a post read
   off another node, and the more flag read from anything but the answer's own."""

   answer = recorded("explore_grid.json")
   grid = parse_explore_grid(answer)
   expected = section_media(answer)

   assert isinstance(grid, ExploreGrid)
   assert len(grid.sections) == len(expected) == 1
   assert grid.more_available is True
   assert [section.feed_type for section in grid.sections] == ["clips"]

   for section, (featured, fills) in zip(grid.sections, expected, strict=True):
      assert [post.pk for post in section.featured] == [node["pk"] for node in featured]
      assert [post.pk for post in section.posts] == [node["pk"] for node in fills]
      assert [post.code for post in section.posts] == [node["code"] for node in fills]
      assert [post.author.id for post in section.posts] == [node["user"]["id"] for node in fills]

   assert len(section.featured) == 1
   assert len(section.posts) == 4
   assert [post.pk for post in grid.posts] == [
      node["pk"] for featured, fills in expected for node in (*featured, *fills)
   ]
   assert [post.taken_at for post in grid.posts] == [
      datetime.fromtimestamp(node["taken_at"], tz=UTC)
      for featured, fills in expected
      for node in (*featured, *fills)
   ]

   refused = {**answer, "more_available": False}

   assert parse_explore_grid(refused).more_available is False


def test_an_explore_post_reads_what_the_rest_shape_leaves_out_as_null() -> None:
   """Catches a photo refused because it carries no video keys, a reel whose duration is read
   anywhere but its manifest, a reel without its track, ``is_seen`` read as anything but False,
   and the one tagged place lost."""

   answer = recorded("explore_grid.json")
   grid = parse_explore_grid(answer)
   nodes = [node for featured, fills in section_media(answer) for node in (*featured, *fills)]
   photos = [post for post in grid.posts if post.media_type == 1]
   reels = [post for post in grid.posts if post.media_type == 2]
   reel_nodes = [node for node in nodes if node["media_type"] == 2]
   tagged = [
      (post, node) for post, node in zip(grid.posts, nodes, strict=True) if node.get("location")
   ]

   assert len(photos) == 1
   assert photos[0].videos == ()
   assert photos[0].video_duration is None
   assert photos[0].audio is None
   assert photos[0].has_audio is None
   assert photos[0].carousel_children == ()
   assert len(reels) == 4
   assert all(len(post.videos) == 3 for post in reels)
   assert [round(post.video_duration or 0.0, 1) for post in reels] == [
      round(node["video_duration"], 1) for node in reel_nodes
   ]
   assert all(post.audio is not None for post in reels)
   assert all(post.accessibility_caption is None for post in reels)
   assert {post.is_seen for post in grid.posts} == {False}
   assert len(tagged) == 1
   assert tagged[0][0].location is not None
   assert tagged[0][0].location.id == tagged[0][1]["location"]["pk"]
   assert tagged[0][0].location.name == tagged[0][1]["location"]["name"]


def test_an_explore_carousel_maps_every_slide_though_its_photo_slides_carry_no_video_keys() -> None:
   """Catches the one carousel of both answers refused over its slides' absent video keys, or
   mapped without its slides."""

   answer = recorded("explore_carousel.json")
   grid = parse_explore_grid(answer)
   _, fills = section_media(answer)[0]
   carousel = grid.sections[0].posts[0]
   slides = fills[0]["carousel_media"]

   assert carousel.media_type == 8
   assert carousel.carousel_media_count == len(slides) == 16
   assert [child.pk for child in carousel.carousel_children] == [slide["pk"] for slide in slides]
   assert {child.videos for child in carousel.carousel_children} == {()}
   assert carousel.videos == ()


def test_an_unknown_block_a_refusal_and_a_key_outside_the_absent_set_are_not_mapped() -> None:
   """Catches a section block the mapper does not know dropped with its posts, a REST refusal
   read as an empty grid, and the absent-as-null rule widened to a key a post cannot lack."""

   answer = recorded("explore_grid.json")
   unknown_block = copy.deepcopy(answer)
   unknown_block["sectional_items"][0]["layout_content"]["medias"] = []
   refused = {**answer, "status": "fail"}
   no_like_count = copy.deepcopy(answer)
   del no_like_count["sectional_items"][0]["layout_content"]["fill_items"][0]["media"]["like_count"]

   with pytest.raises(SchemaChanged, match="medias"):
      parse_explore_grid(unknown_block)

   with pytest.raises(UpstreamRejected):
      parse_explore_grid(refused)

   with pytest.raises(SchemaChanged, match="like_count"):
      parse_explore_grid(no_like_count)


def test_a_place_maps_every_field_from_its_own_key() -> None:
   """Catches a field read from a neighbour's key. The recorded place sent an empty city, zip
   code and phone and the fixture zeroes coordinates, so those four and the price range are given
   distinct values here, and a swap between any two fields shows."""

   answer = recorded("location_info.json")
   info = answer["data"]["xdt_location_get_web_info"]["native_location_data"]["location_info"]
   info.update(
      {
         "lat": 38.5,
         "lng": -77.25,
         "location_city": "a city",
         "location_zip": "a zip code",
         "phone": "a phone",
         "price_range": 2,
      }
   )
   place = parse_location_info(answer)

   assert place == Place(
      id=info["location_id"],
      name=info["name"],
      category=info["category"],
      lat=38.5,
      lng=-77.25,
      media_count=20669042,
      slug=info["slug"],
      address=info["location_address"],
      city="a city",
      zip_code="a zip code",
      phone="a phone",
      price_range=2,
   )
   assert len({place.id, place.name, place.category, place.slug, place.address}) == 5


def test_a_places_grid_maps_each_post_as_a_thumbnail_in_order_with_the_more_flag() -> None:
   """Catches a post dropped or reordered, the author read from anything but the node's own
   ``pk``, and the more flag read from anything but ``has_next_page``."""

   answer = recorded("location_posts.json")
   nodes = grid_nodes()
   page = parse_location_posts(answer)
   ended = copy.deepcopy(answer)
   ended["data"][TAB_ROOT]["page_info"]["has_next_page"] = False

   assert isinstance(page, LocationPosts)
   assert all(isinstance(post, PostThumbnail) for post in page.posts)
   assert len(page.posts) == 4
   assert [post.pk for post in page.posts] == [node["pk"] for node in nodes]
   assert [post.code for post in page.posts] == [node["code"] for node in nodes]
   assert [post.author_id for post in page.posts] == [node["user"]["pk"] for node in nodes]
   assert [post.author_username for post in page.posts] == [
      node["user"]["username"] for node in nodes
   ]
   assert [post.carousel_media_count for post in page.posts] == [
      node["carousel_media_count"] for node in nodes
   ]
   assert page.has_more is True
   assert parse_location_posts(ended).has_more is False


def test_the_new_posts_check_is_the_upstreams_flag() -> None:
   """Catches the answer read as a constant, and anything but a boolean accepted."""

   answer = recorded("new_feed_posts.json")
   flipped = copy.deepcopy(answer)
   flipped["data"]["xdt_api__v1__new_feed_posts_exist"]["new_feed_posts_exist"] = True
   not_a_flag = copy.deepcopy(answer)
   not_a_flag["data"]["xdt_api__v1__new_feed_posts_exist"]["new_feed_posts_exist"] = "false"

   assert parse_new_feed_posts(answer) is False
   assert parse_new_feed_posts(flipped) is True

   with pytest.raises(SchemaChanged):
      parse_new_feed_posts(not_a_flag)


@pytest.mark.asyncio
async def test_the_four_reads_send_what_the_replays_sent() -> None:
   """The parity gate for the discovery reads. Catches another path or query, another variable or
   parameter, another referer, the explore grid's header set, and a root field header on a query
   whose path does not carry one."""

   transport = ScriptedTransport(
      [
         json_response(recorded("explore_grid.json")),
         json_response(recorded("location_info.json")),
         json_response(recorded("location_posts.json")),
         json_response(recorded("new_feed_posts.json")),
      ]
   )
   sender = make_paced(transport)
   session = a_bootstrapped_session()
   place_page = f"https://www.instagram.com/explore/locations/{location_id()}/"

   await read_explore_grid(sender, session)
   await read_location_info(sender, session, location_id())
   await read_location_posts(sender, session, location_id())
   await read_new_feed_posts(sender, session)

   explore, place, posts, new_posts = transport.sent

   assert (explore.method, explore.url, explore.content) == ("GET", EXPLORE_URL, None)
   assert dict(explore.params) == {
      "include_fixed_destinations": "true",
      "is_nonpersonalized_explore": "false",
      "is_prefetch": "false",
      "module": "explore_popular",
      "omit_cover_media": "false",
   }
   assert set(explore.headers) == READ_HEADERS
   assert explore.headers["referer"] == EXPLORE_PAGE
   assert [request.url for request in (place, posts, new_posts)] == [
      API_GRAPHQL,
      GRAPHQL_QUERY,
      API_GRAPHQL,
   ]
   assert [sent_field(request, "doc_id") for request in (place, posts, new_posts)] == [
      LOCATION_INFO_DOC_ID,
      LOCATION_POSTS_DOC_ID,
      NEW_FEED_POSTS_DOC_ID,
   ]
   assert sent_variables(place) == {"location_id_str": location_id(), "show_nearby": False}
   assert sent_variables(posts) == {
      "location_id": location_id(),
      "first": 12,
      "after": None,
      "tab": "ranked",
      "page_size_override": None,
      SHORT_DRAMA: False,
   }
   assert sent_variables(new_posts) == {}
   assert posts.headers["x-root-field-name"] == TAB_ROOT
   assert "x-root-field-name" not in place.headers
   assert "x-root-field-name" not in new_posts.headers
   assert place.headers["referer"] == place_page
   assert posts.headers["referer"] == place_page
   assert new_posts.headers["referer"] == SITE_ROOT


@pytest.mark.asyncio
async def test_a_name_or_an_unobserved_tab_is_refused_before_anything_is_sent() -> None:
   """Catches a place identifier or a tab reaching the request unchecked."""

   transport = ScriptedTransport([])
   sender = make_paced(transport)
   session = a_bootstrapped_session()

   with pytest.raises(ValueError, match="numeric place id"):
      await read_location_info(sender, session, "somewhere")

   with pytest.raises(ValueError, match="numeric place id"):
      await read_location_posts(sender, session, f"{location_id()}x")

   with pytest.raises(ValueError, match="recent"):
      await read_location_posts(sender, session, location_id(), tab="recent")  # type: ignore[arg-type]

   assert transport.sent == []


def paced(transport: ScriptedTransport, client: AsyncClient) -> PacedSender:
   clock = FakeClock()
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)

   return PacedSender(transport, pacer, client._sender.pacing, client._sender.writes)


def friendly_names(requests: list[Any]) -> list[str]:
   return [
      sent_field(request, "fb_api_req_friendly_name") for request in requests if request.content
   ]


@pytest.mark.asyncio
async def test_each_feeds_read_sends_its_one_request_and_nothing_pages_a_places_grid() -> None:
   """The W79 gate. Catches a feeds method sending more than its one request, the grid's next
   page query sent or registered anywhere a later change could send it from, and ``location``
   growing a cursor."""

   transport = ScriptedTransport(
      [
         json_response(recorded("explore_grid.json")),
         json_response(recorded("location_info.json")),
         json_response(recorded("location_posts.json")),
         json_response(recorded("new_feed_posts.json")),
      ]
   )
   client = AsyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR)
   await client._sender.aclose()
   client._sender = paced(transport, client)

   try:
      grid = await client.feeds.explore()
      place = await client.feeds.place(location_id())
      posts = await client.feeds.location(location_id(), tab=LocationTab.RANKED)
      has_new_posts = await client.feeds.has_new_posts()
   finally:
      await client.aclose()

   registered = {
      query.friendly_name for query in (*READ_QUERIES, *COMPANION_QUERIES, *WRITE_QUERIES)
   }

   assert len(grid.posts) == 5
   assert place.id == location_id()
   assert posts.has_more is True
   assert has_new_posts is False
   assert len(transport.sent) == 4
   assert transport.sent[0].url == EXPLORE_URL
   assert friendly_names(transport.sent) == [
      "PolarisExploreLocationsContainerQuery",
      "PolarisLocationPageTabContentQuery",
      "PolarisAPICheckNewFeedPostsExistQuery",
   ]
   assert NEXT_PAGE_NAME not in registered
   assert not hasattr(client.feeds, "iter_location")


def test_the_blocking_feeds_reads_answer_as_their_async_twins() -> None:
   """The same four reads on the blocking surface, each on the loop thread."""

   transport = ScriptedTransport(
      [
         json_response(recorded("new_feed_posts.json")),
         json_response(recorded("location_posts.json")),
         json_response(recorded("location_info.json")),
         json_response(recorded("explore_carousel.json")),
      ]
   )

   with SyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR) as client:
      client._loop.run(client._impl._sender.aclose(), operation="the scripted sender swap")
      client._impl._sender = paced(transport, client._impl)
      has_new_posts = client.feeds.has_new_posts()
      posts = client.feeds.location(location_id())
      place = client.feeds.place(location_id())
      grid = client.feeds.explore()

   assert has_new_posts is False
   assert len(posts.posts) == 4
   assert (
      place.name
      == recorded("location_info.json")["data"]["xdt_location_get_web_info"][
         "native_location_data"
      ]["location_info"]["name"]
   )
   assert [post.media_type for post in grid.posts] == [2, 8]
   assert transport.sent[-1].url == EXPLORE_URL


class FakeFeeds:
   def __init__(self) -> None:
      self.asked: list[tuple[str, str]] = []

   def explore(self) -> ExploreGrid:
      self.asked.append(("explore", ""))

      return parse_explore_grid(recorded("explore_grid.json"))

   def place(self, location_id: str) -> Place:
      self.asked.append(("place", location_id))

      return parse_location_info(recorded("location_info.json"))

   def location(self, location_id: str) -> LocationPosts:
      self.asked.append(("location", location_id))

      return parse_location_posts(recorded("location_posts.json"))

   def has_new_posts(self) -> bool:
      self.asked.append(("new-posts", ""))

      return True


class FakeFeedsClient:
   def __init__(self) -> None:
      self.session = Session(sessionid="s", ds_user_id="1234567890", csrftoken="c")
      self.feeds = FakeFeeds()
      self.closed = False

   def close(self) -> None:
      self.closed = True


def run_command(argv: list[str], client: FakeFeedsClient) -> tuple[int, str]:
   out = io.StringIO()

   def factory(path: Path, *, user_agent: str | None = None) -> Any:
      return client

   try:
      code = main(
         ["--session", "unused.json", *argv],
         environment={},
         client_factory=factory,
         stdout=out,
         stderr=io.StringIO(),
      )
   except SystemExit as exited:
      code = int(exited.code or 0)

   return code, out.getvalue()


def test_dumpsta_explore_place_location_and_new_posts_print_everything_read() -> None:
   """Catches a post or a section left out of either form, a featured post counted as another,
   the more flags dropped, the place's fields cut short, and the new posts flag inverted."""

   explore_client = FakeFeedsClient()
   _, explore_out = run_command(["--json", "explore"], explore_client)
   _, explore_text = run_command(["explore"], FakeFeedsClient())
   place_client = FakeFeedsClient()
   _, place_out = run_command(["--json", "place", location_id()], place_client)
   location_client = FakeFeedsClient()
   _, location_out = run_command(["--json", "location", location_id()], location_client)
   _, location_text = run_command(["location", location_id()], FakeFeedsClient())
   _, new_posts_out = run_command(["--json", "new-posts"], FakeFeedsClient())
   _, new_posts_text = run_command(["new-posts"], FakeFeedsClient())

   explore = json.loads(explore_out)
   place = json.loads(place_out)
   location = json.loads(location_out)
   info = recorded("location_info.json")["data"]["xdt_location_get_web_info"][
      "native_location_data"
   ]["location_info"]

   assert (explore["section_count"], explore["post_count"]) == (1, 5)
   assert len(explore["sections"][0]["featured"]) == 1
   assert len(explore["sections"][0]["posts"]) == 4
   assert explore["more_available"] is True
   assert explore_text.strip().splitlines()[-1] == "sections: 1  posts: 5  more_available: True"
   assert place_client.feeds.asked == [("place", location_id())]
   assert place["place"]["name"] == info["name"]
   assert place["place"]["media_count"] == info["media_count"]
   assert location_client.feeds.asked == [("location", location_id())]
   assert location["post_count"] == 4
   assert [post["pk"] for post in location["posts"]] == [node["pk"] for node in grid_nodes()]
   assert location["more_available"] is True
   assert location_text.strip().splitlines()[-1] == "posts: 4  more_available: True"
   assert [line.split()[0] for line in location_text.strip().splitlines()[:-1]] == [
      node["code"] for node in grid_nodes()
   ]
   assert json.loads(new_posts_out)["new_posts"] is True
   assert new_posts_text.strip() == "new_posts: True"
   assert explore_client.closed
   assert location_client.closed


def test_dumpsta_place_and_location_refuse_a_name() -> None:
   """Catches a place name or slug passed on as a place id."""

   client = FakeFeedsClient()
   place_refused, _ = run_command(["place", "somewhere"], client)
   location_refused, _ = run_command(["location", "somewhere"], client)

   assert (place_refused, location_refused) == (2, 2)
   assert client.feeds.asked == []
