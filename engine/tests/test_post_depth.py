"""Gates on E2 batch 4, post depth: the replies under a comment, the likers, a post read by its
media pk, the more posts from its author, and the location, tags and collaborators a post
carries.

Five defect classes live here.

A reply page can be read from the wrong place or ended on the wrong signal. The upstream decides
a page's length, 9 and then 11 replies for the same ``first``, so only ``has_next_page`` ends a
walk, and the first and later pages are two queries with two page sizes.

A reply is a comment node with a null ``child_comment_count``, so a mapper can refuse every reply
by reading it as the comment page does, or report a count nobody sent.

A read can leave out what its answer carries, or fill in what it does not. The post read by media
pk carries no slide kinds, no image description, no high resolution author picture and no
collaborators, and a gap must read as empty or ``None`` rather than as a guess, while every other
post read keeps refusing what it always refused.

A new field can collapse "none" into "not carried": a null ``usertags`` is no tags, an absent one
is unknown. And a tag can be read by a key some tags lack.

And a command can take a shortcode where a pk is meant, or stop on the wrong terminator.

The payloads are the recorded answers of 2026-09-27, pseudonymised by
``scripts/build_post_depth_fixtures.py``. Nothing in this file touches the network.
"""

from __future__ import annotations

import copy
import io
import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import pytest

from dumpstagram._cli.main import main
from dumpstagram._core.comments import read_replies_page
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.posts import read_likers, read_more_from_author, read_post_by_id
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse.feed import parse_feed_page
from dumpstagram._private.web.parse.media import (
   parse_likers,
   parse_more_from_author,
   parse_post_by_media_id,
   parse_post_detail,
   parse_reply_page,
)
from dumpstagram._private.web.parse.profiles import parse_profile_posts_page
from dumpstagram._private.web.requests.media import build_replies_request
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY
from dumpstagram.client import SyncClient
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import (
   Comment,
   Page,
   Post,
   PostDetail,
   PostThumbnail,
   ProfileSummary,
)
from dumpstagram.session import Session
from tests.test_direct import (
   FakeClock,
   ScriptedTransport,
   a_bootstrapped_session,
   json_response,
   make_paced,
   sent_variables,
)
from tests.test_likes import post_item, post_payload

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "post_depth"
PROFILE_TAB_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "profile_tabs"

GRAPHQL_QUERY = "https://www.instagram.com/graphql/query"
API_GRAPHQL = "https://www.instagram.com/api/graphql"
SITE_ROOT = "https://www.instagram.com/"
REPLIES_ROOT = (
   "xdt_api__v1__media__media_id__comments__parent_comment_id__child_comments__connection"
)
HOME_ROOT = "xdt_api__v1__feed__timeline__connection"
BY_ID_ROOT = "xdt_api__v1__media__media_id_web_info"
STRIP_ROOT = "xdt_api__v1__profile_timeline"
REPLIES_DOC_ID = "28027289793632076"
REPLIES_NEXT_PAGE_DOC_ID = "27229753410037873"
LIKERS_DOC_ID = "27928626103504365"
BY_ID_DOC_ID = "28007559615590940"
STRIP_DOC_ID = "27764946129846908"
POST_PK = "3456789012345678901"
COMMENT_ID = "17890123456789012"
AUTHOR_ID = "81234567"

SCRIPTED_BEHAVIOR = replace(PARITY, cookie_sync=False)


def recorded(name: str) -> Any:
   return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def reply_nodes(name: str) -> list[dict[str, Any]]:
   return [edge["node"] for edge in recorded(name)["data"][REPLIES_ROOT]["edges"]]


def reply_page_info(name: str) -> dict[str, Any]:
   page_info: dict[str, Any] = recorded(name)["data"][REPLIES_ROOT]["page_info"]

   return page_info


def by_id_item() -> dict[str, Any]:
   item: dict[str, Any] = recorded("post_by_media_id.json")["data"][BY_ID_ROOT]["items"][0]

   return item


