"""Gates for the `dumpsta` command, which is the acceptance harness for Phase 2.

Nothing here touches the network. Every read command is driven with a fake client, which is
what the `Client` protocol in `dumpstagram/_cli/main.py` exists for, so the whole file costs
zero live requests.

The properties gated here are the ones a CLI gets wrong in ways nobody notices: cookie
material creeping onto the command line, a failure arriving as a generic exit code, a
credential reaching stderr inside an error message, and pagination stopping on a heuristic
instead of on the server's own signal.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import stat
import time
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dumpstagram._cli.exits import EXIT_BY_ERROR, exit_code_for
from dumpstagram._cli.main import build_parser, main
from dumpstagram.behavior import Behavior
from dumpstagram.errors import (
   AuthenticationFailed,
   CheckpointRequired,
   DumpstagramError,
   RateLimited,
)
from dumpstagram.models import (
   Event,
   EventsDropped,
   FeedItem,
   FeedItemKind,
   ListenerStopped,
   Message,
   MessageSender,
   NewMessage,
   Note,
   NoteAudience,
   Page,
   Post,
   PostAuthor,
   Profile,
)
from dumpstagram.session import Session

CLI_DIRECTORY = Path(__file__).resolve().parent.parent / "dumpstagram" / "_cli"

SESSIONID = "a-session-token-nobody-should-see"
CSRFTOKEN = "a-csrf-token-nobody-should-see"


def a_session(**overrides: object) -> Session:
   fields: dict[str, object] = {
      "sessionid": SESSIONID,
      "ds_user_id": "17841400000000000",
      "csrftoken": CSRFTOKEN,
   }
   fields.update(overrides)

   return Session(**fields)  # type: ignore[arg-type]


def a_message(identifier: str = "mid.1") -> Message:
   return Message(
      id=identifier,
      thread_fbid="17945046917948992",
      sender=MessageSender(fbid="100000000000000"),
      sent_at=datetime(2026, 9, 21, 2, 30, tzinfo=UTC),
      text="hello",
      content_type="TEXT",
   )


def a_profile(**overrides: object) -> Profile:
   fields: dict[str, object] = {
      "id": "58435292991",
      "username": "an-account",
      "full_name": "a name",
      "biography": "a bio",
      "is_private": True,
      "is_verified": False,
      "follower_count": 80,
      "following_count": 124,
      "media_count": 8,
      "total_clips_count": 1,
      "profile_pic_url": "https://example.invalid/pic.jpg",
   }
   fields.update(overrides)

   return Profile(**fields)  # type: ignore[arg-type]


def a_page(*, has_next_page: bool, end_cursor: str | None, message_count: int = 1) -> Page[Message]:
   return Page(
      items=tuple(a_message(f"mid.{index}") for index in range(message_count)),
      has_next_page=has_next_page,
      end_cursor=end_cursor,
   )


def a_post(code: str = "Cxxxxxxxxxx") -> Post:
   return Post(
      id="3757563240116259739_50476469797",
      pk="3757563240116259739",
      code=code,
      taken_at=datetime(2026, 9, 20, 11, 14, 35, tzinfo=UTC),
      author=PostAuthor(
         id="50476469797",
         username="an-account",
         full_name="a name",
         is_private=False,
         is_verified=False,
         profile_pic_url="https://example.invalid/pic.jpg",
      ),
      media_type=8,
      product_type="carousel_container",
      like_count=41,
      comment_count=3,
      has_liked=False,
      is_seen=True,
      caption="a caption",
   )


def a_feed_page(
   *, has_next_page: bool, end_cursor: str | None, kinds: tuple[FeedItemKind, ...] | None = None
) -> Page[FeedItem]:
   """A feed page whose default shape is the measured one: more items than posts."""

   chosen = kinds or (FeedItemKind.POST, FeedItemKind.AD, FeedItemKind.EXPLORE_STORY)
   items = tuple(
      FeedItem(kind=kind, post=a_post(f"C{index:010d}") if kind is FeedItemKind.POST else None)
      for index, kind in enumerate(chosen)
   )

   return Page(items=items, has_next_page=has_next_page, end_cursor=end_cursor)


class FakeClient:
   """A `Client` that records what it was asked for and answers from a script."""

   def __init__(
      self,
      session: Session,
      pages: list[Page[Message]] | None = None,
      failure: BaseException | None = None,
      token_harvested: str | None = None,
      profile: Profile | None = None,
      feed_pages: list[Page[FeedItem]] | None = None,
      notes: tuple[Note, ...] = (),
   ) -> None:
      self.session = session
      self.pages = pages or [a_page(has_next_page=False, end_cursor=None)]
      self.failure = failure
      self.token_harvested = token_harvested
      self.profile_answer = profile if profile is not None else a_profile()
      self.feed_pages = feed_pages or [a_feed_page(has_next_page=False, end_cursor=None)]
      self.notes_answer = notes
      self.calls: list[dict[str, object]] = []
      self.closed = False

   def thread_messages(
      self,
      thread_fbid: str,
      *,
      after: str | None = None,
      newer_than_message_id: str | None = None,
   ) -> Page[Message]:
      self.calls.append(
         {
            "thread_fbid": thread_fbid,
            "after": after,
            "newer_than_message_id": newer_than_message_id,
         }
      )

      if self.failure is not None:
         raise self.failure

      if self.token_harvested is not None:
         self.session.fb_dtsg = self.token_harvested

      index = min(len(self.calls) - 1, len(self.pages) - 1)

      return self.pages[index]

   def feed(self, *, after: str | None = None) -> Page[FeedItem]:
      self.calls.append({"feed_after": after})

      if self.failure is not None:
         raise self.failure

      if self.token_harvested is not None:
         self.session.fb_dtsg = self.token_harvested

      index = min(len(self.calls) - 1, len(self.feed_pages) - 1)

      return self.feed_pages[index]

   def profile(self, username: str) -> Profile:
      self.calls.append({"profile_username": username})

      if self.failure is not None:
         raise self.failure

      if self.token_harvested is not None:
         self.session.fb_dtsg = self.token_harvested

      return self.profile_answer

   def profile_by_id(self, user_id: str) -> Profile:
      self.calls.append({"profile_user_id": user_id})

      if self.failure is not None:
         raise self.failure

      if self.token_harvested is not None:
         self.session.fb_dtsg = self.token_harvested

      return self.profile_answer

   def notes(self) -> tuple[Note, ...]:
      self.calls.append({"notes": True})

      if self.failure is not None:
         raise self.failure

      if self.token_harvested is not None:
         self.session.fb_dtsg = self.token_harvested

      return self.notes_answer

   def close(self) -> None:
      self.closed = True


def run(
   argv: list[str],
   *,
   client: FakeClient | None = None,
   environment: dict[str, str] | None = None,
) -> tuple[int, str, str]:
   out = io.StringIO()
   errors = io.StringIO()

   def factory(path: Path, *, user_agent: str | None = None) -> FakeClient:
      assert client is not None, "this command was not supposed to build a client"

      return client

   code = main(
      argv,
      environment=environment or {},
      client_factory=factory,
      stdout=out,
      stderr=errors,
   )

   return code, out.getvalue(), errors.getvalue()


def option_strings(parser: argparse.ArgumentParser) -> list[str]:
   found: list[str] = []

   for action in parser._actions:
      found.extend(action.option_strings)

      if isinstance(action, argparse._SubParsersAction):
         for subparser in action.choices.values():
            found.extend(option_strings(subparser))

   return found


def names_cookie_material(options: list[str]) -> list[str]:
   forbidden = ("sessionid", "csrftoken", "token", "password", "secret", "dtsg")

   return [option for option in options if any(word in option.lower() for word in forbidden)]


def test_no_option_takes_cookie_material() -> None:
   """`argv` is world-readable through `ps` and lands in shell history.

   The positive control is the second assertion. A scan finding nothing proves nothing until
   the same scan is shown finding a known bad option.
   """

   assert names_cookie_material(option_strings(build_parser())) == []
   assert names_cookie_material(["--json", "--sessionid"]) == ["--sessionid"]


def test_the_cli_reaches_no_capability_module_directly() -> None:
   """A CLI that imports `_core.direct` stops proving the public surface is usable.

   Redaction is the one internal import allowed, because stderr passes through it. The last
   assertion is the positive control.
   """

   imports = [
      line
      for source in sorted(CLI_DIRECTORY.glob("*.py"))
      for line in source.read_text(encoding="utf-8").splitlines()
      if line.startswith("from dumpstagram.") or line.startswith("import dumpstagram.")
   ]
   reaching_past_the_facade = [
      line
      for line in imports
      if ("_private" in line) or ("_core" in line and "_core.redaction" not in line)
   ]

   assert reaching_past_the_facade == []
   assert imports != []
   assert "_core" in "from dumpstagram._core.direct import read_thread_messages"


def test_every_public_error_has_its_own_exit_code() -> None:
   """A harness cannot branch on prose, so a new error class needs a number, not a fallback."""

   def descendants(base: type[BaseException]) -> set[type[BaseException]]:
      found = set(base.__subclasses__())

      for subclass in base.__subclasses__():
         found |= descendants(subclass)

      return found

   assert descendants(DumpstagramError) | {DumpstagramError} == set(EXIT_BY_ERROR)
   assert len(set(EXIT_BY_ERROR.values())) == len(EXIT_BY_ERROR)


def test_exit_code_for_walks_the_inheritance_chain() -> None:
   """A caller's own subclass exits as its closest public ancestor rather than as a crash."""

   class CallerDefined(RateLimited):
      pass

   assert exit_code_for(CallerDefined("slow down")) == 5
   assert exit_code_for(ValueError("not ours")) == 1


