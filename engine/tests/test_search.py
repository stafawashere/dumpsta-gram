"""Gates on E2 batch 8, search: the recent searches, the non-personalised typeahead and a
hashtag's header.

Four defect classes live here.

A mapper can read a field from the wrong key or invent one the answer does not carry. A recent
search is a union of four slots, of which only accounts and keywords have been seen filled, so an
entry can be read from the wrong slot, and a shape nobody has seen can be passed off as one that
has been.

A request can go to the wrong query, carry other variables or another referer, or accept a query
or a tag it should refuse before sending.

A read can send what nothing verified. The personalised typeahead and the keyword grid carry
variables never observed, so neither may be registered or sent (W83).

And a command can drop a row in either output form, or pass a ``#`` on as part of a tag.

The payloads are the recorded answers of 2026-09-27, pseudonymised by
``scripts/build_search_fixtures.py``. Nothing in this file touches the network.
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
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.search import (
   read_hashtag_header,
   read_non_personalised_typeahead,
   read_recent_searches,
)
from dumpstagram._private.web.documents.catalog import (
   COMPANION_QUERIES,
   READ_QUERIES,
   WRITE_QUERIES,
)
from dumpstagram._private.web.parse.search import (
   parse_hashtag_header,
   parse_non_personalised_typeahead,
   parse_recent_searches,
)
from dumpstagram.aio import AsyncClient
from dumpstagram.behavior import PARITY
from dumpstagram.client import SyncClient
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import Hashtag, ProfileSummary, RecentSearch, RecentSearchKind
from dumpstagram.session import Session
from tests.test_direct import (
   FakeClock,
   ScriptedTransport,
   a_bootstrapped_session,
   json_response,
   make_paced,
   sent_variables,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "search"

API_GRAPHQL = "https://www.instagram.com/api/graphql"
SITE_ROOT = "https://www.instagram.com/"
RECENT_SEARCHES_DOC_ID = "38466302779627407"
TYPEAHEAD_DOC_ID = "27634848489527274"
HASHTAG_HEADER_DOC_ID = "35337906325853853"
RECENT_ROOT = "xig_recent_searches"
TYPEAHEAD_ROOT = "xdt_api__v1__fbsearch__non_profiled_serp"
HASHTAG_ROOT = "fetch__XDTTagInfo"
UNOBSERVED_SEARCH_QUERIES = {
   "PolarisSearchBoxContainerQuery",
   "PolarisSearchBoxRefetchableQuery",
   "PolarisKeywordSearchExplorePageRelayQuery",
}
A_TAG = "some_tag"
A_QUERY = "a query"

SCRIPTED_BEHAVIOR = replace(PARITY, cookie_sync=False)


def recorded(name: str) -> Any:
   return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def recent_entries() -> list[dict[str, Any]]:
   return list(recorded("recent_searches.json")["data"][RECENT_ROOT]["recent_searches"])


def typeahead_users() -> list[dict[str, Any]]:
   return list(recorded("non_personalised_typeahead.json")["data"][TYPEAHEAD_ROOT]["users"])


def sent_field(request: Any, name: str) -> str:
   return parse_qs(request.content.decode("utf-8"))[name][0]


def filled_slot(entry: dict[str, Any]) -> str:
   return next(key for key, value in entry.items() if value is not None)


def test_the_recent_searches_map_every_entry_from_its_filled_slot_in_order() -> None:
   """Catches an entry dropped or reordered, its kind read from another slot, an account's fields
   read from other keys, and a keyword read from anything but its name."""

   entries = recent_entries()
   mapped = parse_recent_searches(recorded("recent_searches.json"))

   assert len(mapped) == 15
   assert [entry.kind.value for entry in mapped] == [filled_slot(entry) for entry in entries]
   assert [entry.kind for entry in mapped].count(RecentSearchKind.ACCOUNT) == 4
   assert [entry.kind for entry in mapped].count(RecentSearchKind.KEYWORD) == 11

   for entry, raw in zip(mapped, entries, strict=True):
      if entry.kind is RecentSearchKind.ACCOUNT:
         user = raw["user"]

         assert entry.keyword is None
         assert entry.account == ProfileSummary(
            id=user["pk"],
            username=user["username"],
            full_name=user["full_name"],
            is_verified=user["is_verified"],
            profile_pic_url=user["profile_pic_url"],
            hd_profile_pic_url=user["hd_profile_pic_url_info"]["url"],
         )
      else:
         assert entry.account is None
         assert entry.keyword == raw["keyword"]["name"]


def test_an_unread_slot_is_its_kind_alone_and_a_broken_union_raises() -> None:
   """Catches a hashtag or place entry dropped or given a guessed payload, and an entry with no
   slot, two slots or a slot this version does not know accepted."""

   answer = recorded("recent_searches.json")
   entries = answer["data"][RECENT_ROOT]["recent_searches"]
   keyword_entry = next(entry for entry in entries if entry["keyword"] is not None)

   with_other_kinds = copy.deepcopy(answer)
   hashtag_entry = {**keyword_entry, "keyword": None, "hashtag": {"name": "anything"}}
   place_entry = {**keyword_entry, "keyword": None, "place": {"title": "anything"}}
   with_other_kinds["data"][RECENT_ROOT]["recent_searches"] = [hashtag_entry, place_entry]

   assert parse_recent_searches(with_other_kinds) == (
      RecentSearch(kind=RecentSearchKind.HASHTAG),
      RecentSearch(kind=RecentSearchKind.PLACE),
   )

   empty = {**keyword_entry, "keyword": None}
   doubled = {**keyword_entry, "hashtag": {"name": "anything"}}
   unknown = {**keyword_entry, "keyword": None, "audio": {"id": "1"}}

   for broken in (empty, doubled, unknown):
      payload = copy.deepcopy(answer)
      payload["data"][RECENT_ROOT]["recent_searches"] = [broken]

      with pytest.raises(SchemaChanged):
         parse_recent_searches(payload)


def test_the_typeahead_maps_every_account_in_order_from_its_own_keys() -> None:
   """Catches an account dropped or reordered, a field read from another key, and a privacy flag
   or relationship invented where the row carries none."""

   users = typeahead_users()
   accounts = parse_non_personalised_typeahead(recorded("non_personalised_typeahead.json"))

   assert len(accounts) == 18
   assert accounts == tuple(
      ProfileSummary(
         id=user["pk"],
         username=user["username"],
         full_name=user["full_name"],
         is_verified=user["is_verified"],
         profile_pic_url=user["profile_pic_url"],
         hd_profile_pic_url=user["hd_profile_pic_url_info"]["url"],
      )
      for user in users
   )
   assert any(account.is_verified for account in accounts)
   assert not all(account.is_verified for account in accounts)


def test_the_hashtag_header_is_the_answers_id_and_the_tag_asked_for() -> None:
   """Catches the id read from anything but the answer, the name taken from anything but the tag
   that was sent, and a header without an id accepted."""

   answer = recorded("hashtag_header.json")
   without_id = copy.deepcopy(answer)
   del without_id["data"][HASHTAG_ROOT]["id"]

   assert parse_hashtag_header(answer, A_TAG) == Hashtag(
      id=answer["data"][HASHTAG_ROOT]["id"], name=A_TAG
   )

   with pytest.raises(SchemaChanged):
      parse_hashtag_header(without_id, A_TAG)


@pytest.mark.asyncio
async def test_the_three_reads_send_what_the_replays_sent() -> None:
   """The parity gate for the search reads. Catches another path or query, another variable,
   another referer, a tag sent unescaped in the referer, and a root field header on a path that
   carries none."""

   transport = ScriptedTransport(
      [
         json_response(recorded("recent_searches.json")),
         json_response(recorded("non_personalised_typeahead.json")),
         json_response(recorded("hashtag_header.json")),
         json_response(recorded("hashtag_header.json")),
      ]
   )
   sender = make_paced(transport)
   session = a_bootstrapped_session()

   await read_recent_searches(sender, session)
   await read_non_personalised_typeahead(sender, session, A_QUERY)
   await read_hashtag_header(sender, session, A_TAG)
   await read_hashtag_header(sender, session, "café")

   recent, typeahead, header, accented = transport.sent

   assert [request.url for request in transport.sent] == [API_GRAPHQL] * 4
   assert [sent_field(request, "doc_id") for request in (recent, typeahead, header)] == [
      RECENT_SEARCHES_DOC_ID,
      TYPEAHEAD_DOC_ID,
      HASHTAG_HEADER_DOC_ID,
   ]
   assert sent_variables(recent) == {}
   assert sent_variables(typeahead) == {"hasQuery": True, "query": A_QUERY}
   assert sent_variables(header) == {"tag_name": A_TAG}
   assert sent_variables(accented) == {"tag_name": "café"}
   assert recent.headers["referer"] == SITE_ROOT
   assert typeahead.headers["referer"] == SITE_ROOT
   assert header.headers["referer"] == f"https://www.instagram.com/explore/tags/{A_TAG}/"
   assert accented.headers["referer"] == "https://www.instagram.com/explore/tags/caf%C3%A9/"
   assert all("x-root-field-name" not in request.headers for request in transport.sent)


@pytest.mark.asyncio
async def test_an_empty_query_or_a_tag_with_a_hash_is_refused_before_anything_is_sent() -> None:
   """Catches a blank query or a malformed tag reaching the request, where a ``#`` would be sent
   inside the tag and a ``/`` would break the referer's path."""

   transport = ScriptedTransport([])
   sender = make_paced(transport)
   session = a_bootstrapped_session()

   for query in ("", "   "):
      with pytest.raises(ValueError, match="query text"):
         await read_non_personalised_typeahead(sender, session, query)

   for tag in ("", "#some_tag", "some tag", "some/tag", "tag?x"):
      with pytest.raises(ValueError, match="without its '#'"):
         await read_hashtag_header(sender, session, tag)

   assert transport.sent == []


