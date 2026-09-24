"""Gates on the notes tray read, set_note and delete_note, the Step 14 table in the build plan.

Seven defect classes live here.

The viewer's own note can be found by the wrong identifier. The tray names authors by the
numeric Instagram id, a tray item has an id of its own, and the account has a Facebook-side id
as well, so a comparison against any of the others finds nothing or finds someone else.

The mapper can fill a field from the wrong key, or read seconds as milliseconds, which degrades
every note rather than failing.

The tray can start paging. The read is one call because every measured tray was one flat
list, and a cursor appearing beside the items would make that a first page reported as the
whole tray.

The create can name the account by the wrong id. It sends the Facebook-side ``actor_id`` the
bootstrap page carries, and ``ds_user_id`` is a different number for the same account, so a
substitution in either direction sends a create for nobody, or for the wrong identity.

A delete's success is a null root field, and a mapper that tests it for truthiness reports every
successful delete as a failure. The delete also has to name the tray item, not its author.

A write can leave by a path other than ``send_write``, or be sent again after an error answer.

And each request can drift from the one a browser or the engine sent live, which is the parity
gate for each. A browser sends more around a note, a burst ruling 23 left unrecorded.

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
from dumpstagram._core.notes import find_own_note, read_notes
from dumpstagram._core.pacer import PacingPolicy, WritePolicy
from dumpstagram._core.writes.notes import delete_note, set_note
from dumpstagram._private.web.bootstrap import bootstrap
from dumpstagram._private.web.parse.notes import parse_created_note, parse_inbox_tray
from dumpstagram.aio import AsyncClient
from dumpstagram.errors import SchemaChanged, UpstreamRejected
from dumpstagram.models import Note, NoteAudience
from dumpstagram.namespaces.direct import AsyncDirect
from dumpstagram.session import Session
from tests.test_direct import (
   BOOTSTRAP_PAGE,
   ScriptedTransport,
   a_bootstrapped_session,
   html_response,
   json_response,
   make_paced,
   sent_variables,
)

VIEWER_ID = "1234567890"
"""The ``ds_user_id`` of :func:`~tests.test_direct.a_bootstrapped_session`."""

OWN_ITEM_ID = "18000000000000001"
OTHER_ITEM_ID = "18000000000000002"
OTHER_AUTHOR_ID = "58435292991"
CREATED_AT_SECONDS = 1790121336

ACTOR_ID = "17841400000000077"
"""A Facebook-side id of the recorded length, 17 digits, unlike the 10 of ``VIEWER_ID``."""

TRAY_DOC_ID = "29231580869776032"
CREATE_DOC_ID = "28592645767037889"
DELETE_DOC_ID = "28419182984337833"
INBOX_REFERER = "https://www.instagram.com/direct/inbox/"
API_GRAPHQL = "https://www.instagram.com/api/graphql"


def tray_item(
   *,
   item_id: str = OTHER_ITEM_ID,
   author_id: str = OTHER_AUTHOR_ID,
   text: str = "a note body",
   audience: int = 1,
   pog_user_id: str | None = None,
   item_type: str = "note",
) -> dict[str, Any]:
   """One tray item with the key set measured on 2026-09-21 and 2026-09-23, synthetic values.

   Every value differs from every other, so a field read from the wrong key cannot come out
   equal by accident. The keys the mapper drops are present, because a mapper that only ever
   sees the keys it reads has an untested unknown-field policy.
   """

   return {
      "inbox_tray_item_id": item_id,
      "inbox_tray_item_type": item_type,
      "pog_info": {
         "pog_style": "user",
         "pog_users": [
            {
               "id": pog_user_id if pog_user_id is not None else author_id,
               "username": "an.author",
               "full_name": "An Author",
               "profile_pic_url": "https://example.invalid/pic.jpg",
               "profile_pic_url_hd": "https://example.invalid/pic-hd.jpg",
               "interop_messaging_user_fbid": "17841400000000099",
            }
         ],
      },
      "note_dict": {
         "note_style": 0,
         "note_response_info": {
            "note_pog_video_response_info": None,
            "music_note_response_info": None,
         },
         "custom_theme": None,
         "text": text,
         "is_emoji_only": False,
         "audience": audience,
         "author_id": author_id,
         "created_at": CREATED_AT_SECONDS,
      },
   }


def tray_payload(items: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
   return {
      "data": {"response": {"inbox_tray_items": items, **extra}},
      "extensions": {"is_final": True},
   }


def own_and_other_tray() -> dict[str, Any]:
   return tray_payload(
      [
         tray_item(),
         tray_item(item_id=OWN_ITEM_ID, author_id=VIEWER_ID, text="mine", audience=0),
      ]
   )


def test_the_item_maps_into_note_field_by_field() -> None:
   """Catches a field read from the wrong key and created_at read in the wrong unit."""

   notes = parse_inbox_tray(tray_payload([tray_item()]))

   assert notes == (
      Note(
         id=OTHER_ITEM_ID,
         author_id=OTHER_AUTHOR_ID,
         text="a note body",
         audience=NoteAudience.CLOSE_FRIENDS,
         created_at=datetime(2026, 9, 22, 23, 55, 36, tzinfo=UTC),
         is_emoji_only=False,
         author_username="an.author",
      ),
   )


def test_the_audience_numbers_are_the_web_clients_own() -> None:
   """Catches the two audiences swapped, which would publish a close friends note to everyone
   followed back once a create sends this enum. The numbers are written out, from the client's
   PolarisNotesTypes module and the composer's close friends choice."""

   assert NoteAudience(0) is NoteAudience.MUTUAL_FOLLOWS
   assert NoteAudience(1) is NoteAudience.CLOSE_FRIENDS
   assert NoteAudience(2) is NoteAudience.INTERNAL