def test_a_checkpoint_exits_with_its_own_code(tmp_path: Path) -> None:
   session_path = tmp_path / "session.json"
   a_session().save(session_path)

   client = FakeClient(a_session(), failure=CheckpointRequired("a challenge is waiting"))
   code, out, errors = run(["--session", str(session_path), "thread", "123"], client=client)

   assert code == 4
   assert "CheckpointRequired" in errors
   assert out == ""


def test_stderr_never_carries_a_credential(tmp_path: Path) -> None:
   """A failure message is the one place a cookie reaches output with nobody writing it there.

   The second and third assertions are the positive control: the value is in the message the
   library raised, and redaction is what keeps it off the stream.
   """

   session_path = tmp_path / "session.json"
   a_session().save(session_path)

   leaky = AuthenticationFailed(f"the upstream refused sessionid={SESSIONID}")
   client = FakeClient(a_session(), failure=leaky)
   code, _, errors = run(["--session", str(session_path), "thread", "123"], client=client)

   assert code == 3
   assert SESSIONID not in errors
   assert SESSIONID in str(leaky)
   assert "<redacted>" in errors


def test_pagination_stops_on_the_servers_own_signal(tmp_path: Path) -> None:
   """A short page is not the end of a thread, and a full one is not proof of another."""

   session_path = tmp_path / "session.json"
   a_session().save(session_path)

   client = FakeClient(
      a_session(),
      pages=[
         a_page(has_next_page=True, end_cursor="cursor-1", message_count=20),
         a_page(has_next_page=False, end_cursor="cursor-2", message_count=20),
      ],
   )
   code, _, _ = run(
      ["--session", str(session_path), "thread", "123", "--pages", "5"], client=client
   )

   assert code == 0
   assert len(client.calls) == 2


