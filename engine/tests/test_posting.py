"""Gates on posting: the upload, the photo and carousel publish, the post delete, and the CLI.

Seven defect classes live here.

A request can drift from the one the browser or the engine's verified replay sent. The upload
is the first request on another host with its metadata in headers, and the carousel publish the
first JSON body, so each is held to a pseudonymised fixture of the recorded request.

An upload that applied can be lost from view when the publish after it fails. The caller must
be told which half failed and which upload ids are orphaned, and neither half may be sent
again, which is Step 19's orphaned upload gate.

A write can leave by a path other than ``send_write``, which would skip the write budget and
the single-departure rule. The upload is a write too.

The upload can go to the wrong host, or the account's cookies to a host the upload pin does not
name.

An answer can be taken for success when it is not: a ``status`` other than ``ok``, an upload
answered for another id, a delete answered without ``did_delete``.

The image can be misdescribed: a width and height swapped, or a file that is not a JPEG sent.

And the CLI can report a post confirmed or gone on a read that does not show it, or lose the
code of a post that is up when the read after the publish fails.

Every response is canned from the recorded shapes with synthetic values. Nothing here touches
the network.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pytest
from PIL import Image

from dumpstagram._cli.main import main
from dumpstagram._core.images import read_jpeg
from dumpstagram._core.pacer import Pacer, WritePolicy
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.writes.posts import delete_post, publish_carousel, publish_photo
from dumpstagram._private.transport import Request, Response
from dumpstagram._private.web.requests.posting import UPLOAD_HOST
from dumpstagram.aio import AsyncClient
from dumpstagram.errors import (
   OutcomeUnknown,
   RateLimited,
   SchemaChanged,
   TransportFailure,
   UpstreamRejected,
)
from dumpstagram.models import PostAuthor, PostDetail, PublishedPost
from dumpstagram.session import Session
from tests.test_direct import FakeClock, a_bootstrapped_session, json_response

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "posting"

VIEWER_ID = "1234567890"
POST_PK = "3000000000000000001"
POST_CODE = "Cfixture0000000000000000000000000000001"

CLOCK_SECONDS = 1700000000.001
FIRST_UPLOAD_ID = "1700000000001"
SECOND_UPLOAD_ID = "1700000000002"

UNDOCUMENTED_BROWSER_HEADERS = frozenset(
   {"content-length", "x-ig-max-touch-points", "x-web-session-id"}
)
"""What the browser sent on these calls and the engine does not: the length ``httpx`` adds on
its own, and two headers recorded as departures in ``docs/web-request-contract.md``."""

UNRECORDED_ENGINE_HEADERS = frozenset({"user-agent", "accept-language"})
"""What the engine sends that the fixtures leave out of the recorded names, because the recorded
values identify the browser."""

UNDOCUMENTED_DELETE_HEADERS = frozenset({"content-length", "x-ig-max-touch-points"})
"""The same for the delete, whose page request carried no session id header."""


def fixture(name: str) -> Any:
   return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def jpeg(width: int = 1080, height: int = 1080) -> bytes:
   buffer = io.BytesIO()
   Image.new("RGB", (width, height), (46, 111, 158)).save(buffer, "JPEG", quality=90)

   return buffer.getvalue()


class ScriptedTransport:
   """Answers in order, or raises what the script says, and records every request."""

   def __init__(self, answers: list[Response | BaseException]) -> None:
      self.answers = list(answers)
      self.sent: list[Request] = []

   async def send(self, request: Request) -> Response:
      self.sent.append(request)

      if not self.answers:
         raise AssertionError(f"unscripted request to {request.url}")

      answer = self.answers.pop(0)

      if isinstance(answer, BaseException):
         raise answer

      return answer


def senders(
   transport: ScriptedTransport, writes: WritePolicy | None = None
) -> tuple[PacedSender, PacedSender]:
   """The www sender and the upload sender over one account's pacer, as the client builds them."""

   clock = FakeClock()
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)
   policy = writes or WritePolicy()

   return PacedSender(transport, pacer, writes=policy), PacedSender(transport, pacer, writes=policy)


def a_viewer_session() -> Session:
   session = a_bootstrapped_session()
   session.ds_user_id = VIEWER_ID

   return session


def upload_answer(upload_id: str) -> Response:
   return json_response({**fixture("upload_answer.json"), "upload_id": upload_id})


def photo_answer() -> Response:
   return json_response(fixture("photo_publish_answer.json")["answer"])


