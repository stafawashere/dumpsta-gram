"""Gates on follow, unfollow and the relationship read, the Step 17 table in the build plan.

Six defect classes live here.

The write can name the account by a username, which the mutations were never observed taking,
or by some identifier other than the numeric id.

Follow and unfollow can be crossed, since they share one variable and differ only in their
document.

An answer can be misread. A follow of a private account becomes a request that leaves
``following`` false, so a follow answered false must not be reported as a failure, while an
unfollow answered true did not apply.

The relationship read can report the wrong state, which is the one thing a follow is confirmed
by, and a requested follow can collapse into not following.

A write can leave by a path other than ``send_write``, or be sent again after an error answer.

And the request can drift from the one the engine replayed live, which is the parity gate for
this step. A browser sends more around a follow, a burst nobody has recorded because ruling 23
allowed no browser load, so the gate holds the one request's shape.

Every response is canned, and the account id is synthetic. Nothing in this file touches the
network.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import pytest

from dumpstagram._cli.main import main
from dumpstagram._cli.render import describe_profile
from dumpstagram._core.pacer import PacingPolicy, WritePolicy
from dumpstagram._core.writes.follows import follow_user, unfollow_user
from dumpstagram._private.transport import Request
from dumpstagram._private.web.parse import parse_profile
from dumpstagram.errors import SchemaChanged, UpstreamRejected
from dumpstagram.models import FriendshipStatus
from dumpstagram.session import Session
from tests.test_direct import (
   ScriptedTransport,
   a_bootstrapped_session,
   json_response,
   make_paced,
   sent_variables,
)
from tests.test_profiles import profile_payload

API_GRAPHQL = "https://www.instagram.com/api/graphql"
HOME = "https://www.instagram.com/"

TARGET_ID = "1111111111"
TARGET_USERNAME = "an_account"

FOLLOW_DOC_ID = "27767812149509802"
UNFOLLOW_DOC_ID = "25174972798866458"

NOT_FOLLOWING = {
   "blocking": False,
   "followed_by": False,
   "following": False,
   "incoming_request": False,
   "is_bestie": False,
   "is_feed_favorite": False,
   "is_muting_reel": False,
   "is_restricted": False,
   "muting": False,
   "outgoing_request": False,
}
"""The ten flags another account's profile carried before and after each cycle on 2026-09-23."""

FOLLOWING = {**NOT_FOLLOWING, "following": True}
"""The same ten after each follow of that public account, only ``following`` moved."""

REQUESTED = {**NOT_FOLLOWING, "outgoing_request": True}
"""A pending request to a private account. Constructed, not recorded: the account the step ran
against is public, so no pending request has been observed."""


def other_account_profile(friendship_status: Any) -> dict[str, Any]:
   """Another account's profile as the six reads of 2026-09-23 typed it: three flags null that
   the viewer's own profile carries as booleans, and a relationship object. Synthetic values."""

   return profile_payload(
      id=TARGET_ID,
      pk=TARGET_ID,
      is_private=False,
      is_professional_account=None,
      has_profile_pic=None,
      has_story_archive=None,
      mutual_followers_count=0,
      friendship_status=friendship_status,
   )


def write_answer(root_field: str, *, following: bool, echoed_id: str = TARGET_ID) -> dict[str, Any]:
   """The 215 and 217 byte answers observed on 2026-09-23, the account id echoed."""

   return {
      "data": {root_field: {"friendship_status": {"following": following}, "id": echoed_id}},
      "extensions": {"is_final": True},
   }


def body_of(request: Request) -> dict[str, list[str]]:
   return parse_qs(request.content.decode("utf-8")) if request.content else {}