def paced(transport: ScriptedTransport, client: AsyncClient) -> PacedSender:
   clock = FakeClock()
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)

   return PacedSender(transport, pacer, client._sender.pacing, client._sender.writes)


def friendly_names(requests: list[Any]) -> list[str]:
   return [sent_field(request, "fb_api_req_friendly_name") for request in requests]


@pytest.mark.asyncio
async def test_each_search_read_sends_its_one_query_and_no_unobserved_search_is_registered() -> (
   None
):
   """The W83 gate. Catches a search method sending more than its one query, and the
   personalised typeahead or the keyword grid registered anywhere a later change could send it
   from before its variables are observed."""

   transport = ScriptedTransport(
      [
         json_response(recorded("recent_searches.json")),
         json_response(recorded("non_personalised_typeahead.json")),
         json_response(recorded("hashtag_header.json")),
      ]
   )
   client = AsyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR)
   await client._sender.aclose()
   client._sender = paced(transport, client)

   try:
      recent = await client.search.recent()
      accounts = await client.search.accounts(A_QUERY)
      hashtag = await client.search.hashtag(A_TAG)
   finally:
      await client.aclose()

   registered = {
      query.friendly_name for query in (*READ_QUERIES, *COMPANION_QUERIES, *WRITE_QUERIES)
   }

   assert len(recent) == 15
   assert len(accounts) == 18
   assert hashtag.name == A_TAG
   assert friendly_names(transport.sent) == [
      "PolarisSearchNullStateQuery",
      "PolarisSearchBoxNonProfiledRefetchableQuery",
      "PolarisHashtagHeaderActionButtonsQuery",
   ]
   assert UNOBSERVED_SEARCH_QUERIES.isdisjoint(registered)


