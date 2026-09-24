"""Gates on the comment page read, comment and delete_comment, the Step 16 table in the build plan.

Six defect classes live here.

The page can end early. A comment page that is short or empty while ``has_next_page`` is true
is not the last page, and a reader that stops there loses comments without an error.

The created comment can be mapped wrong, most dangerously its author, which is how a caller
tells the viewer's own comment from anyone else's when it reconciles an unknown outcome.

The delete can name the comment without the post. The two engine deletes that worked sent both,
and nothing records what the upstream does with one alone.

A delete answered without an error can still have deleted nothing: a delete naming no comment
was answered with a null root field, and taking that as a success reports a comment gone that
is still up.

A write can leave by a path other than ``send_write``, or be sent again after an error answer,
which for a comment is a duplicate everyone who can see the post sees.

And each request can drift from the one the engine replayed live, which is the parity gate for
this step. A browser sends more around a comment and a comment read, a burst nobody has
recorded because ruling 23 allowed no browser load, so the gate holds the one request's shape.

Every response is canned, from the shapes recorded on 2026-09-23 with synthetic values. Nothing
in this file touches the network.
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
from dumpstagram._core.comments import read_comment_page
from dumpstagram._core.pacer import PacingPolicy, WritePolicy
from dumpstagram._core.writes.comments import create_comment, delete_comment
from dumpstagram._private.transport import Request
from dumpstagram._private.web.parse.media import parse_comment_page, parse_created_comment
from dumpstagram.aio import AsyncClient
from dumpstagram.errors import UpstreamRejected
from dumpstagram.models import Comment, CommentAuthor, Page
from dumpstagram.session import Session
from tests.test_direct import (
   ScriptedTransport,
   a_bootstrapped_session,
   json_response,
   make_paced,
   sent_variables,
)
from tests.test_feed import MEDIA_ID, MEDIA_PK

API_GRAPHQL = "https://www.instagram.com/api/graphql"
HOME = "https://www.instagram.com/"

PAGE_DOC_ID = "28169471862682868"
CREATE_DOC_ID = "27261905640092552"
DELETE_DOC_ID = "27034318419564986"

COMMENT_ID = "18000000000000001"
AUTHOR_PK = "1234567890"
AUTHOR_FBID = "17840000000000001"
CURSOR = "an-opaque-cursor"
CREATED_AT = 1790156400


def user(**overrides: Any) -> dict[str, Any]:
   """The ``user`` object both answers carried. ``fbid_v2`` is a different identifier from
   ``pk`` and ``id``, which held the same value on every observed node."""

   built: dict[str, Any] = {
      "fbid_v2": AUTHOR_FBID,
      "id": AUTHOR_PK,
      "is_verified": False,
      "pk": AUTHOR_PK,
      "profile_pic_url": "https://example.invalid/pic.jpg",
      "username": "an_author",
   }
   built.update(overrides)

   return built


def node(**overrides: Any) -> dict[str, Any]:
   """The comment page node's full key set as read on 2026-09-23. Synthetic values, and the
   ``__typename`` is a guess of the recorded length, 14, which nothing reads."""

   built: dict[str, Any] = {
      "__typename": "XDTCommentDict",
      "child_comment_count": 2,
      "comment_like_count": 5,
      "created_at": CREATED_AT,
      "fallback_user_info": {"id": AUTHOR_PK},
      "giphy_media_info": None,
      "has_liked_comment": True,
      "has_translation": None,
      "is_covered": False,
      "is_edited": False,
      "parent_comment_id": None,
      "pk": COMMENT_ID,
      "restricted_status": 0,
      "text": "a comment",
      "user": {**user(), "is_unpublished": False},
   }
   built.update(overrides)

   return built


def page_payload(
   nodes: list[dict[str, Any]], *, has_next_page: bool, end_cursor: str | None
) -> dict[str, Any]:
   return {
      "data": {
         "xdt_api__v1__media__media_id__comments__connection": {
            "edges": [{"node": each, "cursor": None} for each in nodes],
            "page_info": {
               "end_cursor": end_cursor,
               "has_next_page": has_next_page,
               "start_cursor": None,
               "has_previous_page": False,
            },
         }
      },
      "extensions": {"is_final": True},
   }


def created_payload() -> dict[str, Any]:
   """The 977 byte answer observed twice, synthetic values under the recorded keys."""

   return {
      "data": {
         "xig_comment_create": {
            "__typename": "XIGCommentCreateMutationSuccessResponse",
            "comment_dict": {
               "created_at": CREATED_AT,
               "pk": COMMENT_ID,
               "text": "a comment",
               "user": {**user(), "full_name": "An Author"},
            },
         }
      },
      "extensions": {"is_final": True},
   }


def deleted_payload() -> dict[str, Any]:
   """The 210 byte answer both real deletes returned. Only the typename's length, 39, was
   recorded, and the value here is inferred from the create's naming, which has that length."""

   return {
      "data": {"xig_comment_delete": {"__typename": "XIGCommentDeleteMutationSuccessResponse"}},
      "extensions": {"is_final": True},
   }