@pytest.mark.parametrize(
   ("flags", "following", "outgoing_request"),
   [(NOT_FOLLOWING, False, False), (FOLLOWING, True, False), (REQUESTED, False, True)],
)
def test_the_relationship_read_maps_each_state(
   flags: dict[str, bool], following: bool, outgoing_request: bool
) -> None:
   """Catches a requested follow collapsed into not following, and ``following`` read from
   another flag or defaulted, which would confirm a follow that never happened."""

   profile = parse_profile(other_account_profile(flags))

   assert profile.friendship_status == FriendshipStatus(
      following=following,
      followed_by=False,
      outgoing_request=outgoing_request,
      incoming_request=False,
      blocking=False,
      muting=False,
      is_muting_reel=False,
      is_restricted=False,
      is_bestie=False,
      is_feed_favorite=False,
   )


def test_the_viewers_own_profile_carries_no_relationship() -> None:
   """Catches the viewer's own null read as a relationship with oneself."""

   assert parse_profile(profile_payload()).friendship_status is None


def test_another_accounts_null_flags_read_as_the_model_defaults() -> None:
   """Catches the three flags another account sends as null refusing the whole profile, which
   left no profile but the viewer's own readable."""

   profile = parse_profile(other_account_profile(NOT_FOLLOWING))

   assert profile.is_professional_account is False
   assert profile.has_profile_pic is True
   assert profile.has_story_archive is False


def test_a_flag_that_is_neither_boolean_nor_null_still_raises() -> None:
   """Catches the null allowance widened into accepting anything."""

   with pytest.raises(SchemaChanged):
      parse_profile(profile_payload(has_profile_pic="yes"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
   ("write", "doc_id", "friendly_name", "root_field", "following"),
   [
      (
         follow_user,
         FOLLOW_DOC_ID,
         "usePolarisFollowUserFollowMutation",
         "xdt_create_friendship",
         True,
      ),
      (
         unfollow_user,
         UNFOLLOW_DOC_ID,
         "usePolarisFollowUserUnfollowMutation",
         "xdt_destroy_friendship",
         False,
      ),
   ],
)
async def test_each_write_sends_the_request_the_engine_replayed(
   write: Any, doc_id: str, friendly_name: str, root_field: str, following: bool
) -> None:
   """The parity gate for the writes, and the gate that follow and unfollow send different
   documents. Catches a crossed document, a variable no send carried, another referer, and a
   request going out beside the write."""

   transport = ScriptedTransport([json_response(write_answer(root_field, following=following))])

   await write(make_paced(transport), a_bootstrapped_session(), TARGET_ID)

   assert len(transport.sent) == 1

   request = transport.sent[0]
   body = body_of(request)

   assert request.url == API_GRAPHQL
   assert body["doc_id"] == [doc_id]
   assert body["fb_api_req_friendly_name"] == [friendly_name]
   assert request.headers["x-fb-friendly-name"] == friendly_name
   assert sent_variables(request) == {"target_user_id": TARGET_ID}
   assert request.headers["referer"] == HOME


@pytest.mark.asyncio
@pytest.mark.parametrize("write", [follow_user, unfollow_user])
async def test_a_username_is_refused_before_anything_is_sent(write: Any) -> None:
   """Catches a username passed through to the upstream, whose answer to it is unobserved."""

   transport = ScriptedTransport([])

   with pytest.raises(ValueError):
      await write(make_paced(transport), a_bootstrapped_session(), TARGET_USERNAME)

   assert transport.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
   ("write", "root_field", "following"),
   [(follow_user, "xdt_create_friendship", True), (unfollow_user, "xdt_destroy_friendship", False)],
)
async def test_both_writes_depart_only_through_the_write_slot(
   write: Any, root_field: str, following: bool
) -> None:
   """Catches a write sent with ``sender.send`` rather than ``send_write``. On an account whose
   writes are stopped the write slot refuses before the transport sees anything, and an
   ordinary send does not."""

   transport = ScriptedTransport([json_response(write_answer(root_field, following=following))])
   sender = make_paced(transport)
   sender.pacer.stop_writes()

   with pytest.raises(UpstreamRejected):
      await write(sender, a_bootstrapped_session(), TARGET_ID)

   assert transport.sent == []