def test_the_blocking_search_reads_answer_as_their_async_twins() -> None:
   """The same three reads on the blocking surface, each on the loop thread."""

   transport = ScriptedTransport(
      [
         json_response(recorded("hashtag_header.json")),
         json_response(recorded("non_personalised_typeahead.json")),
         json_response(recorded("recent_searches.json")),
      ]
   )

   with SyncClient(a_bootstrapped_session(), behavior=SCRIPTED_BEHAVIOR) as client:
      client._loop.run(client._impl._sender.aclose(), operation="the scripted sender swap")
      client._impl._sender = paced(transport, client._impl)
      hashtag = client.search.hashtag(A_TAG)
      accounts = client.search.accounts(A_QUERY)
      recent = client.search.recent()

   assert hashtag.id == recorded("hashtag_header.json")["data"][HASHTAG_ROOT]["id"]
   assert [account.id for account in accounts] == [user["pk"] for user in typeahead_users()]
   assert len(recent) == 15
   assert friendly_names(transport.sent)[-1] == "PolarisSearchNullStateQuery"


class FakeSearch:
   def __init__(self) -> None:
      self.asked: list[tuple[str, str]] = []

   def recent(self) -> tuple[RecentSearch, ...]:
      self.asked.append(("recent", ""))

      return parse_recent_searches(recorded("recent_searches.json"))

   def accounts(self, query: str) -> tuple[ProfileSummary, ...]:
      self.asked.append(("accounts", query))

      return parse_non_personalised_typeahead(recorded("non_personalised_typeahead.json"))

   def hashtag(self, tag: str) -> Hashtag:
      self.asked.append(("hashtag", tag))

      return parse_hashtag_header(recorded("hashtag_header.json"), tag)


