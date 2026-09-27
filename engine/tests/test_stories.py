"""Gates on stories: the tray, one account's live stories and one highlight, E2 batch 5, and
marking an item seen, E2 batch 12.

Six defect classes live here.

A read can mark the wrong thing seen, or fail to mark what a browser marks. Under the default
behavior a reel or highlight read marks its first item and nothing else, the tray marks nothing,
and ``mark_stories_seen`` off marks nothing at all (W94).

The seen mutation can drift from what the browser sent, pair an item with another reel, take a
null answer as marked, or leave by a path other than the write slot, where it would escape the
budget or be sent twice (W93).

A mapper can read a field from the wrong key or invent one the answer does not carry. The tray
carries no items and a reel read no high resolution picture, a story video carries no dimensions,
and a tray's zero ``seen`` means never seen rather than 1970.

An empty answer can be misread. An account with no live story answers no reel, which is ``None``,
and a highlight that answers no reel is ``NotFound``; more than one reel for one id is the
upstream changing.

A request can go to the wrong path, carry other variables, or accept an identifier it should
refuse before sending.

And a command can take a username where an id is meant, drop items in either output form, mark
when told not to, or mark an item other than the one named.

The payloads are the recorded answers of 2026-09-27, pseudonymised by
``scripts/build_stories_fixtures.py``, and the seen answer, which carries nothing personal. No
live reel was recorded, so the live reel here is the recorded highlight with its id and type
recast. Nothing in this file touches the network.
"""

from __future__ import annotations

import copy
import io
import json
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import pytest