@pytest.mark.asyncio
async def test_an_error_envelope_on_a_follow_raises_and_departs_once() -> None:
   """Catches a follow sent again after the upstream answered it with an error. The write stop
   is turned off here, because with it on the pacer would refuse the second send and hide a
   capability that retries."""

   envelope = {"error": "a_code_no_finding_explains"}
   transport = ScriptedTransport([json_response(envelope), json_response(envelope)])
   sender = make_paced(transport).with_pacing(
      PacingPolicy(), WritePolicy(stop_after_unrecognised_rejection=False)
   )

   with pytest.raises(UpstreamRejected):
      await follow_user(sender, a_bootstrapped_session(), TARGET_ID)

   assert len(transport.sent) == 1


@pytest.mark.asyncio
async def test_a_follow_answered_not_following_is_not_a_failure() -> None:
   """Catches every follow that does not answer following being raised, which would report a
   follow request to a private account as a refusal the caller might send again."""

   answer = write_answer("xdt_create_friendship", following=False)
   transport = ScriptedTransport([json_response(answer)])

   await follow_user(make_paced(transport), a_bootstrapped_session(), TARGET_ID)

   assert len(transport.sent) == 1


@pytest.mark.asyncio
async def test_an_unfollow_answered_still_following_is_not_taken_as_applied() -> None:
   """Catches an unfollow reported as done when the upstream's own answer says it follows."""

   answer = write_answer("xdt_destroy_friendship", following=True)
   transport = ScriptedTransport([json_response(answer)])

   with pytest.raises(UpstreamRejected):
      await unfollow_user(make_paced(transport), a_bootstrapped_session(), TARGET_ID)


@pytest.mark.asyncio
async def test_an_answer_about_another_account_is_a_schema_change() -> None:
   """Catches an answer echoing some other account id taken as an answer about this one."""

   answer = write_answer("xdt_create_friendship", following=True, echoed_id="2222222222")
   transport = ScriptedTransport([json_response(answer)])

   with pytest.raises(SchemaChanged):
      await follow_user(make_paced(transport), a_bootstrapped_session(), TARGET_ID)


class RecordingClient:
   def __init__(self) -> None:
      self.session = Session(sessionid="s", ds_user_id="1234567890", csrftoken="c")
      self.calls: list[tuple[str, str]] = []

   def follow(self, user_id: str) -> None:
      self.calls.append(("follow", user_id))

   def unfollow(self, user_id: str) -> None:
      self.calls.append(("unfollow", user_id))

   def close(self) -> None:
      pass


def run_cli(argv: list[str], client: RecordingClient) -> tuple[int, str]:
   out = io.StringIO()

   def factory(path: Path, *, user_agent: str | None = None) -> Any:
      return client

   code = main(argv, environment={}, client_factory=factory, stdout=out, stderr=io.StringIO())

   return code, out.getvalue()


@pytest.mark.parametrize("verb", ["follow", "unfollow"])
def test_the_cli_sends_the_named_account_to_the_named_write(verb: str) -> None:
   """Catches the CLI crossing follow and unfollow, or writing to anything but the id given."""

   client = RecordingClient()

   code, out = run_cli(["--json", "--session", "s.json", verb, TARGET_ID], client)

   assert code == 0
   assert client.calls == [(verb, TARGET_ID)]
   assert json.loads(out) == {"command": verb, "user_id": TARGET_ID}


def test_the_cli_refuses_a_username_before_opening_a_client() -> None:
   """Catches a username reaching a client, where it would become a live request."""

   client = RecordingClient()

   with pytest.raises(SystemExit) as raised:
      run_cli(["--session", "s.json", "follow", TARGET_USERNAME], client)

   assert raised.value.code == 2
   assert client.calls == []


def test_the_profile_json_carries_the_relationship() -> None:
   """Catches the relationship dropped from ``dumpsta profile --json``, the CLI's only way to
   confirm a follow."""

   described = describe_profile(parse_profile(other_account_profile(REQUESTED)))

   assert described["friendship_status"] == REQUESTED
