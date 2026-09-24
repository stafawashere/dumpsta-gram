"""Break the source, watch each profile gate go red, restore.

Same harness and same rule as ``verify_cli_gates.py``: one mutation per gate, only the gate
that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

The field-rename gates in ``tests/test_profiles.py`` are parametrised over fourteen names and
share one mutation, because they share one mechanism: ``_required`` raising instead of
returning a default. Breaking it once is what shows all fourteen can fire.

Two gates have no row here and deliberately. The facade parity gate reads attributes off both
classes, so the only mutation that reaches it is deleting a method the rest of the file
already covers, and the typed-return gate is covered by the same mapper mutation as the
renames.

Run from ``engine/`` with ``uv run python scripts/verify_profile_gates.py``. Writes its result
to ``engine/logs/``.
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

CAPABILITY = "dumpstagram/_core/profiles.py"
MAIN = "dumpstagram/_cli/main.py"
COMMANDS_PROFILES = "dumpstagram/_cli/commands/profiles.py"
PARSE_COMMON = "dumpstagram/_private/web/parse/common.py"
PARSE_PROFILES = "dumpstagram/_private/web/parse/profiles.py"
REQUESTS_PROFILES = "dumpstagram/_private/web/requests/profiles.py"
RENDER_PROFILES = "dumpstagram/_cli/render/profiles.py"

REQUIRED_RAISES = """def _required(node: Any, key: str, path: str) -> Any:
   if not isinstance(node, dict) or key not in node:
      raise SchemaChanged(f"{path}.{key} is missing from the payload", path=f"{path}.{key}")

   return node[key]"""

REQUIRED_DEFAULTS = """def _required(node: Any, key: str, path: str) -> Any:
   if not isinstance(node, dict) or key not in node:
      return ""

   return node[key]"""

INTEGER_IS_CHECKED = """   if isinstance(value, bool) or not isinstance(value, int):
      raise SchemaChanged(f"{path}.{key} is not an integer", path=f"{path}.{key}")

   return value"""

INTEGER_IS_COERCED = """   return int(value)"""

FLAG_IS_CHECKED = """   if not isinstance(value, bool):
      raise SchemaChanged(f"{path}.{key} is not a boolean", path=f"{path}.{key}")

   return value"""

FLAG_IS_COERCED = """   return bool(value)"""

HD_WRAPPER_IS_CHECKED = """   if not isinstance(raw, dict):
      raise SchemaChanged(
         f"{path}.hd_profile_pic_url_info is not an object or null",
         path=f"{path}.hd_profile_pic_url_info",
      )

   return _optional_string(raw, "url", f"{path}.hd_profile_pic_url_info")"""

HD_WRAPPER_IS_SHRUGGED_AT = """   if not isinstance(raw, dict):
      return None

   return _optional_string(raw, "url", f"{path}.hd_profile_pic_url_info")"""

EMPTY_TIMELINE_IS_NOTHING = """   if not edges:
      return None

   node_path = f"{connection_path}.edges[0].node\""""

EMPTY_TIMELINE_IS_ZERO = """   if not edges:
      return "0"

   node_path = f"{connection_path}.edges[0].node\""""

READ_USES_THE_RESOLVED_ID = """   return await read_profile_by_id(
      sender,
      session,
      user_id,"""

READ_USES_THE_USERNAME = """   return await read_profile_by_id(
      sender,
      session,
      username,"""

RESOLUTION_RAISES = """      if user_id is None:
         raise NotFound("""

RESOLUTION_RETURNS_EMPTY = """      if user_id is None:
         return ""

      if False:
         raise NotFound("""

CLI_PICKS_A_ROUTE = """      if arguments.by_id:
         profile = client.profile_by_id(arguments.who)
      else:
         profile = client.profile(arguments.who)"""

CLI_ALWAYS_USES_THE_ID = """      profile = client.profile_by_id(arguments.who)"""

PROFILE_CLOSES_UNDER_A_TRY = """   finally:
      client.close()

   payload = {
      "command": "profile","""

PROFILE_CLOSES_WITHOUT_ONE = """   finally:
      pass

   payload = {
      "command": "profile","""

ID_ROUTE_READS_ONCE = """   async def attempt() -> Profile:
      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)

      request = build_profile_request("""

ID_ROUTE_BOOTSTRAPS_EVERY_TIME = """   async def attempt() -> Profile:
      await bootstrap(sender, session, user_agent=user_agent)

      request = build_profile_request("""