class FakeSearchClient:
   def __init__(self) -> None:
      self.session = Session(sessionid="s", ds_user_id="1234567890", csrftoken="c")
      self.search = FakeSearch()
      self.closed = False

   def close(self) -> None:
      self.closed = True


def run_command(argv: list[str], client: FakeSearchClient) -> tuple[int, str]:
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


def test_dumpsta_recent_searches_search_and_hashtag_print_everything_read() -> None:
   """Catches an entry or an account left out of either form, a kind or a keyword misprinted, the
   query or the tag not passed through, and the hashtag's id dropped."""

   recent_client = FakeSearchClient()
   _, recent_out = run_command(["--json", "recent-searches"], recent_client)
   _, recent_text = run_command(["recent-searches"], FakeSearchClient())
   search_client = FakeSearchClient()
   _, search_out = run_command(["--json", "search", A_QUERY], search_client)
   _, search_text = run_command(["search", A_QUERY], FakeSearchClient())
   hashtag_client = FakeSearchClient()
   _, hashtag_out = run_command(["--json", "hashtag", A_TAG], hashtag_client)
   _, hashtag_text = run_command(["hashtag", A_TAG], FakeSearchClient())

   entries = recent_entries()
   recent = json.loads(recent_out)
   search = json.loads(search_out)
   hashtag = json.loads(hashtag_out)
   recent_lines = recent_text.strip().splitlines()
   expected_recent_lines = [
      f"account  {entry['user']['pk']}  {entry['user']['username']}  {entry['user']['full_name']}"
      if entry["user"] is not None
      else f"keyword  {entry['keyword']['name']}"
      for entry in entries
   ]
   header_id = recorded("hashtag_header.json")["data"][HASHTAG_ROOT]["id"]

   assert recent["entry_count"] == 15
   assert [entry["kind"] for entry in recent["entries"]] == [
      filled_slot(entry) for entry in entries
   ]
   assert [entry["keyword"] for entry in recent["entries"]] == [
      entry["keyword"]["name"] if entry["keyword"] is not None else None for entry in entries
   ]
   assert recent_lines[:-1] == expected_recent_lines
   assert recent_lines[-1] == "recent searches: 15"
   assert search_client.search.asked == [("accounts", A_QUERY)]
   assert search["query"] == A_QUERY
   assert search["account_count"] == 18
   assert [account["id"] for account in search["accounts"]] == [
      user["pk"] for user in typeahead_users()
   ]
   assert [line.split()[0] for line in search_text.strip().splitlines()[:-1]] == [
      user["pk"] for user in typeahead_users()
   ]
   assert search_text.strip().splitlines()[-1] == "accounts: 18"
   assert hashtag_client.search.asked == [("hashtag", A_TAG)]
   assert hashtag["hashtag"] == {"id": header_id, "name": A_TAG}
   assert hashtag_text.strip() == f"#{A_TAG}  id {header_id}"
   assert recent_client.closed
   assert search_client.closed


def test_dumpsta_hashtag_refuses_a_hash_and_search_refuses_a_blank_query() -> None:
   """Catches a ``#`` passed on as part of a tag, and a blank query sent."""

   client = FakeSearchClient()
   hashed, _ = run_command(["hashtag", f"#{A_TAG}"], client)
   blank, _ = run_command(["search", "  "], client)

   assert (hashed, blank) == (2, 2)
   assert client.search.asked == []
