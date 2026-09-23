"""Gates on the notes tray read, its mapper, and the request it is built from.

Four defect classes live here.

The viewer's own note can be found by the wrong identifier. The tray names authors by the
numeric Instagram id, a tray item has an id of its own, and the account has a Facebook-side id
as well, so a comparison against any of the others finds nothing or finds someone else.

The mapper can fill a field from the wrong key, or read seconds as milliseconds, which degrades
every note rather than failing.

The tray can start paging. The read is one call because every measured tray was one flat
list, and a cursor appearing beside the items would make that a first page reported as the
whole tray.

And the request can drift from the one a browser sends, which is the parity gate for this read.

Every response is canned. Nothing in this file touches the network.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs

import pytest

from dumpstagram._core.notes import find_own_note, read_notes
from dumpstagram._private.web.parse import parse_inbox_tray
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import Note, NoteAudience
from tests.test_direct import (
   ScriptedTransport,
   a_bootstrapped_session,
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

TRAY_DOC_ID = "29231580869776032"
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