def carousel_answer() -> Response:
   return json_response(fixture("carousel_publish_answer.json")["answer"])


def delete_answer(text: str | None = None) -> Response:
   body = text if text is not None else (FIXTURES / "delete_answer.txt").read_text()

   return Response(
      status_code=200,
      headers={"content-type": "text/javascript; charset=utf-8"},
      content=body.encode("utf-8"),
      final_url="https://www.instagram.com/",
   )


def form_of(request: Request) -> list[tuple[str, str]]:
   return parse_qsl((request.content or b"").decode("utf-8"), keep_blank_values=True)


@pytest.mark.asyncio
async def test_the_upload_is_shaped_as_the_browser_sent_it() -> None:
   """Catches the upload drifting from the recorded one: another host or path, a header missing
   or renamed, the parameters misnamed, the body not the file, or a csrf header added that the
   composer's uploader never sends."""

   recorded = fixture("upload_request.json")
   transport = ScriptedTransport([upload_answer(FIRST_UPLOAD_ID), photo_answer()])
   sender, uploads = senders(transport)
   image = jpeg()

   await publish_photo(sender, uploads, a_viewer_session(), image, clock=lambda: CLOCK_SECONDS)

   upload = transport.sent[0]
   headers = {name.lower(): value for name, value in upload.headers.items()}

   assert upload.method == recorded["method"]
   assert upload.url == recorded["url"]
   assert upload.content == image
   assert set(recorded["header_names"]) - set(headers) == UNDOCUMENTED_BROWSER_HEADERS
   assert set(headers) - set(recorded["header_names"]) == UNRECORDED_ENGINE_HEADERS
   assert {name: headers[name] for name in recorded["header_values"]} == recorded["header_values"]
   assert headers["x-entity-name"] == recorded["entity_name"]
   assert headers["x-entity-length"] == str(len(image))
   assert json.loads(headers["x-instagram-rupload-params"]) == recorded["rupload_params"]
   assert "x-csrftoken" not in headers


@pytest.mark.asyncio
async def test_the_photo_publish_sends_the_verified_form() -> None:
   """Catches the single publish drifting from the form both verified replays sent: a field
   dropped, added or renamed, a fixed value changed, or the upload id not the one uploaded."""

   recorded = fixture("photo_publish_request.json")
   transport = ScriptedTransport([upload_answer(FIRST_UPLOAD_ID), photo_answer()])
   sender, uploads = senders(transport)

   await publish_photo(sender, uploads, a_viewer_session(), jpeg(), clock=lambda: CLOCK_SECONDS)

   publish = transport.sent[1]
   fields = form_of(publish)
   values = dict(fields)

   assert publish.url == recorded["url"]
   assert publish.headers["content-type"] == recorded["content_type"]
   assert [name for name, _ in fields] == recorded["body_field_names_in_order"]
   assert {name: values[name] for name in recorded["body_fixed_values"]} == recorded[
      "body_fixed_values"
   ]
   assert values["upload_id"] == FIRST_UPLOAD_ID
   assert values["caption"] == ""
   assert publish.headers["x-csrftoken"] == "csrf-value"


@pytest.mark.asyncio
async def test_the_carousel_publish_sends_the_browsers_json_in_its_order() -> None:
   """Catches the carousel body drifting from the browser's: form encoded instead of JSON, a key
   out of the recorded order or missing, a fixed value changed, or the slides out of order."""

   recorded = fixture("carousel_publish_request.json")
   transport = ScriptedTransport(
      [upload_answer(FIRST_UPLOAD_ID), upload_answer(SECOND_UPLOAD_ID), carousel_answer()]
   )
   sender, uploads = senders(transport)

   await publish_carousel(
      sender, uploads, a_viewer_session(), [jpeg(), jpeg()], clock=lambda: CLOCK_SECONDS
   )

   publish = transport.sent[2]
   body = json.loads(publish.content or b"")
   headers = {name.lower(): value for name, value in publish.headers.items()}

   assert set(recorded["header_names"]) - set(headers) == UNDOCUMENTED_BROWSER_HEADERS
   assert set(headers) - set(recorded["header_names"]) == UNRECORDED_ENGINE_HEADERS

   assert publish.url == recorded["url"]
   assert publish.headers["content-type"] == recorded["content_type"]
   assert list(body) == recorded["body_keys_in_order"]
   assert {key: body[key] for key in recorded["body_fixed_values"]} == recorded["body_fixed_values"]
   assert body["children_metadata"] == [
      {"upload_id": FIRST_UPLOAD_ID},
      {"upload_id": SECOND_UPLOAD_ID},
   ]
   assert body["fb_dtsg"] == "an-older-token"


