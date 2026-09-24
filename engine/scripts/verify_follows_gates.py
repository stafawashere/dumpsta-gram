"""Break follow, unfollow and the relationship read, watch each gate go red, restore.

Same harness and same rule as ``verify_likes_gates.py``: one mutation per line below, only the
gate that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

The rows are the Step 17 table in ``engine/docs/build-plan.md``, its parity row held as the one
request's shape because the browser burst is unrecorded under ruling 23, and the gates this
step added beside them: the null flags another account's profile carries, the answer checks,
and the CLI commands.

Run from ``engine/`` with ``uv run python scripts/verify_follows_gates.py``. Writes its result to
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


COMMANDS_SOCIAL = "dumpstagram/_cli/commands/social.py"
PARSE_PROFILES = "dumpstagram/_private/web/parse/profiles.py"
PARSE_SOCIAL = "dumpstagram/_private/web/parse/social.py"
REQUESTS_SOCIAL = "dumpstagram/_private/web/requests/social.py"
FOLLOWS = "dumpstagram/_core/writes/follows.py"
CLI = "dumpstagram/_cli/main.py"
RENDER_PROFILES = "dumpstagram/_cli/render/profiles.py"
GATES = "tests/test_follows.py"

SEND_FOLLOW = '   payload = await send_write(sender, session, WriteRequest(request, "follow"))\n'
SEND_UNFOLLOW = (
   '   payload = await send_write(sender, session, WriteRequest(request, "unfollow"))\n'
)
WRITING_IMPORT = "from dumpstagram._core.writing import send_write\n"
CLASSIFY_IMPORT = WRITING_IMPORT + "from dumpstagram._private.web.classify import classify\n"


def gate(name: str) -> str:
   return f"{GATES}::{name}"


MUTATIONS: list[dict[str, object]] = [
   {
      "gate": gate("test_the_relationship_read_maps_each_state"),
      "defect": "a requested follow is collapsed into not following",
      "edits": [
         (
            PARSE_PROFILES,
            'outgoing_request=_required_flag(raw, "outgoing_request", status_path),',
            "outgoing_request=False,",
         )
      ],
   },
   {
      "gate": gate("test_the_relationship_read_maps_each_state"),
      "defect": "following is read from followed_by",
      "edits": [
         (
            PARSE_PROFILES,
            'following=_required_flag(raw, "following", status_path),',
            'following=_required_flag(raw, "followed_by", status_path),',
         )
      ],
   },
   {
      "gate": gate("test_the_relationship_read_maps_each_state"),
      "defect": "the relationship is never mapped onto the profile",
      "edits": [
         (
            PARSE_PROFILES,
            "      friendship_status=_friendship_status(user, path),\n",
            "",
         )
      ],
   },
   {
      "gate": gate("test_the_viewers_own_profile_carries_no_relationship"),
      "defect": "the viewer's own null is read as a relationship of all false flags",
      "edits": [
         (
            PARSE_PROFILES,
            "   if raw is None:\n      return None\n\n   status_path",
            "   if raw is None:\n"
            "      raw = dict.fromkeys(FriendshipStatus.__dataclass_fields__, False)\n\n"
            "   status_path",
         ),
      ],
   },
   {
      "gate": gate("test_another_accounts_null_flags_read_as_the_model_defaults"),
      "defect": "has_profile_pic is required to be a boolean again",
      "edits": [
         (
            PARSE_PROFILES,
            'has_profile_pic=_flag_or_default(user, "has_profile_pic", path, default=True),',
            'has_profile_pic=_required_flag(user, "has_profile_pic", path),',
         )
      ],
   },
   {
      "gate": gate("test_another_accounts_null_flags_read_as_the_model_defaults"),
      "defect": "a null has_profile_pic is read as false",
      "edits": [
         (
            PARSE_PROFILES,
            'has_profile_pic=_flag_or_default(user, "has_profile_pic", path, default=True),',
            'has_profile_pic=_flag_or_default(user, "has_profile_pic", path, default=False),',
         )
      ],
   },
   {
      "gate": gate("test_a_flag_that_is_neither_boolean_nor_null_still_raises"),
      "defect": "the null allowance accepts any value",
      "edits": [
         (
            PARSE_PROFILES,
            "   if value is None:\n      return default\n\n   if not isinstance(value, bool):\n"
            '      raise SchemaChanged(f"{path}.{key} is not a boolean or null"',
            "   if not isinstance(value, bool):\n      return default\n\n   if False:\n"
            '      raise SchemaChanged(f"{path}.{key} is not a boolean or null"',
         )
      ],
   },
   {
      "gate": gate("test_each_write_sends_the_request_the_engine_replayed"),
      "defect": "unfollow is pointed at the follow document",
      "edits": [
         (
            REQUESTS_SOCIAL,
            '      UNFOLLOW_USER,\n      {"target_user_id": user_id},',
            '      FOLLOW_USER,\n      {"target_user_id": user_id},',
         )
      ],
   },
   {
      "gate": gate("test_each_write_sends_the_request_the_engine_replayed"),
      "defect": "the follow carries a variable no observed send carried",
      "edits": [
         (
            REQUESTS_SOCIAL,
            '      FOLLOW_USER,\n      {"target_user_id": user_id},',
            '      FOLLOW_USER,\n      {"target_user_id": user_id, "container_module": "profile"},',
         )
      ],
   },
   {
      "gate": gate("test_each_write_sends_the_request_the_engine_replayed"),
      "defect": "the follow is sent from the account's profile page instead of the home page",
      "edits": [
         (
            REQUESTS_SOCIAL,
            '      FOLLOW_USER,\n      {"target_user_id": user_id},\n      referer=f"{ORIGIN}/",',
            '      FOLLOW_USER,\n      {"target_user_id": user_id},\n'
            '      referer=f"{ORIGIN}/{user_id}/",',
         )
      ],
   },
   {
      "gate": gate("test_each_write_sends_the_request_the_engine_replayed"),
      "defect": "a request nothing recorded goes out beside the follow",
      "edits": [
         (
            FOLLOWS,
            "   if not session.fb_dtsg:\n"
            "      await bootstrap(sender, session, user_agent=user_agent)\n\n"
            "   request = build_follow_request(",
            "   if True:\n"
            "      await bootstrap(sender, session, user_agent=user_agent)\n\n"
            "   request = build_follow_request(",
         )
      ],
   },
   {
      "gate": gate("test_a_username_is_refused_before_anything_is_sent"),
      "defect": "a username is passed through to the request",
      "edits": [(FOLLOWS, "   if not is_a_user_id(user_id):\n", "   if False:\n")],
   },
   {
      "gate": gate("test_both_writes_depart_only_through_the_write_slot"),
      "defect": "the follow is sent with sender.send rather than send_write",
      "edits": [
         (FOLLOWS, WRITING_IMPORT, CLASSIFY_IMPORT),
         (FOLLOWS, SEND_FOLLOW, "   payload = classify(await sender.send(request))\n"),
      ],
   },
   {
      "gate": gate("test_both_writes_depart_only_through_the_write_slot"),
      "defect": "the unfollow is sent with sender.send rather than send_write",
      "edits": [
         (FOLLOWS, WRITING_IMPORT, CLASSIFY_IMPORT),
         (FOLLOWS, SEND_UNFOLLOW, "   payload = classify(await sender.send(request))\n"),
      ],
   },
   {
      "gate": gate("test_an_error_envelope_on_a_follow_raises_and_departs_once"),
      "defect": "the follow is sent again after an error envelope",
      "edits": [
         (
            FOLLOWS,
            SEND_FOLLOW,
            "   try:\n   " + SEND_FOLLOW + "   except UpstreamRejected:\n   " + SEND_FOLLOW,
         )
      ],
   },
   {
      "gate": gate("test_a_follow_answered_not_following_is_not_a_failure"),
      "defect": "every follow answered not following is raised, a private account's request too",
      "edits": [
         (
            FOLLOWS,
            "   parse_follow_answer(payload, FOLLOW_ANSWER_ROOT, user_id)\n",
            "   if not parse_follow_answer(payload, FOLLOW_ANSWER_ROOT, user_id):\n"
            '      raise UpstreamRejected("not following", code="not_following")\n',
         )
      ],
   },
   {
      "gate": gate("test_an_unfollow_answered_still_following_is_not_taken_as_applied"),
      "defect": "an unfollow answered still following is ignored",
      "edits": [(FOLLOWS, "   if still_following:\n", "   if False:\n")],
   },
   {
      "gate": gate("test_an_answer_about_another_account_is_a_schema_change"),
      "defect": "the echoed account id is not compared",
      "edits": [(PARSE_SOCIAL, "   if echoed_id != user_id:\n", "   if False:\n")],
   },
   {
      "gate": gate("test_the_cli_sends_the_named_account_to_the_named_write"),
      "defect": "the CLI crosses follow and unfollow",
      "edits": [
         (
            COMMANDS_SOCIAL,
            "      if is_follow:\n         client.follow(arguments.user_id)",
            "      if not is_follow:\n         client.follow(arguments.user_id)",
         )
      ],
   },
   {
      "gate": gate("test_the_cli_refuses_a_username_before_opening_a_client"),
      "defect": "the CLI accepts any string as an account id",
      "edits": [
         (
            COMMANDS_SOCIAL,
            '"user_id", metavar="USER_ID", type=account_id, ',
            '"user_id", metavar="USER_ID", ',
         )
      ],
   },
   {
      "gate": gate("test_the_profile_json_carries_the_relationship"),
      "defect": "the profile JSON leaves the relationship out",
      "edits": [
         (
            RENDER_PROFILES,
            '      "friendship_status": describe_friendship_status(profile.friendship_status),\n',
            "",
         )
      ],
   },
   {
      "gate": gate("test_the_profile_json_carries_the_relationship"),
      "defect": "the profile JSON reports a request as not requested",
      "edits": [
         (
            RENDER_PROFILES,
            '      "outgoing_request": status.outgoing_request,\n',
            '      "outgoing_request": status.following,\n',
         )
      ],
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

   for cached in ENGINE.glob("**/__pycache__"):
      shutil.rmtree(cached, ignore_errors=True)

   return subprocess.run(
      [sys.executable, "-B", "-m", "pytest", gate, "-q", "--no-header", "-p", "no:cacheprovider"],
      cwd=ENGINE,
      capture_output=True,
      text=True,
      env=environment,
   )


def apply_edits(edits: list[tuple[str, str, str]], gate: str) -> dict[Path, str]:
   originals: dict[Path, str] = {}

   try:
      for relative, find, replace in edits:
         path = ENGINE / relative
         originals.setdefault(path, path.read_text(encoding="utf-8"))
         current = path.read_text(encoding="utf-8")

         occurrences = current.count(find)

         if occurrences != 1:
            raise SystemExit(
               f"mutation anchor found {occurrences} times in {relative} for {gate}, "
               "expected exactly once"
            )

         path.write_text(current.replace(find, replace, 1), encoding="utf-8")
   except BaseException:
      restore(originals)

      raise

   return originals


def restore(originals: dict[Path, str]) -> None:
   for path, original in originals.items():
      path.write_text(original, encoding="utf-8")


def main() -> int:
   results = []

   for mutation in MUTATIONS:
      gate = str(mutation["gate"])
      edits = mutation["edits"]
      assert isinstance(edits, list)

      originals = apply_edits(edits, gate)

      try:
         mutated = run_gate(gate)
      finally:
         restore(originals)

      restored = run_gate(gate)

      results.append(
         {
            "gate": gate,
            "defect": mutation["defect"],
            "mutated_files": sorted({relative for relative, _, _ in edits}),
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
   log_path = LOG_DIR / f"mutation-follows-{stamp}.json"
   log_path.write_text(
      json.dumps({"every_gate_fired": every_gate_fired, "gates": results}, indent=2) + "\n",
      encoding="utf-8",
   )

   for entry in results:
      fired = entry["red_under_mutation"] and entry["green_after_restore"]
      status = "red then green" if fired else "DID NOT FIRE"
      print(f"{status}: {entry['gate'].split('::')[1]}  ({entry['defect']})")

   print(f"log written to {log_path}")

   return 0 if every_gate_fired else 1


if __name__ == "__main__":
   raise SystemExit(main())