def test_each_page_after_the_first_carries_the_previous_cursor(tmp_path: Path) -> None:
   session_path = tmp_path / "session.json"
   a_session().save(session_path)

   client = FakeClient(
      a_session(),
      pages=[
         a_page(has_next_page=True, end_cursor="cursor-1"),
         a_page(has_next_page=True, end_cursor="cursor-2"),
         a_page(has_next_page=False, end_cursor=None),
      ],
   )
   run(["--session", str(session_path), "thread", "123", "--pages", "3"], client=client)

   assert [call["after"] for call in client.calls] == [None, "cursor-1", "cursor-2"]


def test_the_top_up_marker_is_sent_on_the_first_page_only(tmp_path: Path) -> None:
   """Sending a cursor and a marker together asks a question nobody has measured an answer to."""

   session_path = tmp_path / "session.json"
   a_session().save(session_path)

   client = FakeClient(
      a_session(),
      pages=[
         a_page(has_next_page=True, end_cursor="cursor-1"),
         a_page(has_next_page=False, end_cursor=None),
      ],
   )
   run(
      ["--session", str(session_path), "thread", "123", "--pages", "2", "--since", "mid.99"],
      client=client,
   )

   assert [call["newer_than_message_id"] for call in client.calls] == ["mid.99", None]