from dumpstagram._cli.main import main
from dumpstagram._core.pacer import Pacer, PacingPolicy, WritePolicy
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.stories import read_highlight, read_stories_tray, read_story_reel
from dumpstagram._core.writes.stories import mark_story_item_seen
from dumpstagram._private.web.documents.catalog import (
   COMPANION_QUERIES,
   READ_QUERIES,
   WRITE_QUERIES,
)
from dumpstagram._private.web.parse.stories import (
   parse_highlight_reel,
   parse_stories_tray,
   parse_story_reel,
)
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY
from dumpstagram.errors import (
   NotFound,
   OutcomeUnknown,
   RateLimited,
   SchemaChanged,
   TransportFailure,
   UpstreamRejected,
)
from dumpstagram.models import StoryItem, StoryReel, TrayReel
from dumpstagram.session import Session
from tests.test_direct import (
   FakeClock,
   ScriptedTransport,
   a_bootstrapped_session,
   json_response,
   make_paced,
   sent_variables,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "stories"

GRAPHQL_QUERY = "https://www.instagram.com/graphql/query"
API_GRAPHQL = "https://www.instagram.com/api/graphql"
SITE_ROOT = "https://www.instagram.com/"
TRAY_ROOT = "xdt_api__v1__feed__reels_tray"
REELS_ROOT = "xdt_api__v1__feed__reels_media"
TRAY_DOC_ID = "27703822975903310"
REEL_DOC_ID = "29184890191114309"
PROVIDER = "__relay_internal__pv__PolarisCommunityNoteStoriesLabelEnabledrelayprovider"
USER_ID = "81234567"
SEEN_MUTATIONS = (
   "PolarisStoriesV3SeenMutation",
   "PolarisAPIReelSeenMutation",
   "PolarisAPIForceStorySeenMutation",
)

SCRIPTED_BEHAVIOR = replace(PARITY, cookie_sync=False)


def recorded(name: str) -> Any:
   return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def tray_rows() -> list[dict[str, Any]]:
   rows: list[dict[str, Any]] = recorded("stories_tray.json")["data"][TRAY_ROOT]["tray"]

   return rows


def highlight_node() -> dict[str, Any]:
   node: dict[str, Any] = recorded("highlight.json")["data"][REELS_ROOT]["reels_media"][0]

   return node


def highlight_id() -> str:
   return str(highlight_node()["id"])


def at(seconds: int) -> datetime:
   return datetime.fromtimestamp(seconds, tz=UTC)


def sent_field(request: Any, name: str) -> str:
   return parse_qs(request.content.decode("utf-8"))[name][0]


def friendly_names(transport: ScriptedTransport) -> list[str]:
   return [sent_field(request, "fb_api_req_friendly_name") for request in transport.sent]


def test_the_tray_maps_every_row_in_order_with_its_owner_and_its_times() -> None:
   """Catches rows dropped or reordered, the owner read from the row's own id, a time read from
   another key, and a zero ``seen`` read as a time in 1970 rather than as never seen."""

   rows = tray_rows()
   tray = parse_stories_tray(recorded("stories_tray.json"))

   assert len(tray) == 33
   assert all(isinstance(reel, TrayReel) for reel in tray)
   assert [reel.id for reel in tray] == [row["id"] for row in rows]
   assert [reel.owner.id for reel in tray] == [row["user"]["pk"] for row in rows]
   assert [reel.owner.username for reel in tray] == [row["user"]["username"] for row in rows]
   assert [reel.owner.hd_profile_pic_url for reel in tray] == [
      row["user"]["hd_profile_pic_url_info"]["url"] for row in rows
   ]
   assert {(reel.owner.is_verified, reel.owner.is_private) for reel in tray} == {(None, None)}
   assert [reel.ranked_position for reel in tray] == [row["ranked_position"] for row in rows]
   assert [reel.latest_item_at for reel in tray] == [at(row["latest_reel_media"]) for row in rows]
   assert [reel.expiring_at for reel in tray] == [at(row["expiring_at"]) for row in rows]
   assert [reel.seen_at for reel in tray] == [
      at(row["seen"]) if row["seen"] else None for row in rows
   ]
   assert sum(1 for reel in tray if reel.seen_at is None) == 23
   assert [reel.has_close_friends_items for reel in tray] == [
      row["has_besties_media"] for row in rows
   ]


def test_a_highlight_maps_every_item_from_its_own_keys() -> None:
   """Catches items dropped or reordered, an item's owner read from the reel, the two times
   swapped, renditions, stickers or the audience lost, and the highlight's title or cover
   dropped."""

   node = highlight_node()
   items = node["items"]
   reel = parse_highlight_reel(recorded("highlight.json"))

   assert isinstance(reel, StoryReel)
   assert reel.id == node["id"]
   assert reel.id.startswith("highlight:")
   assert reel.reel_type == "highlight_reel"
   assert reel.title == node["title"]
   assert reel.cover_url == node["cover_media"]["cropped_image_version"]["url"]
   assert reel.owner.id == node["user"]["pk"]
   assert (reel.owner.is_verified, reel.owner.is_private) == (
      node["user"]["is_verified"],
      node["user"]["is_private"],
   )
   assert reel.owner.hd_profile_pic_url is None
   assert reel.latest_item_at == at(node["latest_reel_media"])
   assert len(reel.items) == 18
   assert [item.pk for item in reel.items] == [item["pk"] for item in items]
   assert [item.id for item in reel.items] == [item["id"] for item in items]
   assert [item.code for item in reel.items] == [item["code"] for item in items]
   assert [item.owner_id for item in reel.items] == [item["user"]["pk"] for item in items]
   assert [item.taken_at for item in reel.items] == [at(item["taken_at"]) for item in items]
   assert [item.expiring_at for item in reel.items] == [at(item["expiring_at"]) for item in items]
   assert [item.media_type for item in reel.items] == [item["media_type"] for item in items]
   assert [item.audience for item in reel.items] == [item["audience"] for item in items]
   assert [item.audience for item in reel.items].count("besties") == 2
   assert [len(item.images) for item in reel.items] == [
      len(item["image_versions2"]["candidates"]) for item in items
   ]
   assert [[video.version_type for video in item.videos] for item in reel.items] == [
      [version["type"] for version in item["video_versions"] or []] for item in items
   ]
   assert [item.video_duration for item in reel.items] == [item["video_duration"] for item in items]
   assert sum(len(item.mentions) for item in reel.items) == 4
   assert [[mention.username for mention in item.mentions] for item in reel.items] == [
      [
         sticker["bloks_sticker"]["sticker_data"]["ig_mention"]["username"]
         for sticker in item["story_bloks_stickers"] or []
      ]
      for item in items
   ]
   assert sum(len(item.music) for item in reel.items) == 11
   assert [[track.title for track in item.music] for item in reel.items] == [
      [sticker["music_asset_info"]["title"] for sticker in item["story_music_stickers"] or []]
      for item in items
   ]


def test_a_photo_item_carries_no_video_and_a_null_audio_flag_reads_as_unknown() -> None:
   """Catches a photo given renditions or a duration, and a null ``has_audio`` read as False."""

   reel = parse_highlight_reel(recorded("highlight.json"))
   photos = [item for item in reel.items if item.media_type == 1]
   videos = [item for item in reel.items if item.media_type == 2]

   assert len(photos) == 1
   assert photos[0].videos == ()
   assert photos[0].video_duration is None
   assert photos[0].has_audio is None
   assert all(len(item.videos) == 3 for item in videos)
   assert {item.has_audio for item in videos} == {True}


def test_no_live_story_is_none_and_a_highlight_with_no_reel_is_not_found() -> None:
   """Catches an empty answer read as a reel, or a missing highlight returned as ``None`` where
   the method promises a reel."""

   assert parse_story_reel(recorded("own_reel_empty.json")) is None

   with pytest.raises(NotFound):
      parse_highlight_reel(recorded("own_reel_empty.json"))


def test_more_than_one_reel_for_one_id_is_a_schema_change() -> None:
   """Catches a second reel silently dropped when one id was asked."""

   payload = copy.deepcopy(recorded("highlight.json"))
   reels = payload["data"][REELS_ROOT]["reels_media"]
   reels.append(copy.deepcopy(reels[0]))

   with pytest.raises(SchemaChanged, match="2 reels"):
      parse_story_reel(payload)

   with pytest.raises(SchemaChanged, match="2 reels"):
      parse_highlight_reel(payload)


def test_a_story_video_without_its_type_is_a_schema_change() -> None:
   """Catches a rendition read without the one field besides its address that it carries."""

   payload = copy.deepcopy(recorded("highlight.json"))
   del payload["data"][REELS_ROOT]["reels_media"][0]["items"][0]["video_versions"][0]["type"]

   with pytest.raises(SchemaChanged, match="video_versions"):
      parse_highlight_reel(payload)


@pytest.mark.asyncio
async def test_the_three_reads_send_the_variables_replayed_live() -> None:
   """The parity gate for the stories reads. Catches another path, another query, the highlight
   flag left off a highlight or put on a reel, a missing root field header, or another
   referer."""

   transport = ScriptedTransport(
      [
         json_response(recorded("stories_tray.json")),
         json_response(recorded("own_reel_empty.json")),
         json_response(recorded("highlight.json")),
      ]
   )
   sender = make_paced(transport)
   session = a_bootstrapped_session()

   tray = await read_stories_tray(sender, session)
   reel = await read_story_reel(sender, session, USER_ID)
   highlight = await read_highlight(sender, session, highlight_id())

   assert len(tray) == 33
   assert reel is None
   assert len(highlight.items) == 18
   assert [request.url for request in transport.sent] == [
      API_GRAPHQL,
      GRAPHQL_QUERY,
      GRAPHQL_QUERY,
   ]
   assert [sent_field(request, "doc_id") for request in transport.sent] == [
      TRAY_DOC_ID,
      REEL_DOC_ID,
      REEL_DOC_ID,
   ]
   assert sent_variables(transport.sent[0]) == {
      "data": {"is_following_feed": False},
      "suggestedUsersData": {
         "max_id": "",
         "max_number_to_display": 0,
         "module": "stories_tray",
         "paginate": False,
      },
   }
   assert sent_variables(transport.sent[1]) == {"reel_ids_arr": [USER_ID], PROVIDER: True}
   assert sent_variables(transport.sent[2]) == {
      "reel_ids_arr": [highlight_id()],
      "is_highlight": True,
      PROVIDER: True,
   }
   assert "x-root-field-name" not in transport.sent[0].headers
   assert transport.sent[1].headers["x-root-field-name"] == REELS_ROOT
   assert transport.sent[2].headers["x-root-field-name"] == REELS_ROOT
   assert {request.headers["referer"] for request in transport.sent} == {SITE_ROOT}


@pytest.mark.asyncio
async def test_a_username_and_a_bare_highlight_number_are_refused_before_anything_is_sent() -> None:
   """Catches an identifier reaching the request unchecked."""

   transport = ScriptedTransport([])
   sender = make_paced(transport)
   session = a_bootstrapped_session()
   bare_number = highlight_id().removeprefix("highlight:")

   with pytest.raises(ValueError, match="numeric account id"):
      await read_story_reel(sender, session, "someone")

   with pytest.raises(ValueError, match="highlight id"):
      await read_highlight(sender, session, bare_number)

   with pytest.raises(ValueError, match="highlight id"):
      await read_highlight(sender, session, f"{highlight_id()}x")

   assert transport.sent == []


SEEN_DOC_ID = "26234228992942885"
SEEN_ROOT = "xdt_mark_story_reel_seen"
SEEN_ANSWER = {"data": {SEEN_ROOT: {"__typename": "XDTMarkSeenResponse"}}, "extensions": {}}
"""The 196 byte answer the browser and the engine replay both received on 2026-09-27, its
``server_metadata`` times left out. ``__typename`` was the root's only field on both."""

VIEWED_AT = 1790533419


def a_live_reel() -> dict[str, Any]:
   """The recorded highlight recast as one account's live reel: its id the owner's account id
   and its type ``user_reel``, as the tray's rows carry them. No live reel was recorded (W70),
   so this is constructed, and only the reel's id and type differ from the recording."""

   payload = copy.deepcopy(recorded("highlight.json"))
   node = payload["data"][REELS_ROOT]["reels_media"][0]
   node["id"] = node["user"]["pk"]
   node["reel_type"] = "user_reel"

   return payload


def seen_variables_for(node: dict[str, Any], index: int, viewed_at: int) -> dict[str, Any]:
   """The five variables the browser sent, taken from the recorded answer rather than the
   mapper, so a mapper reading a field from the wrong key is caught here too."""

   item = node["items"][index]

   return {
      "reelId": node["id"],
      "reelMediaId": item["pk"],
      "reelMediaOwnerId": item["user"]["pk"],
      "reelMediaTakenAt": item["taken_at"],
      "viewSeenAt": viewed_at,
   }


@pytest.mark.asyncio
async def test_the_seen_mutation_sends_the_five_variables_the_browser_sent() -> None:
   """The parity gate for the seen mutation. Catches another document or path, a variable
   renamed, reordered in meaning, sent as another type or read off the wrong item, a root field
   header the browser did not send, and another referer."""

   node = highlight_node()
   highlight = parse_highlight_reel(recorded("highlight.json"))
   live = parse_story_reel(a_live_reel())
   transport = ScriptedTransport([json_response(SEEN_ANSWER), json_response(SEEN_ANSWER)])
   sender = make_paced(transport)
   session = a_bootstrapped_session()

   assert live is not None

   await mark_story_item_seen(
      sender, session, highlight, highlight.items[1], clock=lambda: VIEWED_AT + 0.9
   )
   await mark_story_item_seen(sender, session, live, live.items[2], clock=lambda: VIEWED_AT)

   highlight_number = node["id"].removeprefix("highlight:")
   live_node = a_live_reel()["data"][REELS_ROOT]["reels_media"][0]

   assert [request.url for request in transport.sent] == [API_GRAPHQL, API_GRAPHQL]
   assert [sent_field(request, "doc_id") for request in transport.sent] == [SEEN_DOC_ID] * 2
   assert [sent_field(request, "fb_api_req_friendly_name") for request in transport.sent] == [
      "PolarisStoriesV3SeenMutation"
   ] * 2
   assert sent_variables(transport.sent[0]) == seen_variables_for(node, 1, VIEWED_AT)
   assert sent_variables(transport.sent[1]) == seen_variables_for(live_node, 2, VIEWED_AT)
   assert live_node["id"] == node["user"]["pk"]
   assert all("x-root-field-name" not in request.headers for request in transport.sent)
   assert transport.sent[0].headers["referer"] == (
      f"https://www.instagram.com/stories/highlights/{highlight_number}/"
   )
   assert transport.sent[1].headers["referer"] == SITE_ROOT


@pytest.mark.asyncio
async def test_an_item_from_another_reel_is_refused_before_anything_is_sent() -> None:
   """Catches an item paired with a reel it was not read in, which would send one reel's id
   with another item's owner."""

   highlight = parse_highlight_reel(recorded("highlight.json"))
   stranger = replace(highlight.items[0], pk="1", owner_id="2")
   transport = ScriptedTransport([])

   with pytest.raises(ValueError, match="not one of the items"):
      await mark_story_item_seen(
         make_paced(transport), a_bootstrapped_session(), highlight, stranger
      )

   assert transport.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
   ("answer", "raised", "code"),
   [
      ({"data": {SEEN_ROOT: None}, "extensions": {}}, UpstreamRejected, "story_not_marked_seen"),
      ({"data": {}, "extensions": {}}, SchemaChanged, None),
      ({"data": {SEEN_ROOT: {"__typename": "XDTSomethingElse"}}}, SchemaChanged, None),
      ({"data": {SEEN_ROOT: "yes"}}, SchemaChanged, None),
   ],
)
async def test_an_answer_that_is_not_the_seen_response_raises(
   answer: dict[str, Any], raised: type[Exception], code: str | None
) -> None:
   """Catches a null root, a missing root or another type taken as marked, which would tell a
   caller an item was marked when the answer, the only confirmation there is, did not say so."""

   highlight = parse_highlight_reel(recorded("highlight.json"))
   transport = ScriptedTransport([json_response(answer)])

   with pytest.raises(raised) as failure:
      await mark_story_item_seen(
         make_paced(transport), a_bootstrapped_session(), highlight, highlight.items[0]
      )

   if code is not None:
      assert getattr(failure.value, "code", None) == code

   assert len(transport.sent) == 1