def test_an_undeclared_audience_is_a_schema_change() -> None:
   """Catches an audience number nobody declared being mapped to some member anyway."""

   with pytest.raises(SchemaChanged) as raised:
      parse_inbox_tray(tray_payload([tray_item(audience=7)]))

   assert raised.value.path == "data.response.inbox_tray_items[0].note_dict.audience"


def test_a_cursor_beside_the_items_is_a_schema_change() -> None:
   """Catches a paged tray read as the whole tray because the new key was ignored."""

   with pytest.raises(SchemaChanged) as raised:
      parse_inbox_tray(tray_payload([tray_item()], page_info={"has_next_page": True}))

   assert raised.value.path == "data.response.page_info"


def test_a_tray_item_that_is_not_a_note_is_a_schema_change() -> None:
   """Catches a new kind of tray item mapped into a note it is not."""

   with pytest.raises(SchemaChanged):
      parse_inbox_tray(tray_payload([tray_item(item_type="story")]))


def test_the_author_username_is_only_taken_from_the_author() -> None:
   """Catches a note credited to whoever the tray pictured first when that is not the author."""

   notes = parse_inbox_tray(tray_payload([tray_item(pog_user_id="99999999999")]))

   assert notes[0].author_username is None


def test_the_own_note_is_the_one_authored_by_the_viewer() -> None:
   """Catches the own note looked up by any identifier other than the author's numeric id."""

   notes = parse_inbox_tray(own_and_other_tray())

   own = find_own_note(notes, VIEWER_ID)

   assert own is not None
   assert own.id == OWN_ITEM_ID


def test_a_tray_without_the_viewers_note_yields_none() -> None:
   """Catches a lookup that falls back to some item when the viewer has no note."""

   notes = parse_inbox_tray(tray_payload([tray_item(), tray_item(item_id=OWN_ITEM_ID)]))

   assert find_own_note(notes, VIEWER_ID) is None


@pytest.mark.asyncio
async def test_the_tray_read_sends_the_request_the_inbox_sends() -> None:
   """The parity gate for this read. Catches the tray query sent with other variables, another
   referer, on the other path or beside requests the engine does not model. A browser sends
   more around it, the rest of the inbox load, which is a recorded departure."""

   transport = ScriptedTransport([json_response(own_and_other_tray())])

   notes = await read_notes(make_paced(transport), a_bootstrapped_session())

   assert len(transport.sent) == 1

   request = transport.sent[0]
   body = parse_qs(request.content.decode("utf-8")) if request.content else {}

   assert request.url == API_GRAPHQL
   assert body["doc_id"] == [TRAY_DOC_ID]
   assert body["fb_api_req_friendly_name"] == ["IGDInboxTrayQuery"]
   assert sent_variables(request) == {}
   assert request.headers["referer"] == INBOX_REFERER
   assert "x-root-field-name" not in request.headers
   assert [note.id for note in notes] == [OTHER_ITEM_ID, OWN_ITEM_ID]


