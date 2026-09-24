"""Gates on the single post read, like and unlike, the Step 15 table in the build plan.

Five defect classes live here.

The write can name the post by the wrong identifier. A post carries its ``pk`` and an ``id`` of
the form ``<pk>_<author id>``, the mutations were observed taking the ``pk``, and nothing
records what they do with the other one.

Like and unlike can be crossed, since they share an input and differ only in their document.

The read can report the wrong like state, which is the one thing a like is confirmed by.

A write can leave by a path other than ``send_write``, which is where the budget, the stop and
the once-only token are enforced, or can be sent again after an error answer.

And the request can drift from the one the engine replayed live, which is the parity gate for
this step. A browser sends more around a like and a post read, a burst nobody has recorded
because ruling 23 allowed no browser load, so the gate holds the one request's shape.

Every response is canned. Nothing in this file touches the network.
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import pytest

from dumpstagram._cli.main import main
from dumpstagram._core.pacer import PacingPolicy, WritePolicy
from dumpstagram._core.posts import read_post
from dumpstagram._core.writes.likes import like_post, unlike_post
from dumpstagram._private.transport import Request
from dumpstagram._private.web.parse.media import parse_post_detail
from dumpstagram.errors import SchemaChanged, UpstreamRejected
from dumpstagram.models import MediaImage, PostAuthor, PostDetail
from dumpstagram.session import Session
from tests.test_direct import (
   ScriptedTransport,
   a_bootstrapped_session,
   json_response,
   make_paced,
   sent_variables,
)
from tests.test_feed import AUTHOR_ID, MEDIA_ID, MEDIA_PK, media

API_GRAPHQL = "https://www.instagram.com/api/graphql"
HOME = "https://www.instagram.com/"
CODE = "Cxxxxxxxxxx"

LIKE_DOC_ID = "27182485238052618"
UNLIKE_DOC_ID = "27345296031770102"
POST_DOC_ID = "27830990013244856"


def post_item(**overrides: Any) -> dict[str, Any]:
   """The feed media node's key set without ``is_seen``, which the post read does not carry,
   as measured on four live reads on 2026-09-23. Synthetic values."""

   built = media(**overrides)
   del built["is_seen"]

   return built


def post_payload(items: list[dict[str, Any]]) -> dict[str, Any]:
   return {
      "data": {"xdt_api__v1__media__shortcode__web_info": {"items": items}},
      "extensions": {"is_final": True},
   }


def write_answer(root_field: str, *, has_liked: bool) -> dict[str, Any]:
   """The 217 and 220 byte answers observed on 2026-09-23, media echoed in the id form."""

   return {
      "data": {root_field: {"media": {"id": MEDIA_ID, "has_liked": has_liked}}},
      "extensions": {"is_final": True},
   }


def body_of(request: Request) -> dict[str, list[str]]:
   return parse_qs(request.content.decode("utf-8")) if request.content else {}


def test_the_post_read_maps_has_liked_and_like_count_from_the_item() -> None:
   """Catches ``has_liked`` defaulted rather than read, which reports every like as missing."""

   post = parse_post_detail(post_payload([post_item(has_liked=True, like_count=6)]))

   assert post == PostDetail(
      id=MEDIA_ID,
      pk=MEDIA_PK,
      code=CODE,
      taken_at=datetime.fromtimestamp(1789902875, tz=UTC),
      author=post.author,
      media_type=8,
      product_type="carousel_container",
      like_count=6,
      comment_count=3,
      has_liked=True,
      caption="a caption",
      accessibility_caption="a description",
      original_width=1440,
      original_height=1800,
      carousel_media_count=4,
      images=(
         MediaImage(url="https://example.invalid/1024.jpg", width=1024, height=1280),
         MediaImage(url="https://example.invalid/640.jpg", width=640, height=800),
      ),
   )
   assert isinstance(post.author, PostAuthor)
   assert post.author.id == AUTHOR_ID


def test_a_post_read_without_exactly_one_item_is_a_schema_change() -> None:
   """Catches an empty or doubled item list read as some post anyway."""

   with pytest.raises(SchemaChanged):
      parse_post_detail(post_payload([]))

   with pytest.raises(SchemaChanged):
      parse_post_detail(post_payload([post_item(), post_item()]))


@pytest.mark.asyncio
async def test_the_post_read_sends_the_request_the_engine_replayed() -> None:
   """The parity gate for the read. Catches the query sent with other variables, another
   referer or path, or beside a request nothing recorded."""

   transport = ScriptedTransport([json_response(post_payload([post_item()]))])

   post = await read_post(make_paced(transport), a_bootstrapped_session(), CODE)

   assert len(transport.sent) == 1

   request = transport.sent[0]
   body = body_of(request)

   assert request.url == API_GRAPHQL
   assert body["doc_id"] == [POST_DOC_ID]
   assert body["fb_api_req_friendly_name"] == ["PolarisPostRootQuery"]
   assert sent_variables(request) == {
      "shortcode": CODE,
      "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": False,
      "__relay_internal__pv__PolarisMultiCaptionCarouselEnabledrelayprovider": True,
   }
   assert request.headers["referer"] == f"https://www.instagram.com/p/{CODE}/"
   assert post.pk == MEDIA_PK


@pytest.mark.asyncio
@pytest.mark.parametrize(
   ("write", "doc_id", "friendly_name", "root_field", "has_liked"),
   [
      (like_post, LIKE_DOC_ID, "usePolarisLikeMediaXIGLikeMutation", "xig_media_like", True),
      (
         unlike_post,
         UNLIKE_DOC_ID,
         "usePolarisLikeMediaXIGUnlikeMutation",
         "xig_media_unlike",
         False,
      ),
   ],
)
async def test_each_write_sends_the_request_the_engine_replayed(
   write: Any, doc_id: str, friendly_name: str, root_field: str, has_liked: bool
) -> None:
   """The parity gate for the writes, and the gate that like and unlike send different
   documents. Catches the pk swapped for the id form, a crossed document, a variable no send
   carried, and a request going out beside the write."""

   transport = ScriptedTransport([json_response(write_answer(root_field, has_liked=has_liked))])

   await write(make_paced(transport), a_bootstrapped_session(), MEDIA_PK)

   assert len(transport.sent) == 1

   request = transport.sent[0]
   body = body_of(request)

   assert request.url == API_GRAPHQL
   assert body["doc_id"] == [doc_id]
   assert body["fb_api_req_friendly_name"] == [friendly_name]
   assert request.headers["x-fb-friendly-name"] == friendly_name
   assert sent_variables(request) == {
      "input": {"client_mutation_id": "1", "media_id": MEDIA_PK, "tracking_token": None}
   }
   assert request.headers["referer"] == HOME


@pytest.mark.asyncio
@pytest.mark.parametrize("write", [like_post, unlike_post])
async def test_the_id_form_is_refused_before_anything_is_sent(write: Any) -> None:
   """Catches ``Post.id`` passed through to the upstream, whose answer to it is unobserved."""

   transport = ScriptedTransport([])

   with pytest.raises(ValueError):
      await write(make_paced(transport), a_bootstrapped_session(), MEDIA_ID)

   assert transport.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
   ("write", "root_field", "has_liked"),
   [(like_post, "xig_media_like", True), (unlike_post, "xig_media_unlike", False)],
)
async def test_both_writes_depart_only_through_the_write_slot(
   write: Any, root_field: str, has_liked: bool
) -> None:
   """Catches a write sent with ``sender.send`` rather than ``send_write``. On an account whose
   writes are stopped the write slot refuses before the transport sees anything, and an
   ordinary send does not."""

   transport = ScriptedTransport([json_response(write_answer(root_field, has_liked=has_liked))])
   sender = make_paced(transport)
   sender.pacer.stop_writes()

   with pytest.raises(UpstreamRejected):
      await write(sender, a_bootstrapped_session(), MEDIA_PK)

   assert transport.sent == []


@pytest.mark.asyncio
async def test_an_error_envelope_on_a_like_raises_and_departs_once() -> None:
   """Catches a like sent again after the upstream answered it with an error. The write stop is
   turned off here, because with it on the pacer would refuse the second send and hide a
   capability that retries."""

   envelope = {"error": "a_code_no_finding_explains"}
   transport = ScriptedTransport([json_response(envelope), json_response(envelope)])
   sender = make_paced(transport).with_pacing(
      PacingPolicy(), WritePolicy(stop_after_unrecognised_rejection=False)
   )

   with pytest.raises(UpstreamRejected):
      await like_post(sender, a_bootstrapped_session(), MEDIA_PK)

   assert len(transport.sent) == 1


@pytest.mark.asyncio
async def test_an_answer_naming_the_other_state_is_not_taken_as_applied() -> None:
   """Catches a like reported as done when the upstream's own answer says it is not liked."""

   answer = write_answer("xig_media_like", has_liked=False)
   transport = ScriptedTransport([json_response(answer)])

   with pytest.raises(UpstreamRejected):
      await like_post(make_paced(transport), a_bootstrapped_session(), MEDIA_PK)