@pytest.mark.asyncio
async def test_the_seen_mutation_departs_only_through_the_write_slot() -> None:
   """Catches the mutation sent with ``sender.send`` rather than ``send_write``. On an account
   whose writes are stopped the write slot refuses before the transport sees anything."""

   highlight = parse_highlight_reel(recorded("highlight.json"))
   transport = ScriptedTransport([json_response(SEEN_ANSWER)])
   sender = make_paced(transport)
   sender.pacer.stop_writes()

   with pytest.raises(UpstreamRejected):
      await mark_story_item_seen(sender, a_bootstrapped_session(), highlight, highlight.items[0])

   assert transport.sent == []


@pytest.mark.asyncio
async def test_the_seen_mutation_counts_against_the_write_budget() -> None:
   """Catches the mutation treated as a read, which would let a stories walk mark past the
   budget the account's other writes keep to."""

   highlight = parse_highlight_reel(recorded("highlight.json"))
   transport = ScriptedTransport([json_response(SEEN_ANSWER)])
   sender = make_paced(transport).with_pacing(PacingPolicy(), WritePolicy(budget_per_hour=0))

   with pytest.raises(RateLimited):
      await mark_story_item_seen(sender, a_bootstrapped_session(), highlight, highlight.items[0])

   assert transport.sent == []