def home_media() -> list[dict[str, Any]]:
   return [
      edge["node"]["media"]
      for edge in recorded("home_timeline_posts.json")["data"][HOME_ROOT]["edges"]
   ]


def sent_field(request: Any, name: str) -> str:
   return parse_qs(request.content.decode("utf-8"))[name][0]


def test_a_reply_page_maps_every_reply_in_order_with_its_own_terminator() -> None:
   """Catches replies dropped or reordered, and a page's flag or cursor read from anywhere but
   its ``page_info``. One recorded comment's replies fit a page, another's did not."""

   whole = parse_reply_page(recorded("replies_whole.json"))
   first = parse_reply_page(recorded("replies_first_page.json"))

   assert [reply.id for reply in whole.items] == [
      node["pk"] for node in reply_nodes("replies_whole.json")
   ]
   assert len(whole.items) == 9
   assert whole.has_next_page is False
   assert whole.end_cursor is None
   assert [reply.id for reply in first.items] == [
      node["pk"] for node in reply_nodes("replies_first_page.json")
   ]
   assert len(first.items) == 11
   assert first.has_next_page is True
   assert first.end_cursor == reply_page_info("replies_first_page.json")["end_cursor"]


def test_a_reply_is_a_comment_with_no_count_of_its_own_read_from_its_own_keys() -> None:
   """Catches every reply refused because its ``child_comment_count`` is null, a count reported
   where none was sent, and a like count or like state read from a neighbouring key."""

   nodes = reply_nodes("replies_next_page.json")
   replies = parse_reply_page(recorded("replies_next_page.json")).items

   assert {node["child_comment_count"] for node in nodes} == {None}
   assert {reply.reply_count for reply in replies} == {None}
   assert [reply.parent_comment_id for reply in replies] == [
      node["parent_comment_id"] for node in nodes
   ]
   assert [reply.like_count for reply in replies] == [node["comment_like_count"] for node in nodes]
   assert [reply.has_liked for reply in replies] == [node["has_liked_comment"] for node in nodes]
   assert [reply.author.id for reply in replies] == [node["user"]["pk"] for node in nodes]
   assert all(isinstance(reply, Comment) for reply in replies)


def test_a_reply_without_its_parent_is_a_schema_change() -> None:
   """Catches a reply that names no parent passed on as a comment on the post itself."""

   payload = copy.deepcopy(recorded("replies_whole.json"))
   del payload["data"][REPLIES_ROOT]["edges"][0]["node"]["parent_comment_id"]

   with pytest.raises(SchemaChanged):
      parse_reply_page(payload)


def test_the_first_reply_page_sends_the_variables_replayed_live() -> None:
   """The parity gate for the first page. Catches the next page query sent first, another page
   size, a dropped provider, or the variables of the comment page."""

   request = build_replies_request(a_bootstrapped_session(), POST_PK, COMMENT_ID)

   assert request.url == API_GRAPHQL
   assert sent_field(request, "doc_id") == REPLIES_DOC_ID
   assert sent_field(request, "fb_api_req_friendly_name") == "PolarisPostChildCommentsQuery"
   assert request.headers["referer"] == SITE_ROOT
   assert "x-root-field-name" not in request.headers
   assert sent_variables(request) == {
      "after": None,
      "before": None,
      "media_id": POST_PK,
      "parent_comment_id": COMMENT_ID,
      "is_chronological": True,
      "first": 3,
      "last": None,
      "__relay_internal__pv__PolarisIsLoggedInrelayprovider": True,
   }


def test_a_later_reply_page_is_the_pagination_query_on_the_cursor() -> None:
   """The parity gate for the next page. Catches the first page query sent again with a cursor,
   and the first page's size kept."""

   request = build_replies_request(a_bootstrapped_session(), POST_PK, COMMENT_ID, after="C0001cc")

   assert request.url == API_GRAPHQL
   assert sent_field(request, "doc_id") == REPLIES_NEXT_PAGE_DOC_ID
   assert (
      sent_field(request, "fb_api_req_friendly_name")
      == "PolarisPostCommentsChildrenPaginationtQuery"
   )
   assert sent_variables(request) == {
      "after": "C0001cc",
      "before": None,
      "media_id": POST_PK,
      "parent_comment_id": COMMENT_ID,
      "is_chronological": True,
      "first": 10,
      "last": None,
      "__relay_internal__pv__PolarisIsLoggedInrelayprovider": True,
   }


