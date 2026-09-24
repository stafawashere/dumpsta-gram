"""Break the source, watch each CLI gate go red, restore.

Same harness and same rule as ``verify_phase2_gates.py``: one mutation per gate, only the
gate that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

Two gates in ``tests/test_cli.py`` have no row here, and deliberately. The adoption path
spends no live request because ``run_adopt`` takes no client factory, which is a property of
its signature rather than of a branch, and the two positive controls inside the cookie-option
and capability-import gates are what proves those checks can see anything at all.

Run from ``engine/`` with ``uv run python scripts/verify_cli_gates.py``. Writes its result to
``engine/logs/``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
LOG_DIR = ENGINE / "logs"

MAIN = "dumpstagram/_cli/main.py"
COMMANDS_COMMON = "dumpstagram/_cli/commands/common.py"
COMMANDS_DIRECT = "dumpstagram/_cli/commands/direct.py"
COMMANDS_SESSION = "dumpstagram/_cli/commands/session.py"
EXITS = "dumpstagram/_cli/exits.py"
COOKIE_SOURCES = "dumpstagram/_cli/cookie_sources.py"
RENDER_DIRECT = "dumpstagram/_cli/render/direct.py"
RENDER_SESSION = "dumpstagram/_cli/render/session.py"

WRITEBACK_UNDER_A_TRY = """   try:
      pages = read_pages(client, arguments)

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_read
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)
   finally:
      client.close()"""

WRITEBACK_WITHOUT_ONE = """   pages = read_pages(client, arguments)

   harvested_a_new_token = client.session.fb_dtsg != token_before_the_read
   may_write_back = not arguments.no_session_writeback

   if harvested_a_new_token and may_write_back:
      client.session.save(path)

   client.close()"""

EXIT_CODE_WALKS_THE_CHAIN = """   for ancestor in type(failure).__mro__:
      if ancestor in EXIT_BY_ERROR:
         return EXIT_BY_ERROR[ancestor]

   return 1"""

EXIT_CODE_READS_THE_EXACT_TYPE = """   exact = type(failure)

   if exact in EXIT_BY_ERROR:
      return EXIT_BY_ERROR[exact]

   return 1"""

THREAD_OPTIONS = """   thread.add_argument(
      "--user-agent","""

THREAD_OPTIONS_PLUS_A_COOKIE = """   thread.add_argument(
      "--sessionid",
      metavar="VALUE",
      help="the session cookie, which belongs nowhere near a command line",
   )
   thread.add_argument(
      "--user-agent","""

MISSING_KEYS_ALL_AT_ONCE = """   missing = [key for key in REQUIRED_KEYS if not source.get(key)]"""
MISSING_KEYS_ONE_AT_A_TIME = (
   """   missing = [key for key in REQUIRED_KEYS if not source.get(key)][:1]"""
)

COOKIE_FILE_WINS = """   source = (
      read_cookie_file(Path(arguments.cookies_file))
      if arguments.cookies_file
      else dict(environment)
   )"""

COOKIE_FILE_IGNORED = """   source = dict(environment)"""

THREAD_PAGE_LOOP_TAIL = """      if not page.has_next_page:
         break

      cursor = page.end_cursor
      newer_than = None"""

THREAD_WRITEBACK = """      pages = read_pages(client, arguments)

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_read
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)"""

THREAD_MORE_AVAILABLE = """      "message_count": sum(len(page.items) for page in pages),
      "more_available": last.has_next_page if last is not None else False,"""

THREAD_SENT_AT = """      "sender_name": message.sender.name,
      "sent_at": message.sent_at.isoformat(),"""

MUTATIONS = [
   {
      "gate": "tests/test_cli.py::test_no_option_takes_cookie_material",
      "defect": "cookie material on the command line, readable by `ps` and kept in history",
      "file": COMMANDS_DIRECT,
      "find": THREAD_OPTIONS,
      "replace": THREAD_OPTIONS_PLUS_A_COOKIE,
   },
   {
      "gate": "tests/test_cli.py::test_the_cli_reaches_no_capability_module_directly",
      "defect": "the harness reaches past the facade, so it stops proving the facade works",
      "file": MAIN,
      "find": "from dumpstagram._core.redaction import redact",
      "replace": (
         "from dumpstagram._core.direct import read_thread_messages\n"
         "from dumpstagram._core.redaction import redact"
      ),
   },
   {
      "gate": "tests/test_cli.py::test_every_public_error_has_its_own_exit_code",
      "defect": "a public error class with no code of its own, arriving as the generic one",
      "file": EXITS,
      "find": "   NotFound: 7,\n",
      "replace": "",
   },
   {
      "gate": "tests/test_cli.py::test_exit_code_for_walks_the_inheritance_chain",
      "defect": "a caller's own subclass exits as a crash rather than as its ancestor",
      "file": EXITS,
      "find": EXIT_CODE_WALKS_THE_CHAIN,
      "replace": EXIT_CODE_READS_THE_EXACT_TYPE,
   },
   {
      "gate": "tests/test_cli.py::test_a_checkpoint_exits_with_its_own_code",
      "defect": "every failure exits the same way, so a harness cannot tell them apart",
      "file": MAIN,
      "find": "      return exit_code_for(failure)",
      "replace": "      return 1",
   },
   {
      "gate": "tests/test_cli.py::test_stderr_never_carries_a_credential",
      "defect": "a session token reaches stderr inside a message nobody wrote by hand",
      "file": MAIN,
      "find": '      print(redact(f"{type(failure).__name__}: {failure}"), file=errors)',
      "replace": '      print(f"{type(failure).__name__}: {failure}", file=errors)',
   },
   {
      "gate": "tests/test_cli.py::test_pagination_stops_on_the_servers_own_signal",
      "defect": "pagination terminated on a heuristic, so a full last page costs a spare request",
      "file": COMMANDS_DIRECT,
      "find": THREAD_PAGE_LOOP_TAIL,
      "replace": THREAD_PAGE_LOOP_TAIL.replace("if not page.has_next_page", "if not page.items"),
   },
   {
      "gate": "tests/test_cli.py::test_each_page_after_the_first_carries_the_previous_cursor",
      "defect": "every page after the first re-reads the same page",
      "file": COMMANDS_DIRECT,
      "find": THREAD_PAGE_LOOP_TAIL,
      "replace": THREAD_PAGE_LOOP_TAIL.replace("page.end_cursor", "arguments.after"),
   },
   {
      "gate": "tests/test_cli.py::test_the_top_up_marker_is_sent_on_the_first_page_only",
      "defect": "a cursor and a top-up marker sent together, a combination nobody has measured",
      "file": COMMANDS_DIRECT,
      "find": "      cursor = page.end_cursor\n      newer_than = None",
      "replace": "      cursor = page.end_cursor",
   },
   {
      "gate": (
         "tests/test_cli.py::test_json_reports_more_available_from_the_page_not_the_message_count"
      ),
      "defect": "the terminator reported from how many messages arrived",
      "file": RENDER_DIRECT,
      "find": THREAD_MORE_AVAILABLE,
      "replace": THREAD_MORE_AVAILABLE.replace("last.has_next_page", "bool(last.items)"),
   },
   {
      "gate": "tests/test_cli.py::test_json_carries_the_documented_message_fields",
      "defect": "the machine-readable timestamp changed shape under whatever scripts it",
      "file": RENDER_DIRECT,
      "find": THREAD_SENT_AT,
      "replace": THREAD_SENT_AT.replace(
         "message.sent_at.isoformat()", "str(message.sent_at.timestamp())"
      ),
   },
   {
      "gate": "tests/test_cli.py::test_the_client_is_closed_even_when_the_read_fails",
      "defect": "a failed read leaves the loop thread running, so the command hangs",
      "file": COMMANDS_DIRECT,
      "find": WRITEBACK_UNDER_A_TRY,
      "replace": WRITEBACK_WITHOUT_ONE,
   },
   {
      "gate": "tests/test_cli.py::test_a_token_harvested_during_a_read_is_written_back",
      "defect": "every invocation pays a bootstrap request the previous one already paid",
      "file": COMMANDS_DIRECT,
      "find": THREAD_WRITEBACK,
      "replace": THREAD_WRITEBACK.replace(
         "if harvested_a_new_token and may_write_back",
         "if harvested_a_new_token and not may_write_back",
      ),
   },
   {
      "gate": "tests/test_cli.py::test_an_unchanged_token_is_not_written_back",
      "defect": "a credential file rewritten on every run for no reason",
      "file": COMMANDS_DIRECT,
      "find": THREAD_WRITEBACK,
      "replace": THREAD_WRITEBACK.replace(
         "harvested_a_new_token = client.session.fb_dtsg != token_before_the_read",
         "harvested_a_new_token = True",
      ),
   },
   {
      "gate": "tests/test_cli.py::test_write_back_can_be_refused",
      "defect": "the refusal flag is accepted and ignored",
      "file": COMMANDS_DIRECT,
      "find": THREAD_WRITEBACK,
      "replace": THREAD_WRITEBACK.replace(
         "may_write_back = not arguments.no_session_writeback", "may_write_back = True"
      ),
   },
   {
      "gate": (
         "tests/test_cli.py::"
         "test_adopt_writes_a_reloadable_owner_only_session_and_spends_no_request"
      ),
      "defect": "adoption reports success and writes nothing, so the next command has no file",
      "file": COMMANDS_SESSION,
      "find": "   session.save(path)\n\n   summary = describe_session(session, path)",
      "replace": "   summary = describe_session(session, path)",
   },
   {
      "gate": "tests/test_cli.py::test_adopt_names_every_missing_key_at_once",
      "defect": "three missing cookies become three failed runs",
      "file": COOKIE_SOURCES,
      "find": MISSING_KEYS_ALL_AT_ONCE,
      "replace": MISSING_KEYS_ONE_AT_A_TIME,
   },
   {
      "gate": "tests/test_cli.py::test_a_cookie_file_answers_instead_of_the_environment",
      "defect": "the file is accepted and the environment is read anyway, adopting one account "
      "while reporting another",
      "file": COMMANDS_SESSION,
      "find": COOKIE_FILE_WINS,
      "replace": COOKIE_FILE_IGNORED,
   },
   {
      "gate": "tests/test_cli.py::test_the_session_command_prints_no_credential",
      "defect": "the summary prints the session token to stdout",
      "file": RENDER_SESSION,
      "find": '      "ds_user_id": session.ds_user_id,',
      "replace": '      "ds_user_id": session.ds_user_id,\n      "sessionid": session.sessionid,',
   },
   {
      "gate": "tests/test_cli.py::test_a_missing_session_path_is_a_usage_error",
      "defect": "a guessed path writes an account token somewhere its owner did not choose",
      "file": COMMANDS_COMMON,
      "find": "   path = chosen or environment.get(SESSION_PATH_ENV)",
      "replace": '   path = chosen or environment.get(SESSION_PATH_ENV) or "state/session.json"',
   },
   {
      "gate": (
         "tests/test_cli.py::test_the_session_path_comes_from_the_environment_when_no_flag_is_given"
      ),
      "defect": "the environment variable is documented and never read",
      "file": COMMANDS_COMMON,
      "find": "   path = chosen or environment.get(SESSION_PATH_ENV)",
      "replace": "   path = chosen",
   },
   {
      "gate": "tests/test_cli.py::test_an_unreadable_session_file_is_a_usage_error",
      "defect": "a missing file arrives as a traceback rather than as an exit code",
      "file": MAIN,
      "find": "   except (UsageError, OSError) as failure:",
      "replace": "   except UsageError as failure:",
   },
   {
      "gate": "tests/test_cli.py::test_a_page_count_below_one_is_refused_before_a_request",
      "defect": "a nonsense page count is accepted and reads nothing while reporting success",
      "file": COMMANDS_COMMON,
      "find": "   if count < 1:",
      "replace": "   if count < 0:",
   },
]


def run_gate(gate: str) -> subprocess.CompletedProcess[str]:
   """Run one gate in a subprocess that cannot read a stale `.pyc`.

   CPython validates a cached bytecode file against the source's size and its mtime in whole
   seconds. A mutation that changes neither, which is any same-length edit applied and undone
   inside one second, is invisible to that check, and the run then reports the unmutated
   source. It produced two false results on 2026-09-21 before this was found: one mutation
   that looked harmless and one restore that looked broken.
   """

   environment = dict(os.environ)
   environment["PYTHONDONTWRITEBYTECODE"] = "1"

   for cached in ENGINE.glob("dumpstagram/**/__pycache__"):
      shutil.rmtree(cached, ignore_errors=True)

   return subprocess.run(
      [sys.executable, "-B", "-m", "pytest", gate, "-q", "--no-header", "-p", "no:cacheprovider"],
      cwd=ENGINE,
      capture_output=True,
      text=True,
      env=environment,
   )


def apply_mutation(mutation: dict[str, str]) -> str:
   path = ENGINE / mutation["file"]
   original = path.read_text(encoding="utf-8")

   occurrences = original.count(mutation["find"])

   if occurrences != 1:
      raise SystemExit(
         f"mutation anchor found {occurrences} times in {mutation['file']} "
         f"for {mutation['gate']}, expected exactly once"
      )

   path.write_text(original.replace(mutation["find"], mutation["replace"], 1), encoding="utf-8")

   return original


def main() -> int:
   results = []

   for mutation in MUTATIONS:
      path = ENGINE / mutation["file"]
      original = apply_mutation(mutation)

      try:
         mutated = run_gate(mutation["gate"])
      finally:
         path.write_text(original, encoding="utf-8")

      restored = run_gate(mutation["gate"])

      results.append(
         {
            "gate": mutation["gate"],
            "defect": mutation["defect"],
            "mutated_file": mutation["file"],
            "red_under_mutation": mutated.returncode != 0,
            "green_after_restore": restored.returncode == 0,
            "mutated_tail": mutated.stdout.strip().splitlines()[-1:],
         }
      )

   every_gate_fired = bool(results) and all(
      entry["red_under_mutation"] and entry["green_after_restore"] for entry in results
   )

   LOG_DIR.mkdir(parents=True, exist_ok=True)
   stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
   log_path = LOG_DIR / f"mutation-cli-{stamp}.json"
   log_path.write_text(
      json.dumps({"every_gate_fired": every_gate_fired, "gates": results}, indent=2) + "\n",
      encoding="utf-8",
   )

   for entry in results:
      status = (
         "red then green"
         if entry["red_under_mutation"] and entry["green_after_restore"]
         else "DID NOT FIRE"
      )
      print(f"{status}: {entry['gate']}")

   print(f"log written to {log_path}")

   return 0 if every_gate_fired else 1


if __name__ == "__main__":
   raise SystemExit(main())