@pytest.mark.asyncio
async def test_a_rejected_or_interrupted_seen_mutation_departs_once() -> None:
   """Catches the mutation sent again after an error answer or a connection failure. The write
   stop is off, because with it on the pacer would refuse a second send and hide a retry."""

   highlight = parse_highlight_reel(recorded("highlight.json"))
   envelope = {"error": "a_code_no_finding_explains"}
   rejected = ScriptedTransport([json_response(envelope), json_response(envelope)])
   interrupted = FailingTransport([])
   policy = WritePolicy(stop_after_unrecognised_rejection=False)

   with pytest.raises(UpstreamRejected):
      await mark_story_item_seen(
         make_paced(rejected).with_pacing(PacingPolicy(), policy),
         a_bootstrapped_session(),
         highlight,
         highlight.items[0],
      )

   with pytest.raises(OutcomeUnknown):
      await mark_story_item_seen(
         make_paced(interrupted).with_pacing(PacingPolicy(), policy),
         a_bootstrapped_session(),
         highlight,
         highlight.items[0],
      )

   assert len(rejected.sent) == 1
   assert len(interrupted.sent) == 1


class FailingTransport(ScriptedTransport):
   async def send(self, request: Any) -> Any:
      self.sent.append(request)

      raise TransportFailure("the connection dropped with the write in flight")