@pytest.mark.asyncio
async def test_the_delete_names_the_viewers_post_from_its_page() -> None:
   """Catches the delete drifting from the page's: the pk sent without the viewer's id, the
   referer not the post's page, a field of the recorded form renamed, or a csrf header added."""

   recorded = fixture("delete_request.json")
   transport = ScriptedTransport([delete_answer()])
   sender, _ = senders(transport)

   await delete_post(sender, a_viewer_session(), POST_PK, POST_CODE)

   request = transport.sent[0]
   headers = {name.lower(): value for name, value in request.headers.items()}
   sent_names = [name for name, _ in form_of(request)]
   recorded_names = recorded["body_field_names_in_order"]

   assert request.url == recorded["url"]
   assert headers["content-type"] == recorded["content_type"]
   assert headers["referer"] == f"https://www.instagram.com/p/{POST_CODE}/"
   assert headers["x-ig-d"] == recorded["x_ig_d"]
   assert "x-csrftoken" not in headers
   assert set(recorded["header_names"]) - set(headers) == UNDOCUMENTED_DELETE_HEADERS
   assert set(headers) - set(recorded["header_names"]) == UNRECORDED_ENGINE_HEADERS
   assert sent_names == [name for name in recorded_names if name in sent_names]
   assert set(recorded_names) - set(sent_names) == {
      "__s",
      "__dyn",
      "__csr",
      "__hsdp",
      "__hblp",
      "__sjsp",
   }
   assert dict(form_of(request))["__crn"] == recorded["crn"]


@pytest.mark.asyncio
async def test_a_publish_that_fails_after_the_upload_names_the_orphan_and_sends_nothing_more() -> (
   None
):
   """Catches the orphaned upload gate of Step 19: a publish failure that hides which half
   failed, forgets the upload id that applied, wraps the original error, or sends either half
   again."""

   refusal = json_response({"message": "refused", "status": "fail", "error_type": "a_refusal"})
   transport = ScriptedTransport([upload_answer(FIRST_UPLOAD_ID), refusal])
   sender, uploads = senders(transport, WritePolicy(stop_after_unrecognised_rejection=False))

   with pytest.raises(UpstreamRejected) as raised:
      await publish_photo(sender, uploads, a_viewer_session(), jpeg(), clock=lambda: CLOCK_SECONDS)

   notes = " ".join(raised.value.__notes__)

   assert raised.value.code == "a_refusal"
   assert "publish failed" in notes
   assert f"uploads {FIRST_UPLOAD_ID} are orphaned" in notes
   assert len(transport.sent) == 2


@pytest.mark.asyncio
async def test_a_failed_second_upload_names_the_first_as_orphaned_and_publishes_nothing() -> None:
   """Catches a carousel that publishes after an upload failed, or whose error does not say how
   far it got."""

   refusal = json_response({"status": "fail"})
   transport = ScriptedTransport([upload_answer(FIRST_UPLOAD_ID), refusal])
   sender, uploads = senders(transport, WritePolicy(stop_after_unrecognised_rejection=False))

   with pytest.raises(UpstreamRejected) as raised:
      await publish_carousel(
         sender, uploads, a_viewer_session(), [jpeg(), jpeg()], clock=lambda: CLOCK_SECONDS
      )

   notes = " ".join(raised.value.__notes__)

   assert "upload 2 of 2 failed" in notes
   assert f"uploads {FIRST_UPLOAD_ID} applied before it and are orphaned" in notes
   assert len(transport.sent) == 2


@pytest.mark.asyncio
async def test_a_publish_lost_in_flight_is_unknown_and_never_sent_again() -> None:
   """Catches a publish retried after a connection failure, which could post twice, or reported
   as a network error a caller would answer by publishing again."""

   transport = ScriptedTransport(
      [upload_answer(FIRST_UPLOAD_ID), TransportFailure("connection reset")]
   )
   sender, uploads = senders(transport)

   with pytest.raises(OutcomeUnknown) as raised:
      await publish_photo(sender, uploads, a_viewer_session(), jpeg(), clock=lambda: CLOCK_SECONDS)

   assert raised.value.operation == "publish_photo"
   assert "orphaned" in " ".join(raised.value.__notes__)
   assert [urlsplit(request.url).path for request in transport.sent] == [
      f"/rupload_igphoto/fb_uploader_{FIRST_UPLOAD_ID}",
      "/api/v1/media/configure/",
   ]