@pytest.mark.asyncio
async def test_replies_refuse_the_id_form_and_a_comment_id_that_is_not_digits() -> None:
   """Catches an identifier reaching the request unchecked."""

   transport = ScriptedTransport([])
   sender = make_paced(transport)
   session = a_bootstrapped_session()

   with pytest.raises(ValueError, match="media pk"):
      await read_replies_page(sender, session, f"{POST_PK}_{AUTHOR_ID}", COMMENT_ID)

   with pytest.raises(ValueError, match="comment id"):
      await read_replies_page(sender, session, POST_PK, "not-a-comment")

   assert transport.sent == []


def paced(transport: ScriptedTransport, client: AsyncClient) -> PacedSender:
   clock = FakeClock()
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)

   return PacedSender(transport, pacer, client._sender.pacing, client._sender.writes)


def two_reply_pages() -> ScriptedTransport:
   return ScriptedTransport(
      [
         json_response(recorded("replies_first_page.json")),
         json_response(recorded("replies_next_page.json")),
      ]
   )


def friendly_names(transport: ScriptedTransport) -> list[str]:
   return [sent_field(request, "fb_api_req_friendly_name") for request in transport.sent]


@pytest.mark.asyncio
async def test_the_async_reply_walk_crosses_to_the_next_page_query_on_the_first_pages_cursor() -> (
   None
):
   """Catches a walk that asks the first page query again for page two, passes another cursor,
   or stops at the end of the first page."""

   transport = two_reply_pages()
   client = AsyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR)
   await client._sender.aclose()
   client._sender = paced(transport, client)

   try:
      replies = [reply async for reply in client.media.iter_replies(POST_PK, COMMENT_ID, limit=20)]
   finally:
      await client.aclose()

   assert len(replies) == 20
   assert friendly_names(transport) == [
      "PolarisPostChildCommentsQuery",
      "PolarisPostCommentsChildrenPaginationtQuery",
   ]
   assert (
      sent_variables(transport.sent[1])["after"]
      == reply_page_info("replies_first_page.json")["end_cursor"]
   )


def test_the_blocking_reply_walk_crosses_to_the_next_page_query() -> None:
   """The same walk on the blocking surface, each page read on the loop thread."""

   transport = two_reply_pages()

   with SyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR) as client:
      client._loop.run(client._impl._sender.aclose(), operation="the scripted sender swap")
      client._impl._sender = paced(transport, client._impl)
      replies = list(client.media.iter_replies(POST_PK, COMMENT_ID, limit=12))

   assert len(replies) == 12
   assert friendly_names(transport)[1] == "PolarisPostCommentsChildrenPaginationtQuery"
   assert sent_variables(transport.sent[1])["parent_comment_id"] == COMMENT_ID


def test_likers_are_list_rows_in_the_upstream_order_with_every_flag_they_carry() -> None:
   """Catches rows dropped or reordered, an id read from anything but ``pk``, a privacy flag
   reported that no liker carries, and the two flags only some lists send left out."""

   nodes = recorded("likers.json")["data"]["fetch__XDTMediaDict"]["likers_connection"]["nodes"]
   likers = parse_likers(recorded("likers.json"))

   assert len(likers) == 98
   assert [account.id for account in likers] == [node["pk"] for node in nodes]
   assert [account.username for account in likers] == [node["username"] for node in nodes]
   assert {account.is_private for account in likers} == {None}
   assert all(account.friendship_status is not None for account in likers)
   assert [
      account.friendship_status.followed_by for account in likers if account.friendship_status
   ] == [node["friendship_status"]["followed_by"] for node in nodes]
   assert [
      account.friendship_status.blocking for account in likers if account.friendship_status
   ] == [node["friendship_status"]["blocking"] for node in nodes]