def nothing_deleted_payload() -> dict[str, Any]:
   """The 158 byte answer to a delete that named no comment."""

   return {"data": {"xig_comment_delete": None}, "extensions": {"is_final": True}}


def body_of(request: Request) -> dict[str, list[str]]:
   return parse_qs(request.content.decode("utf-8")) if request.content else {}


def test_a_short_page_that_says_more_exist_is_not_the_end() -> None:
   """Catches a reader that decides the connection ended because a page came back short or
   empty, when the server's own flag says otherwise."""

   short = parse_comment_page(page_payload([node()], has_next_page=True, end_cursor=CURSOR))
   empty = parse_comment_page(page_payload([], has_next_page=True, end_cursor=CURSOR))
   last = parse_comment_page(page_payload([node()], has_next_page=False, end_cursor=None))

   assert short.has_next_page is True
   assert short.end_cursor == CURSOR
   assert empty.has_next_page is True
   assert empty.end_cursor == CURSOR
   assert last.has_next_page is False


def test_a_page_node_maps_into_a_comment_field_by_field() -> None:
   """Catches a count, the reply link or the viewer's like read from the wrong key."""

   page = parse_comment_page(page_payload([node()], has_next_page=False, end_cursor=None))

   assert page == Page(
      items=(
         Comment(
            id=COMMENT_ID,
            text="a comment",
            created_at=datetime.fromtimestamp(CREATED_AT, tz=UTC),
            author=CommentAuthor(
               id=AUTHOR_PK,
               username="an_author",
               is_verified=False,
               profile_pic_url="https://example.invalid/pic.jpg",
            ),
            like_count=5,
            reply_count=2,
            parent_comment_id=None,
            has_liked=True,
         ),
      ),
      has_next_page=False,
      end_cursor=None,
   )


def test_the_created_comment_maps_field_by_field_from_the_recorded_answer() -> None:
   """Catches the author taken from the wrong identifier, the time in the wrong unit, or the
   counts the answer does not carry filled in with a guess."""

   created = parse_created_comment(created_payload())

   assert created == Comment(
      id=COMMENT_ID,
      text="a comment",
      created_at=datetime.fromtimestamp(CREATED_AT, tz=UTC),
      author=CommentAuthor(
         id=AUTHOR_PK,
         username="an_author",
         is_verified=False,
         profile_pic_url="https://example.invalid/pic.jpg",
      ),
   )


@pytest.mark.asyncio
async def test_the_page_read_sends_the_request_the_engine_replayed() -> None:
   """The parity gate for the read. Catches the query sent with other variables, a cursor not
   passed on, another path or referer, or beside a request nothing recorded."""

   transport = ScriptedTransport(
      [json_response(page_payload([node()], has_next_page=False, end_cursor=None))]
   )

   await read_comment_page(make_paced(transport), a_bootstrapped_session(), MEDIA_PK, after=CURSOR)

   assert len(transport.sent) == 1

   request = transport.sent[0]
   body = body_of(request)

   assert request.url == API_GRAPHQL
   assert body["doc_id"] == [PAGE_DOC_ID]
   assert body["fb_api_req_friendly_name"] == ["PolarisPostCommentsPaginationQuery"]
   assert sent_variables(request) == {
      "after": CURSOR,
      "before": None,
      "first": 10,
      "last": None,
      "media_id": MEDIA_PK,
      "sort_order": "popular",
      "__relay_internal__pv__PolarisIsLoggedInrelayprovider": True,
   }
   assert request.headers["referer"] == HOME