def paced(transport: ScriptedTransport, client: AsyncClient) -> PacedSender:
   clock = FakeClock()
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)

   return PacedSender(transport, pacer, client._sender.pacing, client._sender.writes)


async def run_the_three_reads(behavior: Any, responses: list[Any]) -> ScriptedTransport:
   transport = ScriptedTransport(responses)
   client = AsyncClient(a_bootstrapped_session(), behavior=behavior)
   await client._sender.aclose()
   client._sender = paced(transport, client)

   try:
      await client.stories.tray()
      await client.stories.reel(USER_ID)
      await client.stories.highlight(highlight_id())
   finally:
      await client.aclose()

   return transport


@pytest.mark.asyncio
async def test_under_the_default_a_reel_and_a_highlight_read_mark_their_first_item_only() -> None:
   """The W94 gate. Catches a reel or highlight read that marks nothing, marks an item other
   than the first, marks every item, or marks before it has read, and a tray read that marks
   anything, which a browser's tray does not."""

   before = int(time.time())
   transport = await run_the_three_reads(
      SCRIPTED_BEHAVIOR,
      [
         json_response(recorded("stories_tray.json")),
         json_response(a_live_reel()),
         json_response(SEEN_ANSWER),
         json_response(recorded("highlight.json")),
         json_response(SEEN_ANSWER),
      ],
   )
   after = int(time.time())

   live_node = a_live_reel()["data"][REELS_ROOT]["reels_media"][0]
   highlight = highlight_node()
   live_seen = sent_variables(transport.sent[2])
   highlight_seen = sent_variables(transport.sent[4])

   assert friendly_names(transport) == [
      "PolarisStoriesV3TrayContainerQuery",
      "PolarisStoriesV3ReelPageStandaloneQuery",
      "PolarisStoriesV3SeenMutation",
      "PolarisStoriesV3ReelPageStandaloneQuery",
      "PolarisStoriesV3SeenMutation",
   ]
   assert before <= live_seen["viewSeenAt"] <= after
   assert before <= highlight_seen["viewSeenAt"] <= after
   assert live_seen == seen_variables_for(live_node, 0, live_seen["viewSeenAt"])
   assert highlight_seen == seen_variables_for(highlight, 0, highlight_seen["viewSeenAt"])