def test_json_reports_more_available_from_the_page_not_the_message_count(tmp_path: Path) -> None:
   """An empty page that claims a successor still has one, and a full page may be the last."""

   session_path = tmp_path / "session.json"
   a_session().save(session_path)

   client = FakeClient(
      a_session(), pages=[a_page(has_next_page=True, end_cursor="cursor-1", message_count=0)]
   )
   code, out, _ = run(["--session", str(session_path), "--json", "thread", "123"], client=client)
   payload = json.loads(out)

   assert code == 0
   assert payload["message_count"] == 0
   assert payload["more_available"] is True
   assert payload["end_cursor"] == "cursor-1"


def test_json_carries_the_documented_message_fields(tmp_path: Path) -> None:
   session_path = tmp_path / "session.json"
   a_session().save(session_path)

   client = FakeClient(a_session())
   _, out, _ = run(["--session", str(session_path), "--json", "thread", "123"], client=client)
   message = json.loads(out)["messages"][0]

   assert message["id"] == "mid.0"
   assert message["sender_fbid"] == "100000000000000"
   assert message["sent_at"] == "2026-09-21T02:30:00+00:00"
   assert message["content_type"] == "TEXT"


def test_the_client_is_closed_even_when_the_read_fails(tmp_path: Path) -> None:
   """A CLI that leaks the loop thread on a failure hangs instead of exiting."""

   session_path = tmp_path / "session.json"
   a_session().save(session_path)

   client = FakeClient(a_session(), failure=RateLimited("too fast"))
   code, _, _ = run(["--session", str(session_path), "thread", "123"], client=client)

   assert code == 5
   assert client.closed is True


def test_a_token_harvested_during_a_read_is_written_back(tmp_path: Path) -> None:
   """Without the write-back every invocation pays a bootstrap request it already paid for."""

   session_path = tmp_path / "session.json"
   a_session().save(session_path)

   client = FakeClient(a_session(), token_harvested="fresh-token")
   code, _, _ = run(["--session", str(session_path), "thread", "123"], client=client)

   assert code == 0
   assert Session.load(session_path).fb_dtsg == "fresh-token"


def test_an_unchanged_token_is_not_written_back(tmp_path: Path) -> None:
   """Rewriting a credential file that did not change is a write nobody asked for."""

   session_path = tmp_path / "session.json"
   a_session().save(session_path)

   session = a_session(fb_dtsg="already-had-one")
   saves: list[Path] = []
   session.save = lambda path: saves.append(Path(path))  # type: ignore[method-assign]

   code, _, _ = run(
      ["--session", str(session_path), "thread", "123"],
      client=FakeClient(session, token_harvested="already-had-one"),
   )

   assert code == 0
   assert saves == []


def test_write_back_can_be_refused(tmp_path: Path) -> None:
   session_path = tmp_path / "session.json"
   a_session().save(session_path)

   client = FakeClient(a_session(), token_harvested="fresh-token")
   code, _, _ = run(
      ["--session", str(session_path), "thread", "123", "--no-session-writeback"],
      client=client,
   )

   assert code == 0
   assert Session.load(session_path).fb_dtsg is None


def test_adopt_writes_a_reloadable_owner_only_session_and_spends_no_request(
   tmp_path: Path,
) -> None:
   """Adoption is offline. A run that spends a request cannot be used to check credentials."""

   session_path = tmp_path / "session.json"
   environment = {
      "IG_SESSIONID": SESSIONID,
      "IG_DS_USER_ID": "17841400000000000",
      "IG_CSRFTOKEN": CSRFTOKEN,
      "IG_MID": "a-mid-value",
   }

   code, out, errors = run(["--session", str(session_path), "adopt"], environment=environment)
   reloaded = Session.load(session_path)

   assert code == 0
   assert errors == ""
   assert "requests_spent: 0" in out
   assert reloaded.ds_user_id == "17841400000000000"
   assert reloaded.extra_cookies == {"mid": "a-mid-value"}
   assert stat.filemode(session_path.stat().st_mode) == "-rw-------"