def a_session_with_an_actor_id() -> Session:
   session = a_bootstrapped_session()
   session.actor_id = ACTOR_ID

   return session


def created_payload(*, audience: int = 1) -> dict[str, Any]:
   """The create answer's key set as the engine create read it on 2026-09-23, synthetic values.

   The item is the tray's own shape under ``data.xdt_create_inbox_tray_item.inbox_tray_item``.
   """

   return {
      "data": {
         "xdt_create_inbox_tray_item": {
            "inbox_tray_item": tray_item(
               item_id=OWN_ITEM_ID, author_id=VIEWER_ID, text="brb", audience=audience
            )
         }
      },
      "extensions": {
         "is_final": True,
         "server_metadata": {"request_start_time_ms": 1, "time_at_flush_ms": 2},
      },
   }


def deleted_payload() -> dict[str, Any]:
   """The 166 byte answer every observed delete returned, whose whole payload is a null root."""

   return {"data": {"xdt_delete_inbox_tray_item": None}, "extensions": {"is_final": True}}


def page_with_an_actor_id() -> str:
   """The bootstrap page with the config a real inbox document carries its actorID in."""

   config = (
      '["RelayAPIConfigDefaults",[],{"accessToken":"","actorID":"'
      + ACTOR_ID
      + '","customHeaders":{}},4]'
   )

   return BOOTSTRAP_PAGE.replace("</script>", config + "</script>")


def test_the_created_item_maps_into_note_field_by_field() -> None:
   """Catches a field of the created note read from the wrong key, or read off anything but the
   item the create answered with."""

   created = parse_created_note(created_payload())

   assert created == Note(
      id=OWN_ITEM_ID,
      author_id=VIEWER_ID,
      text="brb",
      audience=NoteAudience.CLOSE_FRIENDS,
      created_at=datetime(2026, 9, 22, 23, 55, 36, tzinfo=UTC),
      is_emoji_only=False,
      author_username="an.author",
   )


@pytest.mark.asyncio
async def test_the_create_sends_actor_id_never_ds_user_id() -> None:
   """The parity gate for the create, and the table's first row. Catches ``ds_user_id`` sent as
   ``actor_id``, the audience or text not passed on, another variable, path or referer, or a
   request beside the write."""

   transport = ScriptedTransport([json_response(created_payload())])

   await set_note(
      make_paced(transport),
      a_session_with_an_actor_id(),
      "brb",
      audience=NoteAudience.CLOSE_FRIENDS,
   )

   assert len(transport.sent) == 1

   request = transport.sent[0]
   body = parse_qs(request.content.decode("utf-8")) if request.content else {}

   assert request.url == API_GRAPHQL
   assert body["doc_id"] == [CREATE_DOC_ID]
   assert body["fb_api_req_friendly_name"] == ["usePolarisCreateInboxTrayItemSubmitMutation"]
   assert sent_variables(request) == {
      "input": {
         "actor_id": ACTOR_ID,
         "additional_params": {"note_create_params": {"note_style": 0, "text": "brb"}},
         "audience": 1,
         "client_mutation_id": "1",
         "inbox_tray_item_type": "note",
      }
   }
   assert request.headers["referer"] == INBOX_REFERER


@pytest.mark.asyncio
async def test_the_bootstrap_reads_the_actor_id_and_never_falls_back_to_ds_user_id() -> None:
   """Catches the Facebook-side id taken from anywhere but the page's relay config, or filled in
   with ``ds_user_id`` when a page does not carry it."""

   with_it = a_bootstrapped_session()
   without_it = a_bootstrapped_session()

   await bootstrap(ScriptedTransport([html_response(page_with_an_actor_id())]), with_it)
   await bootstrap(ScriptedTransport([html_response(BOOTSTRAP_PAGE)]), without_it)

   assert with_it.actor_id == ACTOR_ID
   assert without_it.actor_id is None


@pytest.mark.asyncio
async def test_a_session_without_an_actor_id_bootstraps_before_the_create() -> None:
   """Catches a create attempted with page tokens but no ``actor_id``, which is every session
   saved before the id was harvested."""

   transport = ScriptedTransport(
      [html_response(page_with_an_actor_id()), json_response(created_payload())]
   )

   await set_note(
      make_paced(transport), a_bootstrapped_session(), "brb", audience=NoteAudience.CLOSE_FRIENDS
   )

   assert [request.method for request in transport.sent] == ["GET", "POST"]
   assert sent_variables(transport.sent[1])["input"]["actor_id"] == ACTOR_ID