@pytest.mark.asyncio
async def test_with_marking_off_no_stories_read_sends_a_seen_mutation() -> None:
   """Catches ``mark_stories_seen=False`` ignored, and an account with no live story marked
   anyway, under the default too."""

   off = await run_the_three_reads(
      replace(SCRIPTED_BEHAVIOR, mark_stories_seen=False),
      [
         json_response(recorded("stories_tray.json")),
         json_response(a_live_reel()),
         json_response(recorded("highlight.json")),
      ],
   )
   transport = ScriptedTransport([json_response(recorded("own_reel_empty.json"))])
   client = AsyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR)
   await client._sender.aclose()
   client._sender = paced(transport, client)

   try:
      nothing_live = await client.stories.reel(USER_ID)
   finally:
      await client.aclose()

   assert friendly_names(off) == [
      "PolarisStoriesV3TrayContainerQuery",
      "PolarisStoriesV3ReelPageStandaloneQuery",
      "PolarisStoriesV3ReelPageStandaloneQuery",
   ]
   assert nothing_live is None
   assert friendly_names(transport) == ["PolarisStoriesV3ReelPageStandaloneQuery"]


@pytest.mark.asyncio
async def test_a_read_whose_mark_is_refused_raises_rather_than_returning_unmarked() -> None:
   """The W94 failure rule. Catches a reel returned as if read in parity when its first item
   was never marked, here because the write budget refused the mark."""

   transport = ScriptedTransport([json_response(recorded("highlight.json"))])
   client = AsyncClient(
      a_bootstrapped_session(), behavior=replace(SCRIPTED_BEHAVIOR, write_budget_per_hour=0)
   )
   await client._sender.aclose()
   client._sender = paced(transport, client)

   try:
      with pytest.raises(RateLimited):
         await client.stories.highlight(highlight_id())
   finally:
      await client.aclose()

   assert friendly_names(transport) == ["PolarisStoriesV3ReelPageStandaloneQuery"]