@pytest.mark.asyncio
async def test_the_likers_and_the_strip_send_the_variables_replayed_live() -> None:
   """The parity gate for the likers and the strip. Catches the id form sent as the media,
   another path, a post sent to the strip, another count, or a username accepted as an author."""

   transport = ScriptedTransport(
      [
         json_response(recorded("likers.json")),
         json_response(recorded("more_from_author.json")),
      ]
   )
   sender = make_paced(transport)
   session = a_bootstrapped_session()

   likers = await read_likers(sender, session, POST_PK)
   strip = await read_more_from_author(sender, session, AUTHOR_ID)

   assert all(isinstance(account, ProfileSummary) for account in likers)
   assert all(isinstance(thumbnail, PostThumbnail) for thumbnail in strip)
   assert [request.url for request in transport.sent] == [API_GRAPHQL, GRAPHQL_QUERY]
   assert [sent_field(request, "doc_id") for request in transport.sent] == [
      LIKERS_DOC_ID,
      STRIP_DOC_ID,
   ]
   assert sent_variables(transport.sent[0]) == {"media_id": POST_PK}
   assert sent_variables(transport.sent[1]) == {
      "media_owner_id": AUTHOR_ID,
      "count": 6,
      "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": False,
   }
   assert transport.sent[1].headers["x-root-field-name"] == STRIP_ROOT
   assert {request.headers["referer"] for request in transport.sent} == {SITE_ROOT}

   with pytest.raises(ValueError, match="numeric account id"):
      await read_more_from_author(sender, session, "someone")

   with pytest.raises(ValueError, match="media pk"):
      await read_likers(sender, session, f"{POST_PK}_{AUTHOR_ID}")

   assert len(transport.sent) == 2


def test_the_strip_maps_each_post_as_a_thumbnail_from_its_own_keys() -> None:
   """Catches posts dropped or reordered, the author read from the wrong object, the like count
   read from the comment count, and a carousel's slide count lost."""

   items = recorded("more_from_author.json")["data"][STRIP_ROOT]["profile_grid_items"]
   media = [item["media"] for item in items]
   strip = parse_more_from_author(recorded("more_from_author.json"))

   assert len(strip) == 6
   assert [thumbnail.pk for thumbnail in strip] == [node["pk"] for node in media]
   assert [thumbnail.code for thumbnail in strip] == [node["code"] for node in media]
   assert [thumbnail.author_id for thumbnail in strip] == [node["user"]["pk"] for node in media]
   assert [thumbnail.author_username for thumbnail in strip] == [
      node["user"]["username"] for node in media
   ]
   assert [thumbnail.carousel_media_count for thumbnail in strip] == [
      node["carousel_media_count"] for node in media
   ]
   assert [thumbnail.product_type for thumbnail in strip] == [
      node["product_type"] for node in media
   ]
   assert [len(thumbnail.images) for thumbnail in strip] == [
      len(node["image_versions2"]["candidates"]) for node in media
   ]


def test_a_post_read_by_media_pk_leaves_empty_what_its_item_does_not_carry() -> None:
   """Catches a slide invented without its kind, an image description or collaborators reported
   as none when the item never carried them, and the tags this item does carry dropped."""

   item = by_id_item()
   post = parse_post_by_media_id(recorded("post_by_media_id.json"))

   assert isinstance(post, PostDetail)
   assert post.pk == item["pk"]
   assert post.code == item["code"]
   assert post.author.id == item["user"]["id"]
   assert post.author.hd_profile_pic_url is None
   assert post.carousel_media_count == len(item["carousel_media"]) == 3
   assert post.carousel_children == ()
   assert "accessibility_caption" not in item
   assert post.accessibility_caption is None
   assert "coauthor_producers" not in item
   assert post.collaborators is None
   assert post.location is None
   assert post.user_tags is not None
   assert [tag.account.id for tag in post.user_tags] == [
      tag["user"]["id"] for tag in item["usertags"]["in"]
   ]
   assert {tag.position for tag in post.user_tags} == {None}