def test_adopt_carries_fr_onto_the_session_and_never_into_the_cookie_jar(
   tmp_path: Path,
) -> None:
   """Catches `IG_FR` dropped at intake, or sent as a cookie, which no browser does."""

   session_path = tmp_path / "session.json"
   environment = {
      "IG_SESSIONID": SESSIONID,
      "IG_DS_USER_ID": "17841400000000000",
      "IG_CSRFTOKEN": CSRFTOKEN,
      "IG_FR": "an-fr-value",
   }

   code, out, _ = run(["--session", str(session_path), "adopt"], environment=environment)
   reloaded = Session.load(session_path)

   assert code == 0
   assert reloaded.fr == "an-fr-value"
   assert "an-fr-value" not in reloaded.extra_cookies.values()
   assert "an-fr-value" not in out


def test_adopt_names_every_missing_key_at_once(tmp_path: Path) -> None:
   """Reporting one missing cookie at a time turns three cookies into three failed runs."""

   code, _, errors = run(
      ["--session", str(tmp_path / "session.json"), "adopt"],
      environment={"IG_SESSIONID": SESSIONID},
   )

   assert code == 3
   assert "IG_DS_USER_ID" in errors
   assert "IG_CSRFTOKEN" in errors


def test_a_cookie_file_answers_instead_of_the_environment(tmp_path: Path) -> None:
   """A file passed explicitly is the source. Reading the environment anyway adopts the wrong
   account silently, which a summary showing the right `ds_user_id` would not reveal.
   """

   cookies = tmp_path / "cookies.env"
   cookies.write_text(
      "# pasted from the browser\n"
      f'IG_SESSIONID="{SESSIONID}"\n'
      "IG_DS_USER_ID=17841400000000000\n"
      f"IG_CSRFTOKEN={CSRFTOKEN}\n",
      encoding="utf-8",
   )
   session_path = tmp_path / "session.json"

   code, _, _ = run(
      ["--session", str(session_path), "adopt", "--cookies-file", str(cookies)],
      environment={
         "IG_SESSIONID": "a-different-accounts-token",
         "IG_DS_USER_ID": "17841499999999999",
         "IG_CSRFTOKEN": "a-different-accounts-csrf",
      },
   )
   adopted = Session.load(session_path)

   assert code == 0
   assert adopted.sessionid == SESSIONID
   assert adopted.ds_user_id == "17841400000000000"


def test_the_session_command_prints_no_credential(tmp_path: Path) -> None:
   """The summary reports the account, not the token. The control is the file itself."""

   session_path = tmp_path / "session.json"
   a_session(fb_dtsg="a-token", lsd="an-lsd").save(session_path)

   code, out, _ = run(["--session", str(session_path), "session"])

   assert code == 0
   assert "17841400000000000" in out
   assert "bootstrapped: True" in out
   assert SESSIONID not in out
   assert SESSIONID in session_path.read_text(encoding="utf-8")


def test_a_missing_session_path_is_a_usage_error() -> None:
   code, _, errors = run(["session"])

   assert code == 2
   assert "DUMPSTAGRAM_SESSION" in errors


def test_the_session_path_comes_from_the_environment_when_no_flag_is_given(
   tmp_path: Path,
) -> None:
   session_path = tmp_path / "session.json"
   a_session().save(session_path)

   code, out, _ = run(["session"], environment={"DUMPSTAGRAM_SESSION": str(session_path)})

   assert code == 0
   assert str(session_path) in out


def test_an_unreadable_session_file_is_a_usage_error(tmp_path: Path) -> None:
   code, _, errors = run(["--session", str(tmp_path / "absent.json"), "session"])

   assert code == 2
   assert "absent.json" in errors


def test_a_page_count_below_one_is_refused_before_a_request(tmp_path: Path) -> None:
   with pytest.raises(SystemExit) as refused:
      run(["--session", str(tmp_path / "session.json"), "thread", "123", "--pages", "0"])

   assert refused.value.code == 2


def test_the_profile_command_reads_by_username_by_default() -> None:
   """Catches a command that quietly treats every argument as an id and never resolves."""

   client = FakeClient(a_session())
   code, out, errors = run(
      ["--session", "/tmp/session.json", "profile", "an-account"], client=client
   )

   assert code == 0
   assert client.calls == [{"profile_username": "an-account"}]
   assert "an-account" in out
   assert errors == ""


def test_the_profile_command_skips_resolution_under_by_id() -> None:
   """The flag exists to spend one request instead of two, so it must reach the other call."""

   client = FakeClient(a_session())
   code, out, _ = run(
      ["--session", "/tmp/session.json", "--json", "profile", "58435292991", "--by-id"],
      client=client,
   )

   assert code == 0
   assert client.calls == [{"profile_user_id": "58435292991"}]
   assert json.loads(out)["requests_spent"] == 1