def test_only_the_seen_mutation_that_was_verified_is_registered_and_as_a_write() -> None:
   """Catches the seen mutation registered as a read or a companion, where the doctor would
   replay it, and either alternate compiled route registered without a finding (W93)."""

   read_and_companion = {query.friendly_name for query in (*READ_QUERIES, *COMPANION_QUERIES)}
   writes = {query.friendly_name for query in WRITE_QUERIES}
   registered = read_and_companion | writes

   assert "PolarisStoriesV3SeenMutation" in writes
   assert not any("Seen" in name for name in read_and_companion)
   assert {name for name in registered if "Seen" in name} == {"PolarisStoriesV3SeenMutation"}
   assert not any(name in registered for name in SEEN_MUTATIONS[1:])


class FakeStories:
   def __init__(self, client: FakeStoriesClient, reel: StoryReel | None) -> None:
      self.client = client
      self.reel_answer = reel
      self.asked: list[tuple[str, ...]] = []

   def marking(self) -> str:
      return "marking" if self.client.behavior.mark_stories_seen else "not marking"

   def tray(self) -> tuple[TrayReel, ...]:
      self.asked.append(("tray", ""))

      return parse_stories_tray(recorded("stories_tray.json"))

   def reel(self, user_id: str) -> StoryReel | None:
      self.asked.append(("reel", user_id, self.marking()))

      return self.reel_answer

   def highlight(self, highlight_id: str) -> StoryReel:
      self.asked.append(("highlight", highlight_id, self.marking()))

      return parse_highlight_reel(recorded("highlight.json"))

   def mark_seen(self, item: StoryItem, *, reel: StoryReel) -> None:
      self.asked.append(("mark_seen", item.pk, reel.id))


class FakeStoriesClient:
   def __init__(self, reel: StoryReel | None = None, behavior: Any = PARITY) -> None:
      self.session = Session(sessionid="s", ds_user_id="1234567890", csrftoken="c")
      self.behavior = behavior
      self.stories = FakeStories(self, reel)
      self.closed = False
      self.scoped: list[FakeStoriesClient] = []

   def with_behavior(self, behavior: Any) -> FakeStoriesClient:
      scoped = FakeStoriesClient(self.stories.reel_answer, behavior)
      scoped.stories.asked = self.stories.asked
      self.scoped.append(scoped)

      return scoped

   def close(self) -> None:
      self.closed = True


def run_command(argv: list[str], client: FakeStoriesClient) -> tuple[int, str, str]:
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


def test_dumpsta_stories_tray_story_and_highlight_print_every_row_and_item() -> None:
   """Catches a row or an item cut short in either output form, a reel with no live story
   printed as anything but null, and the id passed on as something else."""

   tray_client = FakeStoriesClient()
   _, tray_out, _ = run_command(["--json", "stories-tray"], tray_client)
   _, tray_text, _ = run_command(["stories-tray"], FakeStoriesClient())
   empty_client = FakeStoriesClient(reel=None)
   _, empty_out, _ = run_command(["--json", "story", USER_ID], empty_client)
   highlight_client = FakeStoriesClient()
   _, highlight_out, _ = run_command(["--json", "highlight", highlight_id()], highlight_client)
   _, highlight_text, _ = run_command(["highlight", highlight_id()], FakeStoriesClient())

   tray = json.loads(tray_out)
   empty = json.loads(empty_out)
   highlight = json.loads(highlight_out)

   assert tray["reel_count"] == 33
   assert len(tray["reels"]) == 33
   assert tray_text.strip().splitlines()[-1] == "reels: 33"
   assert empty_client.stories.asked == [("reel", USER_ID, "marking")]
   assert empty["reel"] is None
   assert empty["item_count"] == 0
   assert highlight_client.stories.asked == [("highlight", highlight_id(), "marking")]
   assert highlight["item_count"] == 18
   assert len(highlight["reel"]["items"]) == 18
   assert highlight_text.strip().splitlines()[-1] == "items: 18"
   assert tray_client.closed
   assert highlight_client.closed