class RecordingClient:
   def __init__(self) -> None:
      self.session = Session(sessionid="s", ds_user_id="1234567890", csrftoken="c")
      self.calls: list[tuple[str, str]] = []

   def like(self, post_pk: str) -> None:
      self.calls.append(("like", post_pk))

   def unlike(self, post_pk: str) -> None:
      self.calls.append(("unlike", post_pk))

   def close(self) -> None:
      pass


def run_cli(argv: list[str], client: RecordingClient) -> tuple[int, str]:
   out = io.StringIO()
   factories: list[Path] = []

   def factory(path: Path, *, user_agent: str | None = None) -> Any:
      factories.append(path)

      return client

   code = main(argv, environment={}, client_factory=factory, stdout=out, stderr=io.StringIO())

   return code, out.getvalue()


@pytest.mark.parametrize("verb", ["like", "unlike"])
def test_the_cli_sends_the_named_post_to_the_named_write(verb: str) -> None:
   """Catches the CLI crossing like and unlike, or writing to anything but the pk it was given."""

   client = RecordingClient()

   code, out = run_cli(["--json", "--session", "s.json", verb, MEDIA_PK], client)

   assert code == 0
   assert client.calls == [(verb, MEDIA_PK)]
   assert json.loads(out)["has_liked"] is (verb == "like")


def test_the_cli_refuses_the_id_form_before_opening_a_client() -> None:
   """Catches the id form reaching a client, where it would become a live request."""

   client = RecordingClient()

   with pytest.raises(SystemExit) as raised:
      run_cli(["--session", "s.json", "like", MEDIA_ID], client)

   assert raised.value.code == 2
   assert client.calls == []