@pytest.mark.asyncio
async def test_the_comment_sends_the_request_the_engine_replayed() -> None:
   """The parity gate for the create. Catches the id form sent for the pk, a variable no send
   carried, an input wrapper the upstream did not take, or a request beside the write."""

   transport = ScriptedTransport([json_response(created_payload())])

   await create_comment(make_paced(transport), a_bootstrapped_session(), MEDIA_PK, "a comment")

   assert len(transport.sent) == 1

   request = transport.sent[0]
   body = body_of(request)

   assert request.url == API_GRAPHQL
   assert body["doc_id"] == [CREATE_DOC_ID]
   assert body["fb_api_req_friendly_name"] == ["PolarisPostCommentInputRevampedMutation"]
   assert sent_variables(request) == {
      "connections": [],
      "data": {"comment_text": "a comment", "media_id": MEDIA_PK},
   }
   assert request.headers["referer"] == HOME


@pytest.mark.asyncio
async def test_the_delete_sends_the_post_and_the_comment_together() -> None:
   """The parity gate for the delete, and the table's row that it names both. Catches the post
   identifier dropped, the two swapped, or a request beside the write."""

   transport = ScriptedTransport([json_response(deleted_payload())])

   await delete_comment(make_paced(transport), a_bootstrapped_session(), MEDIA_PK, COMMENT_ID)

   assert len(transport.sent) == 1

   request = transport.sent[0]
   body = body_of(request)

   assert request.url == API_GRAPHQL
   assert body["doc_id"] == [DELETE_DOC_ID]
   assert body["fb_api_req_friendly_name"] == ["usePolarisPostDeleteCommentMutation"]
   assert sent_variables(request) == {
      "input": {"client_mutation_id": "1", "comment_id": COMMENT_ID, "media_id": MEDIA_PK}
   }
   assert request.headers["referer"] == HOME


@pytest.mark.asyncio
async def test_a_delete_answered_with_a_null_root_is_not_a_delete() -> None:
   """Catches a null root field taken as success, which reports a comment gone that is up."""

   transport = ScriptedTransport([json_response(nothing_deleted_payload())])

   with pytest.raises(UpstreamRejected) as raised:
      await delete_comment(make_paced(transport), a_bootstrapped_session(), MEDIA_PK, COMMENT_ID)

   assert raised.value.code == "comment_not_deleted"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["page", "comment", "delete"])
async def test_the_id_form_is_refused_before_anything_is_sent(operation: str) -> None:
   """Catches ``Post.id`` passed through to the upstream, whose answer to it is unobserved."""

   transport = ScriptedTransport([])
   sender = make_paced(transport)
   session = a_bootstrapped_session()

   with pytest.raises(ValueError):
      if operation == "page":
         await read_comment_page(sender, session, MEDIA_ID)
      elif operation == "comment":
         await create_comment(sender, session, MEDIA_ID, "a comment")
      else:
         await delete_comment(sender, session, MEDIA_ID, COMMENT_ID)

   assert transport.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["comment", "delete"])
async def test_both_writes_depart_only_through_the_write_slot(operation: str) -> None:
   """Catches a write sent with ``sender.send`` rather than ``send_write``. On an account whose
   writes are stopped the write slot refuses before the transport sees anything, and an
   ordinary send does not."""

   answer = created_payload() if operation == "comment" else deleted_payload()
   transport = ScriptedTransport([json_response(answer)])
   sender = make_paced(transport)
   sender.pacer.stop_writes()

   with pytest.raises(UpstreamRejected):
      if operation == "comment":
         await create_comment(sender, a_bootstrapped_session(), MEDIA_PK, "a comment")
      else:
         await delete_comment(sender, a_bootstrapped_session(), MEDIA_PK, COMMENT_ID)

   assert transport.sent == []