def test_dumpsta_story_refuses_a_username_and_highlight_a_bare_number(
   capsys: pytest.CaptureFixture[str],
) -> None:
   """Catches a username passed on as an account id, and a highlight id without its prefix."""

   client = FakeStoriesClient()
   story_refused, _, _ = run_command(["story", "someone"], client)
   highlight_refused, _, _ = run_command(
      ["highlight", highlight_id().removeprefix("highlight:")], client
   )

   assert story_refused == 2
   assert highlight_refused == 2
   assert client.stories.asked == []
   assert "highlight:<number>" in capsys.readouterr().err


def test_dumpsta_story_and_highlight_mark_the_first_item_unless_told_not_to() -> None:
   """The W95 gate. Catches ``--no-mark-seen`` ignored or applied to the wrong client, the
   scoped client left open, and the JSON claiming a mark that was not asked for."""

   marking = FakeStoriesClient()
   _, marked_out, _ = run_command(["--json", "highlight", highlight_id()], marking)
   quiet = FakeStoriesClient()
   _, quiet_out, _ = run_command(["--json", "highlight", "--no-mark-seen", highlight_id()], quiet)
   quiet_story = FakeStoriesClient(reel=parse_story_reel(a_live_reel()))
   _, quiet_story_out, _ = run_command(["--json", "story", "--no-mark-seen", USER_ID], quiet_story)

   assert marking.stories.asked == [("highlight", highlight_id(), "marking")]
   assert json.loads(marked_out)["marked_first_item_seen"] is True
   assert marking.scoped == []
   assert quiet.stories.asked == [("highlight", highlight_id(), "not marking")]
   assert json.loads(quiet_out)["marked_first_item_seen"] is False
   assert [scoped.closed for scoped in quiet.scoped] == [True]
   assert quiet_story.stories.asked == [("reel", USER_ID, "not marking")]
   assert json.loads(quiet_story_out)["marked_first_item_seen"] is False
   assert quiet.closed
   assert quiet_story.closed


def test_dumpsta_story_seen_reads_without_marking_then_marks_the_named_item() -> None:
   """Catches the read before the mark marking an item of its own, the wrong item or reel
   marked, and a missing item or reel answered with a mark instead of an error."""

   node = highlight_node()
   third = node["items"][2]["pk"]
   live_owner = a_live_reel()["data"][REELS_ROOT]["reels_media"][0]["id"]
   on_highlight = FakeStoriesClient()
   code, out, _ = run_command(["--json", "story-seen", highlight_id(), third], on_highlight)
   on_live = FakeStoriesClient(reel=parse_story_reel(a_live_reel()))
   live_code, _, _ = run_command(["story-seen", live_owner, third], on_live)
   missing_item = FakeStoriesClient()
   missing_code, _, _ = run_command(["story-seen", highlight_id(), "1"], missing_item)
   no_live = FakeStoriesClient(reel=None)
   no_live_code, _, _ = run_command(["story-seen", USER_ID, third], no_live)
   refused = FakeStoriesClient()
   refused_code, _, _ = run_command(["story-seen", highlight_id(), "not-a-pk"], refused)

   assert code == 0
   assert on_highlight.stories.asked == [
      ("highlight", highlight_id(), "not marking"),
      ("mark_seen", third, highlight_id()),
   ]
   assert json.loads(out) == {
      "command": "story-seen",
      "reel_id": highlight_id(),
      "item_pk": third,
      "marked_seen": True,
   }
   assert [scoped.closed for scoped in on_highlight.scoped] == [True]
   assert live_code == 0
   assert on_live.stories.asked == [
      ("reel", live_owner, "not marking"),
      ("mark_seen", third, live_owner),
   ]
   assert missing_code == 7
   assert missing_item.stories.asked == [("highlight", highlight_id(), "not marking")]
   assert no_live_code == 7
   assert no_live.stories.asked == [("reel", USER_ID, "not marking")]
   assert refused_code == 2
   assert refused.stories.asked == []