def test_the_partial_post_by_media_pk_answer_is_returned_through_the_classifier() -> None:
   """Catches the first answer of 2026-09-27, whole beside twelve field errors, refused, and a
   mapper that reads a field the errors null out."""

   payload = recorded("post_by_media_id_partial.json")
   post = parse_post_by_media_id(classify(json_response(payload)))

   assert len(payload["errors"]) == 12
   assert post.pk == payload["data"][BY_ID_ROOT]["items"][0]["pk"]


@pytest.mark.asyncio
async def test_a_post_read_by_media_pk_is_the_media_id_query_on_its_own_path() -> None:
   """The parity gate for the read. Catches the variable in another case, another path, or the
   root field header left off a query on the graphql/query path."""

   transport = ScriptedTransport([json_response(recorded("post_by_media_id.json"))])

   post = await read_post_by_id(make_paced(transport), a_bootstrapped_session(), POST_PK)

   assert isinstance(post, PostDetail)
   assert transport.sent[0].url == GRAPHQL_QUERY
   assert sent_field(transport.sent[0], "doc_id") == BY_ID_DOC_ID
   assert transport.sent[0].headers["x-root-field-name"] == BY_ID_ROOT
   assert sent_variables(transport.sent[0]) == {"mediaId": POST_PK}


def test_a_reel_read_by_media_pk_maps_and_an_original_sound_without_its_flag_is_unknown() -> None:
   """Catches ``by_id`` refusing a reel, as it did live on 2026-09-27, because the item's original
   sound carries no ``is_explicit``, and a guessed flag filled in instead. The reel with no track
   still maps its video, and the shortcode read keeps refusing the same slot."""

   silent = recorded("post_by_media_id_reel.json")
   sounded = recorded("post_by_media_id_reel_original_sound.json")
   sounded_item = sounded["data"][BY_ID_ROOT]["items"][0]
   original_sound = sounded_item["clips_metadata"]["original_sound_info"]

   silent_post = parse_post_by_media_id(silent)
   sounded_post = parse_post_by_media_id(sounded)

   assert "is_explicit" not in original_sound
   assert original_sound["audio_asset_id"]
   assert sounded_post.audio is None
   assert silent_post.audio is None
   assert [post.media_type for post in (silent_post, sounded_post)] == [2, 2]
   assert all(
      post.videos and post.video_duration is not None for post in (silent_post, sounded_post)
   )
   assert len(sounded_post.videos) == len(sounded_item["video_versions"])

   strict_item = copy.deepcopy(sounded_item)
   strict_item["accessibility_caption"] = None
   strict_item["user"]["hd_profile_pic_url_info"] = None

   with pytest.raises(SchemaChanged, match="is_explicit"):
      parse_post_detail(post_payload([strict_item]))


def test_a_post_read_by_shortcode_still_refuses_an_author_without_the_picture_key() -> None:
   """Catches the leniency the media pk read needs leaking into the reads that always carried
   the author's high resolution picture."""

   item = post_item()
   del item["user"]["hd_profile_pic_url_info"]

   with pytest.raises(SchemaChanged):
      parse_post_detail(post_payload([item]))


