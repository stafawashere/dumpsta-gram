"""Gates for the classifier.

The defects this layer can produce are a status-code branch, an unrecognised envelope passing
as a payload, the HTML application shell parsing as an empty result, and a checkpoint decided
from user content. The last one is the expensive one: a checkpoint is never retried, so a
false positive makes an operation permanently unfinishable rather than slow.
"""

from __future__ import annotations

import json

import pytest

from dumpstagram._private.transport import Response
from dumpstagram._private.web.classify import classify, classify_preloaded
from dumpstagram.errors import CheckpointRequired, SchemaChanged, UpstreamRejected


def make_response(
   body: str | bytes,
   *,
   status_code: int = 200,
   final_url: str = "https://www.instagram.com/graphql/query",
   headers: dict[str, str] | None = None,
   history_urls: tuple[str, ...] = (),
) -> Response:
   content = body.encode() if isinstance(body, str) else body
   base_headers = {"content-type": "application/json; charset=utf-8"}
   base_headers.update(headers or {})

   return Response(
      status_code=status_code,
      headers=base_headers,
      content=content,
      final_url=final_url,
      history_urls=history_urls,
   )


def test_a_500_carrying_a_payload_is_a_success() -> None:
   """Catches a status branch being added, which would reject a payload the caller can use."""
   response = make_response(json.dumps({"data": {"ok": True}}), status_code=500)

   assert classify(response) == {"data": {"ok": True}}


def test_a_200_carrying_an_envelope_is_a_failure() -> None:
   """The positive control for the gate above: the body decides, not the status."""
   response = make_response(json.dumps({"errors": [{"code": 1357004}]}), status_code=200)

   with pytest.raises(UpstreamRejected) as caught:
      classify(response)

   assert caught.value.code == "1357004"


def test_the_jsonp_prefix_is_stripped_before_parsing() -> None:
   """Catches the prefix reaching the parser, which would report a schema change instead."""
   response = make_response('for (;;);{"data": {"ok": true}}')

   assert classify(response) == {"data": {"ok": True}}


def test_the_error_field_envelope_is_detected() -> None:
   """Catches the `error` branch being dropped, which would return a failure as a payload."""
   response = make_response(json.dumps({"error": "invalid_token"}))

   with pytest.raises(UpstreamRejected) as caught:
      classify(response)

   assert caught.value.code == "invalid_token"


def test_the_error_summary_envelope_is_detected() -> None:
   """Catches the `errorSummary` branch being dropped. This is the named mutation."""
   response = make_response(json.dumps({"errorSummary": "Something went wrong"}))

   with pytest.raises(UpstreamRejected) as caught:
      classify(response)

   assert caught.value.code == "errorSummary"


def test_a_null_error_field_beside_a_payload_is_not_an_envelope() -> None:
   """Catches a truthiness mistake that would reject every successful response."""
   response = make_response(json.dumps({"data": {"ok": True}, "error": None, "errors": []}))

   assert classify(response) == {"data": {"ok": True}, "error": None, "errors": []}


def test_the_html_app_shell_raises_rather_than_parsing_as_empty() -> None:
   """Catches the shell being returned as a success, which reads as an empty result."""
   response = make_response(
      "<!DOCTYPE html><html><body>Instagram</body></html>",
      headers={"content-type": "text/html"},
   )

   with pytest.raises(UpstreamRejected) as caught:
      classify(response)

   assert caught.value.code == "html_app_shell"


def test_unparseable_json_is_a_schema_change_not_a_transport_failure() -> None:
   """Catches a bare parse error escaping, or the body being guessed at instead."""
   response = make_response('{"data": {"ok":')

   with pytest.raises(SchemaChanged):
      classify(response)


def test_a_payload_containing_the_challenge_literal_is_not_a_checkpoint() -> None:
   """Catches an unconditional body scan, the defect that made the prior guard unusable.

   A message quoting `/challenge/` is ordinary user content. Because a checkpoint is never
   retried, firing here does not slow an operation, it ends it permanently.
   """
   payload = {"data": {"message": {"text": "look at instagram.com/challenge/ lol"}}}
   response = make_response(json.dumps(payload))

   assert classify(response) == payload


def test_a_redirect_to_the_challenge_url_is_a_checkpoint() -> None:
   """The positive control: the same literal in the URL, where user content cannot appear."""
   response = make_response(
      json.dumps({"data": {"ok": True}}),
      final_url="https://www.instagram.com/challenge/?next=/direct/inbox/",
   )

   with pytest.raises(CheckpointRequired):
      classify(response)


def test_a_location_header_pointing_at_the_challenge_is_a_checkpoint() -> None:
   """Catches the header being ignored when redirects are not followed."""
   response = make_response(
      "",
      status_code=302,
      headers={"location": "https://www.instagram.com/challenge/action/"},
   )

   with pytest.raises(CheckpointRequired):
      classify(response)


def test_a_redirect_in_the_history_is_a_checkpoint() -> None:
   """Catches only the final URL being read after a redirect chain lands somewhere innocent."""
   response = make_response(
      json.dumps({"data": {"ok": True}}),
      final_url="https://www.instagram.com/accounts/login/",
      history_urls=("https://www.instagram.com/challenge/",),
   )

   with pytest.raises(CheckpointRequired):
      classify(response)