@pytest.mark.asyncio
async def test_a_page_without_the_actor_id_stops_the_create_before_it_is_sent() -> None:
   """Catches a create sent with ``ds_user_id`` standing in when the page carried no actorID."""

   transport = ScriptedTransport([html_response(BOOTSTRAP_PAGE), json_response(created_payload())])

   with pytest.raises(SchemaChanged):
      await set_note(
         make_paced(transport),
         a_bootstrapped_session(),
         "brb",
         audience=NoteAudience.CLOSE_FRIENDS,
      )

   assert [request.method for request in transport.sent] == ["GET"]


@pytest.mark.asyncio
async def test_a_created_note_for_another_audience_raises() -> None:
   """Catches a close friends request answered with a wider audience and reported as done."""

   transport = ScriptedTransport([json_response(created_payload(audience=0))])

   with pytest.raises(UpstreamRejected) as raised:
      await set_note(
         make_paced(transport),
         a_session_with_an_actor_id(),
         "brb",
         audience=NoteAudience.CLOSE_FRIENDS,
      )

   assert raised.value.code == "note_audience_did_not_follow"


@pytest.mark.asyncio
async def test_a_delete_answered_with_a_null_root_is_a_success() -> None:
   """The table's null root row. Catches the root field tested for truthiness, which reads
   every successful delete as a failure."""

   transport = ScriptedTransport([json_response(deleted_payload())])

   await delete_note(make_paced(transport), a_bootstrapped_session(), OWN_ITEM_ID)

   assert len(transport.sent) == 1


@pytest.mark.asyncio
async def test_a_delete_answer_without_its_root_field_is_a_schema_change() -> None:
   """Catches an answer with no root field at all taken as a delete, which it is not known to
   be."""

   transport = ScriptedTransport([json_response({"data": {}, "extensions": {"is_final": True}})])

   with pytest.raises(SchemaChanged):
      await delete_note(make_paced(transport), a_bootstrapped_session(), OWN_ITEM_ID)


@pytest.mark.asyncio
async def test_the_delete_sends_the_item_id() -> None:
   """The parity gate for the delete, and the table's row that it names the item. Catches the
   author's id sent instead, an ``input`` wrapper the browser did not send, another path or
   referer, or a request beside the write."""

   transport = ScriptedTransport([json_response(deleted_payload())])

   await delete_note(make_paced(transport), a_bootstrapped_session(), OWN_ITEM_ID)

   request = transport.sent[0]
   body = parse_qs(request.content.decode("utf-8")) if request.content else {}

   assert len(transport.sent) == 1
   assert request.url == API_GRAPHQL
   assert body["doc_id"] == [DELETE_DOC_ID]
   assert body["fb_api_req_friendly_name"] == ["usePolarisDeleteInboxTrayItemSubmitMutation"]
   assert sent_variables(request) == {"inbox_tray_item_id": OWN_ITEM_ID}
   assert request.headers["referer"] == INBOX_REFERER


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["set", "delete"])
async def test_both_note_writes_depart_only_through_the_write_slot(operation: str) -> None:
   """Catches a note write sent with ``sender.send`` rather than ``send_write``. On an account
   whose writes are stopped the write slot refuses before the transport sees anything, and an
   ordinary send does not."""

   answer = created_payload() if operation == "set" else deleted_payload()
   transport = ScriptedTransport([json_response(answer)])
   sender = make_paced(transport)
   sender.pacer.stop_writes()

   with pytest.raises(UpstreamRejected):
      if operation == "set":
         await set_note(
            sender, a_session_with_an_actor_id(), "brb", audience=NoteAudience.CLOSE_FRIENDS
         )
      else:
         await delete_note(sender, a_bootstrapped_session(), OWN_ITEM_ID)

   assert transport.sent == []