@pytest.mark.asyncio
async def test_an_upload_counts_against_the_write_budget() -> None:
   """Catches an upload sent outside ``send_write``, which would skip the budget and the
   one-departure rule. With room for one write, the upload takes it and the publish is refused
   before it leaves."""

   transport = ScriptedTransport([upload_answer(FIRST_UPLOAD_ID)])
   sender, uploads = senders(transport, WritePolicy(budget_per_hour=1))

   with pytest.raises(RateLimited, match="write budget"):
      await publish_photo(sender, uploads, a_viewer_session(), jpeg(), clock=lambda: CLOCK_SECONDS)

   assert len(transport.sent) == 1


@pytest.mark.asyncio
async def test_an_upload_answered_for_another_id_publishes_nothing() -> None:
   """Catches an upload answer taken as success when it names another upload, after which the
   publish would name a file nobody stored."""

   transport = ScriptedTransport([upload_answer("1700000000999")])
   sender, uploads = senders(transport)

   with pytest.raises(SchemaChanged):
      await publish_photo(sender, uploads, a_viewer_session(), jpeg(), clock=lambda: CLOCK_SECONDS)

   assert len(transport.sent) == 1


@pytest.mark.asyncio
async def test_a_publish_answer_without_status_ok_is_a_rejection() -> None:
   """Catches a REST ``status`` other than ``ok`` passed through as a post, which the
   classifier cannot see because it reads GraphQL envelopes only."""

   refusal = json_response({"media": None, "status": "fail"})
   transport = ScriptedTransport([upload_answer(FIRST_UPLOAD_ID), refusal])
   sender, uploads = senders(transport, WritePolicy(stop_after_unrecognised_rejection=False))

   with pytest.raises(UpstreamRejected) as raised:
      await publish_photo(sender, uploads, a_viewer_session(), jpeg(), clock=lambda: CLOCK_SECONDS)

   assert raised.value.code == "status_not_ok"


@pytest.mark.asyncio
async def test_the_publish_returns_the_post_the_answer_describes() -> None:
   """Catches the created post mapped wrong: the id form in ``pk``, a lost code, or the upload
   ids out of slide order."""

   transport = ScriptedTransport(
      [upload_answer(FIRST_UPLOAD_ID), upload_answer(SECOND_UPLOAD_ID), carousel_answer()]
   )
   sender, uploads = senders(transport)

   published = await publish_carousel(
      sender, uploads, a_viewer_session(), [jpeg(), jpeg()], clock=lambda: CLOCK_SECONDS
   )

   assert published.pk == POST_PK
   assert published.id == f"{POST_PK}_{VIEWER_ID}"
   assert published.code == POST_CODE
   assert published.media_type == 8
   assert published.upload_ids == (FIRST_UPLOAD_ID, SECOND_UPLOAD_ID)


@pytest.mark.asyncio
async def test_a_delete_answered_without_did_delete_is_refused() -> None:
   """Catches a delete that reports success when the answer says nothing was deleted."""

   answer = 'for (;;);{"__ar":1,"payload":{"did_delete":false}}'
   transport = ScriptedTransport([delete_answer(answer)])
   sender, _ = senders(transport)

   with pytest.raises(UpstreamRejected) as raised:
      await delete_post(sender, a_viewer_session(), POST_PK, POST_CODE)

   assert raised.value.code == "post_not_deleted"


@pytest.mark.asyncio
async def test_the_id_form_is_refused_before_a_delete_is_sent() -> None:
   """Catches the ``<pk>_<owner>`` form reaching the request, where it would become
   ``<pk>_<owner>_<viewer>``."""

   transport = ScriptedTransport([])
   sender, _ = senders(transport)

   with pytest.raises(ValueError):
      await delete_post(sender, a_viewer_session(), f"{POST_PK}_{VIEWER_ID}", POST_CODE)

   assert transport.sent == []


@pytest.mark.asyncio
async def test_the_upload_declares_the_files_own_width_and_height() -> None:
   """Catches the dimensions swapped or fixed, which the upload's parameters carry."""

   transport = ScriptedTransport([upload_answer(FIRST_UPLOAD_ID), photo_answer()])
   sender, uploads = senders(transport)

   await publish_photo(
      sender, uploads, a_viewer_session(), jpeg(1080, 1350), clock=lambda: CLOCK_SECONDS
   )

   parameters = json.loads(transport.sent[0].headers["x-instagram-rupload-params"])

   assert (parameters["upload_media_width"], parameters["upload_media_height"]) == (1080, 1350)