def test_a_home_post_carries_its_location_tags_and_collaborators_from_their_own_keys() -> None:
   """Catches the three fields dropped from the timeline's post, collaborators read without the
   viewer's relationship, a tag's position lost, and a slide's tag moved onto the post."""

   media = home_media()
   posts = [item.post for item in parse_feed_page(recorded("home_timeline_posts.json")).items]
   shared = next(index for index, node in enumerate(media) if node["coauthor_producers"])
   shared_post = posts[shared]

   assert all(isinstance(post, Post) for post in posts)
   assert [post.location.id if post and post.location else None for post in posts] == [
      node["location"]["pk"] if node["location"] else None for node in media
   ]
   assert shared_post is not None
   assert shared_post.collaborators is not None
   assert [account.id for account in shared_post.collaborators] == [
      producer["pk"] for producer in media[shared]["coauthor_producers"]
   ]
   assert all(account.friendship_status is not None for account in shared_post.collaborators)
   assert shared_post.user_tags is not None
   assert [tag.account.id for tag in shared_post.user_tags] == [
      tag["user"]["id"] for tag in media[shared]["usertags"]["in"]
   ]
   assert [tag.position for tag in shared_post.user_tags] == [
      tuple(tag["position"]) for tag in media[shared]["usertags"]["in"]
   ]
   slide_tags = [
      [tag["user"]["id"] for tag in (slide["usertags"] or {"in": []})["in"]]
      for slide in media[shared]["carousel_media"]
   ]
   assert [
      [tag.account.id for tag in slide.user_tags or ()] for slide in shared_post.carousel_children
   ] == slide_tags
   assert any(slide_tags)


def test_a_tag_is_read_by_its_id_because_some_tags_carry_no_pk() -> None:
   """Catches a tag read by ``pk``, which refuses the whole post on the one tag that lacks it.
   The recorded post's slide tag is such a tag."""

   media = home_media()
   slide_tags = [
      tag
      for node in media
      for slide in node.get("carousel_media") or []
      for tag in (slide.get("usertags") or {"in": []})["in"]
   ]

   assert any("pk" not in tag["user"] for tag in slide_tags)
   assert parse_feed_page(recorded("home_timeline_posts.json")).items


def test_a_null_is_no_tags_or_collaborators_and_an_absent_key_is_unknown() -> None:
   """Catches null and absent collapsed into one answer, which tells a caller a post read by
   media pk has no collaborators when that read never says."""

   null_item = post_item(usertags=None, coauthor_producers=None)
   absent_item = post_item()
   del absent_item["usertags"]
   del absent_item["coauthor_producers"]
   del absent_item["location"]

   with_nulls = parse_post_detail(post_payload([null_item]))
   with_nothing = parse_post_detail(post_payload([absent_item]))

   assert (with_nulls.user_tags, with_nulls.collaborators) == ((), ())
   assert (with_nothing.user_tags, with_nothing.collaborators, with_nothing.location) == (
      None,
      None,
      None,
   )


def test_a_location_pk_sent_as_a_number_reads_as_a_string() -> None:
   """Catches a grid post refused because its location's ``pk`` is a number there and a string
   on the home timeline, and a coordinate read from the wrong key."""

   grid = json.loads((PROFILE_TAB_FIXTURES / "owner_grid_partial.json").read_text("utf-8"))
   nodes = [
      edge["node"]
      for edge in grid["data"]["xdt_api__v1__feed__user_timeline_graphql_connection"]["edges"]
   ]
   posts = parse_profile_posts_page(grid).items
   located = [(post, node) for post, node in zip(posts, nodes, strict=True) if node["location"]]

   assert len(located) == 3
   assert {type(node["location"]["pk"]) for _, node in located} == {int}
   assert [post.location.id for post, _ in located if post.location] == [
      str(node["location"]["pk"]) for _, node in located
   ]

   item = post_item(location={"pk": "123", "name": "a place", "lat": 1.5, "lng": -2.25})
   location = parse_post_detail(post_payload([item])).location

   assert location is not None
   assert (location.id, location.name, location.lat, location.lng) == ("123", "a place", 1.5, -2.25)


class FakeMedia:
   def __init__(self, reply_pages: list[Page[Comment]]) -> None:
      self.reply_pages = reply_pages
      self.cursors: list[str | None] = []
      self.by_id_asked: list[str] = []

   def replies(self, post_pk: str, comment_id: str, *, after: str | None = None) -> Page[Comment]:
      self.cursors.append(after)

      return self.reply_pages[len(self.cursors) - 1]

   def likers(self, post_pk: str) -> tuple[ProfileSummary, ...]:
      return parse_likers(recorded("likers.json"))

   def by_id(self, post_pk: str) -> PostDetail:
      self.by_id_asked.append(post_pk)

      return parse_post_by_media_id(recorded("post_by_media_id.json"))

   def more_from_author(self, author_id: str) -> tuple[PostThumbnail, ...]:
      return parse_more_from_author(recorded("more_from_author.json"))


