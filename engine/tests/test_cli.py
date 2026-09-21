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
import io
import json
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dumpstagram._cli.exits import EXIT_BY_ERROR, exit_code_for
from dumpstagram._cli.main import build_parser, main
from dumpstagram.errors import (
   AuthenticationFailed,
   CheckpointRequired,
   DumpstagramError,
   RateLimited,
)
from dumpstagram.models import Message, MessageSender, Page
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


def a_page(*, has_next_page: bool, end_cursor: str | None, message_count: int = 1) -> Page[Message]:
   return Page(
      items=tuple(a_message(f"mid.{index}") for index in range(message_count)),
      has_next_page=has_next_page,
      end_cursor=end_cursor,
   )


class FakeClient:
   """A `Client` that records what it was asked for and answers from a script."""

   def __init__(
      self,
      session: Session,
      pages: list[Page[Message]] | None = None,
      failure: BaseException | None = None,
      token_harvested: str | None = None,
   ) -> None:
      self.session = session
      self.pages = pages or [a_page(has_next_page=False, end_cursor=None)]
      self.failure = failure
      self.token_harvested = token_harvested
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