def test_an_envelope_naming_a_challenge_is_a_checkpoint_not_a_rejection() -> None:
   """Catches a checkpoint body being reported as a generic rejection, which `_core` retries."""
   response = make_response(json.dumps({"error": "challenge_required"}))

   with pytest.raises(CheckpointRequired):
      classify(response)


def test_the_app_shell_of_a_challenge_page_is_a_checkpoint_not_a_rejection() -> None:
   """Catches the shell branch short-circuiting the body scan it is allowed to perform."""
   response = make_response(
      "<!DOCTYPE html><html><body>checkpoint_required</body></html>",
      headers={"content-type": "text/html"},
   )

   with pytest.raises(CheckpointRequired):
      classify(response)


GRID_ROOT = "xdt_api__v1__feed__user_timeline_graphql_connection"
POST_ROOT = "xdt_api__v1__media__media_id_web_info"


def field_error(path: list[object], severity: str = "ERROR") -> dict[str, object]:
   return {"message": "A server error field_exception occured.", "severity": severity, "path": path}


def grid_answer(errors: list[dict[str, object]], *, caption: str = "") -> dict[str, object]:
   """The shape the profile grid answered with on 2026-09-27: whole edges, the errored location
   picture null, and one error per errored field."""

   node = {
      "pk": "1",
      "caption": {"text": caption},
      "location": {"pk": "2", "profile_pic_url": None},
   }

   return {
      "data": {
         GRID_ROOT: {"edges": [{"node": node}], "page_info": {"has_next_page": False}},
         "xdt_viewer": {"user": {"id": "3"}},
      },
      "errors": errors,
   }


def test_field_errors_beside_a_root_that_answered_are_a_partial_answer() -> None:
   """Catches the grid refused whole for one errored location picture per post, as the shipped
   classifier did on 2026-09-27, and the post read's UNSET errors refused the same way."""

   grid = grid_answer([field_error([GRID_ROOT, "edges", 0, "node", "location", "profile_pic_url"])])
   post = {
      "data": {POST_ROOT: {"items": [{"ad_id": None, "user": {"friendship_status": {}}}]}},
      "errors": [
         field_error([POST_ROOT, "items", 0, "ad_id"], severity="UNSET"),
         field_error([POST_ROOT, "items", 0, "user", "friendship_status", "muting"], "UNSET"),
      ],
      "status": "ok",
   }

   assert classify(make_response(json.dumps(grid))) == grid
   assert classify(make_response(json.dumps(post))) == post


@pytest.mark.parametrize(
   "errors",
   [
      pytest.param([{"message": "a failure", "severity": "ERROR"}], id="no path"),
      pytest.param([field_error([GRID_ROOT])], id="a path of one element"),
      pytest.param([field_error(["absent_root", "edges", 0])], id="a root the data lacks"),
      pytest.param(
         [
            field_error([GRID_ROOT, "edges", 0, "node", "location", "profile_pic_url"]),
            {"message": "a failure", "severity": "ERROR"},
         ],
         id="one field error beside one with no path",
      ),
   ],
)
def test_an_error_that_is_not_a_field_error_beside_an_answer_is_still_refused(
   errors: list[dict[str, object]],
) -> None:
   """Catches the partial answer rule widened past field errors: an error with no path, one
   naming the root itself, one naming a root that is not there, and a pathless error hidden
   behind a field error."""

   with pytest.raises(UpstreamRejected) as caught:
      classify(make_response(json.dumps(grid_answer(errors))))

   assert caught.value.code == "errors"


def test_a_field_error_under_a_null_root_is_refused() -> None:
   """Catches a root that did not answer taken for one that did, because the error's path is
   long enough. The control is the same error beside the root present."""

   path = [GRID_ROOT, "edges", 0, "node", "location", "profile_pic_url"]
   answered = grid_answer([field_error(path)])
   null_root = {"data": {GRID_ROOT: None}, "errors": [field_error(path)]}

   assert classify(make_response(json.dumps(answered))) == answered

   with pytest.raises(UpstreamRejected):
      classify(make_response(json.dumps(null_root)))


def test_a_partial_answer_quoting_the_challenge_path_is_not_a_checkpoint() -> None:
   """Catches the body scan run over a partial answer, which carries user content: a caption
   quoting ``/challenge/`` would end the read for good."""

   path = [GRID_ROOT, "edges", 0, "node", "location", "profile_pic_url"]
   answer = grid_answer([field_error(path)], caption="see instagram.com/challenge/ now")

   assert classify(make_response(json.dumps(answer))) == answer


def test_a_preloaded_result_follows_the_same_partial_answer_rule() -> None:
   """Catches the preloaded reader left refusing a partial answer, or accepting a pathless
   error because it reads the envelope another way."""

   path = [GRID_ROOT, "edges", 0, "node", "location", "profile_pic_url"]
   partial = grid_answer([field_error(path)])
   refused = grid_answer([{"message": "a failure", "severity": "ERROR"}])

   assert classify_preloaded(partial) == partial

   with pytest.raises(UpstreamRejected):
      classify_preloaded(refused)