MUTATIONS = [
   {
      "gate": "tests/test_profiles.py::test_a_renamed_field_raises_rather_than_defaulting",
      "defect": "an upstream rename degrades every record instead of failing loudly",
      "file": PARSE_COMMON,
      "find": REQUIRED_RAISES,
      "replace": REQUIRED_DEFAULTS,
   },
   {
      "gate": "tests/test_profiles.py::test_a_count_that_stops_being_a_number_raises",
      "defect": "a count sent as a string is coerced, so a schema change looks like data",
      "file": PARSE_COMMON,
      "find": INTEGER_IS_CHECKED,
      "replace": INTEGER_IS_COERCED,
   },
   {
      "gate": "tests/test_profiles.py::test_a_boolean_sent_as_a_number_raises",
      "defect": "truthiness stands in for a boolean, so 0 reads as a real False",
      "file": PARSE_COMMON,
      "find": FLAG_IS_CHECKED,
      "replace": FLAG_IS_COERCED,
   },
   {
      "gate": "tests/test_profiles.py::test_an_hd_picture_wrapper_of_the_wrong_shape_raises",
      "defect": "an upstream shape change is reported as an account with no picture",
      "file": PARSE_COMMON,
      "find": HD_WRAPPER_IS_CHECKED,
      "replace": HD_WRAPPER_IS_SHRUGGED_AT,
   },
   {
      "gate": "tests/test_profiles.py::test_a_renamed_bio_link_field_raises",
      "defect": "the link tray degrades silently while the rest of the profile still maps",
      "file": PARSE_PROFILES,
      "find": '            lynx_url=_required_string(entry, "lynx_url", entry_path),',
      "replace": '            lynx_url=entry.get("lynx_url", ""),',
   },
   {
      "gate": (
         "tests/test_profiles.py::"
         "test_an_empty_timeline_resolves_to_nothing_rather_than_to_a_wrong_id"
      ),
      "defect": "an account with nothing visible resolves to an invented id",
      "file": PARSE_PROFILES,
      "find": EMPTY_TIMELINE_IS_NOTHING,
      "replace": EMPTY_TIMELINE_IS_ZERO,
   },
   {
      "gate": (
         "tests/test_profiles.py::test_the_profile_request_carries_the_account_id_and_its_document"
      ),
      "defect": "the profile query is sent with a rotated or mistyped document id",
      "file": REQUESTS_PROFILES,
      "find": '      "id": user_id,',
      "replace": '      "id": user_id[::-1],',
   },
   {
      "gate": (
         "tests/test_profiles.py::"
         "test_the_resolution_request_asks_for_one_post_and_names_the_username"
      ),
      "defect": "the resolver inherits the web client's twelve and moves 200 kB for one id",
      "file": REQUESTS_PROFILES,
      "find": "_profile_posts_variables(username, RESOLUTION_PAGE_SIZE)",
      "replace": "_profile_posts_variables(username, 12)",
   },
   {
      "gate": (
         "tests/test_profiles.py::"
         "test_reading_by_username_resolves_first_and_then_reads_by_the_resolved_id"
      ),
      "defect": "the username is sent where the account id belongs",
      "file": CAPABILITY,
      "find": READ_USES_THE_RESOLVED_ID,
      "replace": READ_USES_THE_USERNAME,
   },
   {
      "gate": (
         "tests/test_profiles.py::"
         "test_an_unresolvable_username_raises_not_found_and_spends_no_second_request"
      ),
      "defect": "an unresolvable username answers with an empty id instead of failing",
      "file": CAPABILITY,
      "find": RESOLUTION_RAISES,
      "replace": RESOLUTION_RETURNS_EMPTY,
   },
   {
      "gate": "tests/test_profiles.py::test_reading_by_id_spends_one_request",
      "defect": "the id route pays for a resolution it does not need",
      "file": CAPABILITY,
      "find": ID_ROUTE_READS_ONCE,
      "replace": ID_ROUTE_BOOTSTRAPS_EVERY_TIME,
   },
   {
      "gate": "tests/test_cli.py::test_the_profile_command_reads_by_username_by_default",
      "defect": "every argument is treated as an id, so a username is never resolved",
      "file": COMMANDS_PROFILES,
      "find": CLI_PICKS_A_ROUTE,
      "replace": CLI_ALWAYS_USES_THE_ID,
   },
   {
      "gate": "tests/test_cli.py::test_the_profile_command_reports_two_requests_when_it_resolves",
      "defect": "the reported cost stops matching the route that ran",
      "file": COMMANDS_PROFILES,
      "find": '      "requests_spent": 1 if arguments.by_id else 2,',
      "replace": '      "requests_spent": 1,',
   },
   {
      "gate": "tests/test_cli.py::test_the_profile_json_form_carries_the_identity_and_the_counts",
      "defect": "a contract key is renamed under whatever scripts the command",
      "file": RENDER_PROFILES,
      "find": '      "follower_count": profile.follower_count,',
      "replace": '      "followers": profile.follower_count,',
   },
   {
      "gate": (
         "tests/test_cli.py::test_the_profile_command_prints_no_credential_when_the_read_fails"
      ),
      "defect": "a session token reaches stderr inside a message nobody wrote by hand",
      "file": MAIN,
      "find": '      print(redact(f"{type(failure).__name__}: {failure}"), file=errors)',
      "replace": '      print(f"{type(failure).__name__}: {failure}", file=errors)',
   },
   {
      "gate": (
         "tests/test_cli.py::test_the_profile_command_closes_its_client_even_when_the_read_fails"
      ),
      "defect": "a failed read leaves the loop thread running, so the command hangs",
      "file": COMMANDS_PROFILES,
      "find": PROFILE_CLOSES_UNDER_A_TRY,
      "replace": PROFILE_CLOSES_WITHOUT_ONE,
   },
]


def run_gate(gate: str) -> subprocess.CompletedProcess[str]:
   """Run one gate in a subprocess that cannot read a stale `.pyc`.

   The reason is the one ``verify_cli_gates.py`` records: CPython validates cached bytecode
   against the source's size and its mtime in whole seconds, so a same-length edit applied and
   undone inside one second is invisible to that check.
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
   log_path = LOG_DIR / f"mutation-profile-{stamp}.json"
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