@pytest.mark.asyncio
async def test_an_error_envelope_on_a_comment_raises_and_departs_once() -> None:
   """Catches a comment sent again after the upstream answered it with an error, which would be
   a duplicate if the first had applied. The write stop is off here, because with it on the
   pacer would refuse the second send and hide a capability that retries."""

   envelope = {"error": "a_code_no_finding_explains"}
   transport = ScriptedTransport([json_response(envelope), json_response(envelope)])
   sender = make_paced(transport).with_pacing(
      PacingPolicy(), WritePolicy(stop_after_unrecognised_rejection=False)
   )

   with pytest.raises(UpstreamRejected):
      await create_comment(sender, a_bootstrapped_session(), MEDIA_PK, "a comment")

   assert len(transport.sent) == 1


def test_the_comment_docstring_names_the_reconciling_read() -> None:
   """The documentation row of the table, held mechanically. Catches the public ``comment``
   losing the instruction to read the comments before sending again, which for an appending
   write is the only safe way out of an unknown outcome."""

   documented = AsyncClient.comment.__doc__ or ""

   assert "OutcomeUnknown" in documented
   assert ":meth:`comments`" in documented


class RecordingClient:
   def __init__(self) -> None:
      self.session = Session(sessionid="s", ds_user_id="1234567890", csrftoken="c")
      self.calls: list[tuple[str, ...]] = []

   def comments(self, post_pk: str, *, after: str | None = None) -> Page[Comment]:
      self.calls.append(("comments", post_pk, after or ""))

      return parse_comment_page(page_payload([node()], has_next_page=True, end_cursor=CURSOR))

   def comment(self, post_pk: str, text: str) -> Comment:
      self.calls.append(("comment", post_pk, text))

      return parse_created_comment(created_payload())

   def delete_comment(self, post_pk: str, comment_id: str) -> None:
      self.calls.append(("delete_comment", post_pk, comment_id))

   def close(self) -> None:
      pass


def run_cli(argv: list[str], client: RecordingClient) -> tuple[int, str]:
   out = io.StringIO()

   def factory(path: Path, *, user_agent: str | None = None) -> Any:
      return client

   code = main(argv, environment={}, client_factory=factory, stdout=out, stderr=io.StringIO())

   return code, out.getvalue()


def test_the_cli_reads_the_named_page_and_reports_the_servers_terminator() -> None:
   """Catches the cursor not passed on, or ``more_available`` computed from the page length."""

   client = RecordingClient()

   code, out = run_cli(
      ["--json", "--session", "s.json", "comments", MEDIA_PK, "--after", CURSOR], client
   )

   assert code == 0
   assert client.calls == [("comments", MEDIA_PK, CURSOR)]
   assert json.loads(out)["more_available"] is True


def test_the_cli_writes_the_named_text_to_the_named_post() -> None:
   """Catches the CLI commenting on anything but the pk and text it was given."""

   client = RecordingClient()

   code, out = run_cli(["--json", "--session", "s.json", "comment", MEDIA_PK, "hello"], client)

   assert code == 0
   assert client.calls == [("comment", MEDIA_PK, "hello")]
   assert json.loads(out)["comment"]["id"] == COMMENT_ID


def test_the_cli_deletes_the_named_comment_on_the_named_post() -> None:
   """Catches the CLI swapping the two identifiers or dropping one."""

   client = RecordingClient()

   code, _ = run_cli(["--session", "s.json", "delete-comment", MEDIA_PK, COMMENT_ID], client)

   assert code == 0
   assert client.calls == [("delete_comment", MEDIA_PK, COMMENT_ID)]


def test_the_cli_refuses_a_comment_id_that_is_not_digits_before_opening_a_client() -> None:
   """Catches a malformed comment id reaching a client, where it would become a live write."""

   client = RecordingClient()

   with pytest.raises(SystemExit) as raised:
      run_cli(["--session", "s.json", "delete-comment", MEDIA_PK, "abc"], client)

   assert raised.value.code == 2
   assert client.calls == []