class FakeMediaClient:
   def __init__(self, reply_pages: list[Page[Comment]]) -> None:
      self.session = Session(sessionid="s", ds_user_id="1234567890", csrftoken="c")
      self.media = FakeMedia(reply_pages)
      self.closed = False

   def post(self, code: str) -> PostDetail:
      raise AssertionError("post --by-id read the post by its shortcode")

   def close(self) -> None:
      self.closed = True


def run_command(argv: list[str], client: FakeMediaClient) -> tuple[int, str, str]:
   out = io.StringIO()
   errors = io.StringIO()

   def factory(path: Path, *, user_agent: str | None = None) -> Any:
      return client

   try:
      code = main(
         ["--session", "unused.json", *argv],
         environment={},
         client_factory=factory,
         stdout=out,
         stderr=errors,
      )
   except SystemExit as exited:
      code = int(exited.code or 0)

   return code, out.getvalue(), errors.getvalue()


def recorded_reply_pages() -> list[Page[Comment]]:
   first = parse_reply_page(recorded("replies_first_page.json"))
   second = parse_reply_page(recorded("replies_next_page.json"))
   last = Page(items=second.items, has_next_page=False, end_cursor=None)

   return [replace(first, end_cursor="k1"), last]


def test_dumpsta_replies_walks_on_the_pages_own_cursor_and_stops_on_its_terminator() -> None:
   """Catches the command passing its first cursor again, or reading past a last page when
   ``--pages`` allows more."""

   client = FakeMediaClient(recorded_reply_pages())

   code, out, _ = run_command(["--json", "replies", POST_PK, COMMENT_ID, "--pages", "5"], client)
   payload = json.loads(out)

   assert code == 0
   assert client.media.cursors == [None, "k1"]
   assert payload["pages_read"] == 2
   assert payload["reply_count"] == 23
   assert payload["more_available"] is False
   assert len(payload["replies"]) == 23
   assert client.closed


def test_dumpsta_post_by_id_reads_by_the_pk_and_refuses_a_shortcode() -> None:
   """Catches ``--by-id`` reading by shortcode, and a shortcode passed on as a pk."""

   client = FakeMediaClient([])

   code, out, _ = run_command(["--json", "post", "--by-id", POST_PK], client)
   refused, _, errors = run_command(["post", "--by-id", "Cxxxxxxxxxx"], FakeMediaClient([]))
   payload = json.loads(out)

   assert code == 0
   assert client.media.by_id_asked == [POST_PK]
   assert payload["by_id"] is True
   assert payload["post"]["collaborators"] is None
   assert refused == 2
   assert "pk" in errors


def test_dumpsta_likers_and_more_from_author_print_every_account_and_post(
   capsys: pytest.CaptureFixture[str],
) -> None:
   """Catches a list cut short in either output form, and a username taken as an author id."""

   _, likers_out, _ = run_command(["--json", "likers", POST_PK], FakeMediaClient([]))
   _, strip_out, _ = run_command(["--json", "more-from-author", AUTHOR_ID], FakeMediaClient([]))
   _, strip_text, _ = run_command(["more-from-author", AUTHOR_ID], FakeMediaClient([]))
   refused, _, _ = run_command(["more-from-author", "someone"], FakeMediaClient([]))

   assert json.loads(likers_out)["account_count"] == 98
   assert len(json.loads(likers_out)["accounts"]) == 98
   assert len(json.loads(strip_out)["posts"]) == 6
   assert strip_text.strip().splitlines()[-1] == "posts: 6"
   assert refused == 2
   assert "numeric id" in capsys.readouterr().err