@pytest.mark.asyncio
async def test_an_error_envelope_on_a_set_raises_and_departs_once() -> None:
   """Catches a set sent again after the upstream answered it with an error. The write stop is
   off here, because with it on the pacer would refuse the second send and hide the retry."""

   envelope = {"error": "a_code_no_finding_explains"}
   transport = ScriptedTransport([json_response(envelope), json_response(envelope)])
   sender = make_paced(transport).with_pacing(
      PacingPolicy(), WritePolicy(stop_after_unrecognised_rejection=False)
   )

   with pytest.raises(UpstreamRejected):
      await set_note(
         sender, a_session_with_an_actor_id(), "brb", audience=NoteAudience.CLOSE_FRIENDS
      )

   assert len(transport.sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["empty text", "id that is not digits"])
async def test_what_cannot_be_a_note_is_refused_before_anything_is_sent(operation: str) -> None:
   """Catches empty text or a malformed item id reaching the upstream as a live write."""

   transport = ScriptedTransport([])
   sender = make_paced(transport)

   with pytest.raises(ValueError):
      if operation == "empty text":
         await set_note(
            sender, a_session_with_an_actor_id(), "  ", audience=NoteAudience.CLOSE_FRIENDS
         )
      else:
         await delete_note(sender, a_bootstrapped_session(), f"{OWN_ITEM_ID}_{VIEWER_ID}")

   assert transport.sent == []


@pytest.mark.parametrize("public_set_note", [AsyncClient.set_note, AsyncDirect.set_note])
def test_the_set_note_docstring_names_the_reconciling_read(public_set_note: Any) -> None:
   """Catches the public ``set_note``, flat or on ``client.direct``, losing the instruction to
   read the tray after an unknown outcome, and the warning that a set replaces the note already
   up."""

   documented = public_set_note.__doc__ or ""

   assert "OutcomeUnknown" in documented
   assert ":meth:`notes`" in documented
   assert "replaces" in documented


class RecordingClient:
   def __init__(self) -> None:
      self.session = a_session_with_an_actor_id()
      self.calls: list[tuple[object, ...]] = []

   def set_note(self, text: str, *, audience: NoteAudience = NoteAudience.CLOSE_FRIENDS) -> Note:
      self.calls.append(("set_note", text, audience))

      return parse_created_note(created_payload(audience=int(audience)))

   def delete_note(self, note_id: str) -> None:
      self.calls.append(("delete_note", note_id))

   def close(self) -> None:
      pass


def run_cli(argv: list[str], client: RecordingClient) -> tuple[int, str]:
   out = io.StringIO()

   def factory(path: Path, *, user_agent: str | None = None) -> Any:
      return client

   code = main(argv, environment={}, client_factory=factory, stdout=out, stderr=io.StringIO())

   return code, out.getvalue()


@pytest.mark.parametrize(
   ("named", "audience"),
   [
      ("close-friends", NoteAudience.CLOSE_FRIENDS),
      ("mutual-follows", NoteAudience.MUTUAL_FOLLOWS),
   ],
)
def test_the_cli_sets_the_named_text_for_the_named_audience(
   named: str, audience: NoteAudience
) -> None:
   """Catches the CLI sending other text, or another audience than the one named."""

   client = RecordingClient()

   code, out = run_cli(
      ["--json", "--session", "s.json", "note", "set", "brb", "--audience", named], client
   )

   assert code == 0
   assert client.calls == [("set_note", "brb", audience)]
   assert json.loads(out)["note"]["id"] == OWN_ITEM_ID


def test_the_cli_refuses_a_set_without_an_audience_before_opening_a_client() -> None:
   """Catches a note set falling back to an audience nobody named, which 13.6 forbids."""

   client = RecordingClient()

   with pytest.raises(SystemExit) as raised:
      run_cli(["--session", "s.json", "note", "set", "brb"], client)

   assert raised.value.code == 2
   assert client.calls == []


def test_the_cli_deletes_the_named_note() -> None:
   """Catches the CLI deleting anything but the item id it was given."""

   client = RecordingClient()

   code, _ = run_cli(["--session", "s.json", "note", "delete", OWN_ITEM_ID], client)

   assert code == 0
   assert client.calls == [("delete_note", OWN_ITEM_ID)]


def test_the_cli_refuses_a_note_id_that_is_not_digits_before_opening_a_client() -> None:
   """Catches a malformed note id reaching a client, where it would become a live write."""

   client = RecordingClient()

   with pytest.raises(SystemExit) as raised:
      run_cli(["--session", "s.json", "note", "delete", "abc"], client)

   assert raised.value.code == 2
   assert client.calls == []