@pytest.mark.asyncio
async def test_what_is_not_a_jpeg_is_refused_before_anything_is_sent() -> None:
   """Catches a PNG or any other file sent to an upload only a JPEG has been observed through."""

   png = io.BytesIO()
   Image.new("RGB", (10, 10)).save(png, "PNG")
   transport = ScriptedTransport([])
   sender, uploads = senders(transport)

   with pytest.raises(ValueError):
      await publish_photo(sender, uploads, a_viewer_session(), png.getvalue())

   assert transport.sent == []


def test_a_jpeg_is_read_from_a_path_as_from_bytes(tmp_path: Path) -> None:
   """Catches the path form reading something other than the file's bytes."""

   image = jpeg(640, 480)
   path = tmp_path / "slide.jpg"
   path.write_bytes(image)

   assert read_jpeg(path) == read_jpeg(image)
   assert (read_jpeg(path).width, read_jpeg(path).height) == (640, 480)


@pytest.mark.asyncio
async def test_a_carousel_of_one_is_refused_before_anything_is_sent() -> None:
   """Catches one image published as a carousel, which the composer never does."""

   transport = ScriptedTransport([])
   sender, uploads = senders(transport)

   with pytest.raises(ValueError):
      await publish_carousel(sender, uploads, a_viewer_session(), [jpeg()])

   assert transport.sent == []


@pytest.mark.asyncio
async def test_the_client_uploads_through_a_pool_pinned_to_the_upload_host() -> None:
   """Catches the upload sent through the www pool, which refuses the host, or through a pool
   pinned elsewhere or pacing apart from the account, which would let uploads skip the write
   spacing the www writes wait out."""

   async with AsyncClient(a_viewer_session()) as client:
      upload_transport = client._uploads._sender
      scoped = client.with_behavior(client.behavior)

      assert upload_transport.allowed_host == UPLOAD_HOST
      assert not upload_transport.cookieless
      assert client._uploads.pacer is client._sender.pacer
      assert scoped._uploads.pacer is client._sender.pacer


def a_post_detail(*, pk: str = POST_PK, author_id: str = VIEWER_ID) -> PostDetail:
   from datetime import UTC, datetime

   return PostDetail(
      id=f"{pk}_{author_id}",
      pk=pk,
      code=POST_CODE,
      taken_at=datetime(2026, 9, 23, tzinfo=UTC),
      author=PostAuthor(
         id=author_id,
         username="fixture_owner",
         full_name="",
         is_private=True,
         is_verified=False,
         profile_pic_url="https://example.invalid/pic.jpg",
      ),
      media_type=1,
      product_type="feed",
      like_count=0,
      comment_count=0,
      has_liked=False,
   )


class RecordingMedia:
   def __init__(self, client: RecordingClient) -> None:
      self.client = client

   def publish_photo(self, image: object, *, caption: str = "") -> PublishedPost:
      self.client.calls.append(("publish_photo", str(image), caption))

      return self.client.published

   def publish_carousel(self, images: list[object], *, caption: str = "") -> PublishedPost:
      self.client.calls.append(("publish_carousel", *[str(image) for image in images]))

      return self.client.published

   def delete_post(self, post_pk: str, code: str) -> None:
      self.client.calls.append(("delete_post", post_pk, code))

   def by_code(self, code: str) -> PostDetail:
      self.client.calls.append(("by_code", code))
      answer = self.client.read_answers.pop(0)

      if isinstance(answer, BaseException):
         raise answer

      return answer


class RecordingClient:
   def __init__(self, read_answers: list[PostDetail | BaseException]) -> None:
      from datetime import UTC, datetime

      self.session = Session(sessionid="s", ds_user_id=VIEWER_ID, csrftoken="c")
      self.calls: list[tuple[str, ...]] = []
      self.read_answers = read_answers
      self.published = PublishedPost(
         pk=POST_PK,
         id=f"{POST_PK}_{VIEWER_ID}",
         code=POST_CODE,
         taken_at=datetime(2026, 9, 23, tzinfo=UTC),
         media_type=1,
         upload_ids=(FIRST_UPLOAD_ID,),
      )
      self.media = RecordingMedia(self)

   def close(self) -> None:
      pass