def test_the_profile_command_reports_two_requests_when_it_resolves() -> None:
   client = FakeClient(a_session())
   _, out, _ = run(
      ["--session", "/tmp/session.json", "--json", "profile", "an-account"], client=client
   )

   assert json.loads(out)["requests_spent"] == 2


def test_the_profile_json_form_carries_the_identity_and_the_counts() -> None:
   """The JSON keys are a contract, so a renamed one breaks whatever scripts this command."""

   client = FakeClient(a_session())
   _, out, _ = run(
      ["--session", "/tmp/session.json", "--json", "profile", "an-account"], client=client
   )

   described = json.loads(out)["profile"]

   assert described["id"] == "58435292991"
   assert described["username"] == "an-account"
   assert described["follower_count"] == 80
   assert described["following_count"] == 124
   assert described["media_count"] == 8


def test_the_profile_command_prints_no_credential_when_the_read_fails() -> None:
   """The same redaction gate the thread command has, because stderr is the leak path.

   The message carries the credential in the ``sessionid=`` form the redactor recognises,
   which is the form the library itself produces, so this gates redaction rather than luck.
   """

   leaky = AuthenticationFailed(f"the upstream refused sessionid={SESSIONID}")
   client = FakeClient(a_session(), failure=leaky)
   code, _, errors = run(["--session", "/tmp/session.json", "profile", "an-account"], client=client)

   assert code == EXIT_BY_ERROR[AuthenticationFailed]
   assert SESSIONID not in errors


def test_the_profile_command_closes_its_client_even_when_the_read_fails() -> None:
   client = FakeClient(a_session(), failure=RateLimited("slow down"))
   code, _, _ = run(["--session", "/tmp/session.json", "profile", "an-account"], client=client)

   assert code == EXIT_BY_ERROR[RateLimited]
   assert client.closed


def test_the_feed_command_reads_one_page_by_default() -> None:
   """Catches a command that paginates on its own and spends requests nobody asked for."""

   client = FakeClient(a_session())
   code, out, errors = run(["--session", "/tmp/session.json", "feed"], client=client)

   assert code == 0
   assert client.calls == [{"feed_after": None}]
   assert "an-account" in out
   assert errors == ""


def test_the_feed_command_stops_on_the_terminator_and_not_on_a_page_length() -> None:
   """Catches a loop that treats a short page as the end, which every measured page was."""

   client = FakeClient(
      a_session(),
      feed_pages=[
         a_feed_page(has_next_page=True, end_cursor="cursor-one"),
         a_feed_page(has_next_page=False, end_cursor=None),
      ],
   )
   code, out, _ = run(
      ["--session", "/tmp/session.json", "--json", "feed", "--pages", "4"], client=client
   )

   assert code == 0
   assert client.calls == [{"feed_after": None}, {"feed_after": "cursor-one"}]
   assert json.loads(out)["pages_read"] == 2
   assert json.loads(out)["more_available"] is False


def test_the_feed_command_passes_a_given_cursor_to_the_first_request() -> None:
   client = FakeClient(a_session())
   run(["--session", "/tmp/session.json", "feed", "--after", "a-cursor"], client=client)

   assert client.calls == [{"feed_after": "a-cursor"}]


def test_the_feed_json_form_separates_items_from_posts() -> None:
   """Catches a count that conflates the two, which differed on every measured page."""

   client = FakeClient(a_session())
   _, out, _ = run(["--session", "/tmp/session.json", "--json", "feed"], client=client)

   described = json.loads(out)

   assert described["item_count"] == 3
   assert described["post_count"] == 1
   assert described["kinds"] == {"ad": 1, "explore_story": 1, "media": 1}


def test_the_feed_json_form_carries_the_post_identity_and_its_author() -> None:
   """The JSON keys are a contract, so a renamed one breaks whatever scripts this command."""

   client = FakeClient(a_session())
   _, out, _ = run(["--session", "/tmp/session.json", "--json", "feed"], client=client)

   post = json.loads(out)["items"][0]["post"]

   assert post["pk"] == "3757563240116259739"
   assert post["id"] == "3757563240116259739_50476469797"
   assert post["author"]["username"] == "an-account"
   assert post["like_count"] == 41


def test_posts_only_hides_the_other_items_but_still_counts_them() -> None:
   """Catches a filter that also filters the trailer, making a page look shorter than it was."""

   client = FakeClient(a_session())
   _, out, _ = run(
      ["--session", "/tmp/session.json", "--json", "feed", "--posts-only"], client=client
   )

   described = json.loads(out)

   assert len(described["items"]) == 1
   assert described["item_count"] == 3
   assert described["post_count"] == 1


def test_the_feed_command_prints_no_credential_when_the_read_fails() -> None:
   """The same redaction gate the other commands have, because stderr is the leak path."""

   client = FakeClient(
      a_session(), failure=AuthenticationFailed(f"the call failed with sessionid={SESSIONID}")
   )
   code, _, errors = run(["--session", "/tmp/session.json", "feed"], client=client)

   assert code == exit_code_for(AuthenticationFailed("x"))
   assert SESSIONID not in errors


def test_the_feed_command_closes_its_client_even_when_the_read_fails() -> None:
   """A failed read that leaks the loop thread makes the command hang instead of exiting."""

   client = FakeClient(a_session(), failure=RateLimited("slow down"))
   run(["--session", "/tmp/session.json", "feed"], client=client)

   assert client.closed is True


def a_note(note_id: str, author_id: str) -> Note:
   return Note(
      id=note_id,
      author_id=author_id,
      text="a note body",
      audience=NoteAudience.CLOSE_FRIENDS,
      created_at=datetime(2026, 9, 22, 23, 55, 36, tzinfo=UTC),
      is_emoji_only=False,
      author_username="an.author",
   )


def test_the_note_list_marks_the_note_authored_by_the_viewer() -> None:
   """Catches the own note picked by position or by the item id instead of by the author."""

   viewer_id = "17841400000000000"
   notes = (a_note("18000000000000002", "58435292991"), a_note(viewer_id, "11111111111"))
   notes = (*notes, a_note("18000000000000001", viewer_id))
   client = FakeClient(a_session(), notes=notes)

   code, out, _ = run(["--json", "--session", "s.json", "note", "list"], client=client)

   payload = json.loads(out)

   assert code == 0
   assert payload["note_count"] == 3
   assert payload["own_note_id"] == "18000000000000001"
   assert [note["is_own"] for note in payload["notes"]] == [False, False, True]
   assert payload["notes"][0]["audience"] == "close_friends"


class FakeListener:
   """A blocking listener that hands out one scripted batch per wait, then nothing."""

   def __init__(self, batches: list[list[Event]]) -> None:
      self.batches = list(batches)
      self.started = False
      self.stopped = False

   def start(self) -> None:
      self.started = True

   def stop(self) -> None:
      self.stopped = True

   def wait_for_events(self, timeout: float | None) -> list[Event]:
      if self.batches:
         return self.batches.pop(0)

      time.sleep(min(timeout or 0.01, 0.01))

      return []


class FakeListeningClient:
   def __init__(self, listener: FakeListener) -> None:
      self.session = a_session()
      self.listener = listener
      self.since: str | None = None
      self.behavior: Behavior | None = None
      self.closed = False

   def events(self, *, since: str | None = None) -> FakeListener:
      self.since = since

      return self.listener

   def close(self) -> None:
      self.closed = True


class FakeAsyncListeningClient:
   def __init__(self, events: list[Event]) -> None:
      self.session = a_session()
      self.scripted = events
      self.since: str | None = None
      self.behavior: Behavior | None = None
      self.closed = False

   async def events(self, *, since: str | None = None) -> AsyncIterator[Event]:
      self.since = since

      for event in self.scripted:
         yield event

      await asyncio.Event().wait()

   async def aclose(self) -> None:
      self.closed = True


SECRET_TEXT = "a body that must never reach a log"


def a_new_message() -> NewMessage:
   message = a_message("mid.$e1")

   return NewMessage(
      message=replace(message, text=SECRET_TEXT, sender=MessageSender(fbid="1", name="a name"))
   )