def run_cli(argv: list[str], client: RecordingClient) -> tuple[int, dict[str, Any], str]:
   out = io.StringIO()
   errors = io.StringIO()

   def factory(path: Path, *, user_agent: str | None = None) -> Any:
      return client

   code = main(
      ["--json", "--session", "s.json", *argv],
      environment={},
      client_factory=factory,
      stdout=out,
      stderr=errors,
   )
   printed = json.loads(out.getvalue()) if out.getvalue() else {}

   return code, printed, errors.getvalue()


def test_the_cli_publishes_and_confirms_by_reading_the_post_back() -> None:
   """Catches a publish command that reports the post without reading it, or reads another code."""

   client = RecordingClient([a_post_detail()])

   code, printed, _ = run_cli(["publish-photo", "slide.jpg"], client)

   assert code == 0
   assert client.calls == [("publish_photo", "slide.jpg", ""), ("by_code", POST_CODE)]
   assert printed["confirmed"] is True
   assert printed["post"]["code"] == POST_CODE


def test_the_cli_does_not_confirm_a_read_back_of_someone_elses_post() -> None:
   """Catches a confirmation that checks the read succeeded and not what it shows."""

   client = RecordingClient([a_post_detail(author_id="9999999999")])

   code, printed, _ = run_cli(["publish-photo", "slide.jpg"], client)

   assert code == 0
   assert printed["confirmed"] is False


def test_the_cli_prints_a_published_post_even_when_the_read_after_it_fails() -> None:
   """Catches a post that is up while its pk and code are lost to a failed confirmation."""

   client = RecordingClient([TransportFailure("read failed")])

   code, printed, _ = run_cli(["publish-photo", "slide.jpg"], client)

   assert code == 9
   assert printed["post"]["pk"] == POST_PK
   assert printed["post"]["code"] == POST_CODE
   assert printed["confirmed"] is False


def test_the_cli_reports_a_deleted_post_gone_only_on_the_deleted_posts_refusal() -> None:
   """Catches the delete command reporting gone without a read, or on any refusal at all."""

   gone = RecordingClient([UpstreamRejected("rejected", code="1675030")])
   other = RecordingClient([UpstreamRejected("rejected", code="html_app_shell")])

   gone_code, gone_printed, _ = run_cli(["delete-post", POST_PK, POST_CODE], gone)
   other_code, other_printed, _ = run_cli(["delete-post", POST_PK, POST_CODE], other)

   assert gone.calls == [("delete_post", POST_PK, POST_CODE), ("by_code", POST_CODE)]
   assert (gone_code, gone_printed["gone"]) == (0, True)
   assert (other_code, other_printed["gone"]) == (6, None)


def test_the_cli_says_a_post_that_still_reads_back_is_not_gone() -> None:
   """Catches a delete answered as done taken on its word while the post is still up."""

   client = RecordingClient([a_post_detail()])

   code, printed, _ = run_cli(["delete-post", POST_PK, POST_CODE], client)

   assert code == 6
   assert printed["gone"] is False


def test_the_cli_publishes_the_carousel_slides_in_the_order_given() -> None:
   """Catches the slide order changed between the command line and the publish."""

   client = RecordingClient([a_post_detail()])

   run_cli(["publish-carousel", "b.jpg", "a.jpg"], client)

   assert client.calls[0] == ("publish_carousel", "b.jpg", "a.jpg")


def test_the_cli_refuses_a_carousel_of_one_before_opening_a_client() -> None:
   """Catches one slide reaching a client, where it would become a write the core refuses."""

   code = main(
      ["--session", "s.json", "publish-carousel", "a.jpg"],
      environment={},
      client_factory=lambda path, *, user_agent=None: pytest.fail("a client was opened"),
      stdout=io.StringIO(),
      stderr=io.StringIO(),
   )

   assert code == 2


def test_the_cli_prints_the_orphan_note_with_the_error() -> None:
   """Catches the note naming the orphaned upload dropped between the library and the user."""

   failure = UpstreamRejected("refused", code="a_refusal")
   failure.add_note("posting: every upload applied and the publish failed")

   class FailingMedia(RecordingMedia):
      def publish_photo(self, image: object, *, caption: str = "") -> PublishedPost:
         raise failure

   client = RecordingClient([])
   client.media = FailingMedia(client)

   code, _, errors = run_cli(["publish-photo", "slide.jpg"], client)

   assert code == 6
   assert "the publish failed" in errors