def run_events(
   argv: list[str],
   *,
   blocking: FakeListeningClient | None = None,
   awaitable: FakeAsyncListeningClient | None = None,
) -> tuple[int, str]:
   out = io.StringIO()

   def blocking_factory(
      path: Path, *, user_agent: str | None, behavior: Behavior
   ) -> FakeListeningClient:
      assert blocking is not None, "the blocking surface was not supposed to be used"
      blocking.behavior = behavior

      return blocking

   def async_factory(
      path: Path, *, user_agent: str | None, behavior: Behavior
   ) -> FakeAsyncListeningClient:
      assert awaitable is not None, "the async surface was not supposed to be used"
      awaitable.behavior = behavior

      return awaitable

   code = main(
      ["--session", "unused.json", *argv],
      environment={},
      listening_client_factory=blocking_factory,
      async_listening_client_factory=async_factory,
      stdout=out,
      stderr=io.StringIO(),
   )

   return code, out.getvalue()


def test_events_prints_one_json_object_per_event_and_a_summary() -> None:
   """Catches --json ignored for a stream, which hands a script lines it cannot parse."""

   listener = FakeListener([[a_new_message(), EventsDropped(count=None, thread_fbid="17")]])
   code, out = run_events(
      ["--json", "events", "--duration", "0.2", "--no-session-writeback"],
      blocking=FakeListeningClient(listener),
   )

   lines = [json.loads(line) for line in out.splitlines()]

   assert code == 0
   assert lines[0]["event"] == "new_message"
   assert lines[0]["message"]["id"] == "mid.$e1"
   assert lines[1] == {"event": "events_dropped", "count": None, "thread_fbid": "17"}
   assert lines[2]["command"] == "events"
   assert lines[2]["new_messages"] == 1
   assert lines[2]["events_dropped"] == 1


def test_events_ids_only_never_prints_a_messages_text_or_sender_name() -> None:
   """Catches --ids-only leaking a message body, which a live run's log must never hold. The
   positive control is the same event printed without the flag, which does carry the text."""

   printed = {}

   for form in (["--json"], []):
      for flag in (["--ids-only"], []):
         listener = FakeListener([[a_new_message()]])
         _, out = run_events(
            [*form, "events", "--duration", "0.1", "--no-session-writeback", *flag],
            blocking=FakeListeningClient(listener),
         )
         printed[(bool(form), bool(flag))] = out

   assert SECRET_TEXT not in printed[(True, True)]
   assert "a name" not in printed[(True, True)]
   assert SECRET_TEXT not in printed[(False, True)]
   assert "mid.$e1" in printed[(True, True)]
   assert SECRET_TEXT in printed[(True, False)]
   assert SECRET_TEXT in printed[(False, False)]


def test_events_stops_the_listener_when_the_duration_ends() -> None:
   """Catches a command that returns with its listener still polling the account."""

   listener = FakeListener([])
   client = FakeListeningClient(listener)

   code, _ = run_events(
      ["events", "--duration", "0.1", "--since", "mid.$e0", "--no-session-writeback"],
      blocking=client,
   )

   assert code == 0
   assert listener.started
   assert listener.stopped
   assert client.closed
   assert client.since == "mid.$e0"


def test_a_listener_stopped_by_a_checkpoint_exits_with_the_checkpoint_code() -> None:
   """Catches the blocking listener's final event printed and ignored, which ends a run that a
   checkpoint stopped with exit 0."""

   failure = CheckpointRequired("a checkpoint")
   listener = FakeListener([[ListenerStopped(error=failure)]])

   code, _ = run_events(
      ["events", "--duration", "5", "--no-session-writeback"],
      blocking=FakeListeningClient(listener),
   )

   assert code == exit_code_for(failure)
   assert listener.stopped


def test_events_on_the_async_surface_reads_the_async_iterator() -> None:
   """Catches --surface async quietly running the blocking listener instead, and the chosen
   interval and since not reaching the client."""

   client = FakeAsyncListeningClient([a_new_message()])

   code, out = run_events(
      [
         "--json",
         "events",
         "--surface",
         "async",
         "--duration",
         "0.2",
         "--interval",
         "7",
         "--since",
         "mid.$e0",
         "--ids-only",
         "--no-session-writeback",
      ],
      awaitable=client,
   )

   lines = [json.loads(line) for line in out.splitlines()]

   assert code == 0
   assert lines[0]["message"]["id"] == "mid.$e1"
   assert lines[-1]["surface"] == "async"
   assert client.since == "mid.$e0"
   assert client.behavior is not None
   assert client.behavior.poll_interval_seconds == 7.0
   assert client.closed
