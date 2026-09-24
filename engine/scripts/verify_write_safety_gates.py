"""Break the write path, watch each Step 13 gate go red, restore.

Same harness and same rule as ``verify_cookie_sync_gates.py``: one mutation per line below, only
the gate that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind. The rows follow the Step 13
gates table in ``engine/docs/build-plan.md``, each under exactly the mutation it names, followed
by the gates this step added beside the table.

The two retry mutations rebuild the write request's token on each attempt, because a retry that
resent the same object would be stopped by the departed-token check and would prove that check
rather than the gate it is aimed at.

Run from ``engine/`` with ``uv run python scripts/verify_write_safety_gates.py``. Writes its
result to ``engine/logs/``.
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


ERRORS = "dumpstagram/errors.py"
EXITS = "dumpstagram/_cli/exits.py"
WRITING = "dumpstagram/_core/writing.py"
WRITES_PACKAGE = "dumpstagram/_core/writes/__init__.py"
PACER = "dumpstagram/_core/pacer.py"
BEHAVIOR = "dumpstagram/behavior.py"
CLIENT = "dumpstagram/aio.py"

ERROR_GATES = "tests/test_errors.py"
CLI_GATES = "tests/test_cli.py"
GATES = "tests/test_write_safety.py"


SEND_AND_CLASSIFY = (
   "      response = await sender.send_once(write)\n      payload = classify(response)\n"
)

RECORD_WHEN_DEPARTED = (
   "      if sender.pacer.write_departed(write.token):\n"
   "         _record_answer(sender, session, failure, recognised_rejections)\n"
)

PACER_IMPORT = "from dumpstagram._core.pacer import backoff_delay\n"

REBUILD_IMPORTS = "from dataclasses import replace\nfrom uuid import uuid4\n\n"

RESEND = "classify(await sender.send_once(replace(write, token=uuid4().hex)))"

SHELL_RESET = "      session.fb_dtsg = None\n      return\n"


def gate(name: str, module: str = GATES) -> str:
   return f"{module}::{name}"


MUTATIONS: list[dict[str, object]] = [
   {
      "gate": gate("test_an_unknown_outcome_is_absent_from_the_retryable_set", ERROR_GATES),
      "defect": "OutcomeUnknown is added to RETRYABLE",
      "edits": [
         (
            ERRORS,
            "(TransportFailure, RateLimited)",
            "(TransportFailure, RateLimited, OutcomeUnknown)",
         )
      ],
   },
   {
      "gate": gate("test_an_unknown_outcome_inherits_from_no_retryable_type", ERROR_GATES),
      "defect": "OutcomeUnknown subclasses TransportFailure",
      "edits": [
         (
            ERRORS,
            "class OutcomeUnknown(DumpstagramError):",
            "class OutcomeUnknown(TransportFailure):",
         )
      ],
   },
   {
      "gate": gate("test_a_transport_failure_during_a_write_is_an_unknown_outcome"),
      "defect": "the TransportFailure propagates",
      "edits": [
         (
            WRITING,
            "   except TransportFailure as failure:\n",
            "   except ZeroDivisionError as failure:\n",
         )
      ],
   },
   {
      "gate": gate("test_the_unknown_outcome_chains_the_transport_failure"),
      "defect": "the from is dropped",
      "edits": [(WRITING, "      ) from failure\n", "      )\n")],
   },
   {
      "gate": gate("test_a_timed_out_write_departs_once"),
      "defect": "send_write is routed through run_with_retries",
      "edits": [
         (
            WRITING,
            PACER_IMPORT,
            REBUILD_IMPORTS
            + "from dumpstagram._core.pacer import backoff_delay, run_with_retries\n",
         ),
         (
            WRITING,
            "      response = await sender.send_once(write)\n",
            "      response = await run_with_retries(\n"
            "         lambda: sender.send_once(replace(write, token=uuid4().hex)),\n"
            "         pacer=sender.pacer,\n"
            "      )\n",
         ),
      ],
   },
   {
      "gate": gate("test_a_shell_answer_to_a_write_departs_once"),
      "defect": "send_write is routed through with_token_recovery",
      "edits": [
         (WRITING, PACER_IMPORT, REBUILD_IMPORTS + PACER_IMPORT),
         (
            WRITING,
            "from dumpstagram._core.tokens import HTML_APP_SHELL\n",
            "from dumpstagram._core.tokens import HTML_APP_SHELL, with_token_recovery\n",
         ),
         (
            WRITING,
            SEND_AND_CLASSIFY,
            "      async def resend() -> Any:\n"
            f"         return {RESEND}\n\n"
            "      payload = await with_token_recovery(resend, sender=sender, session=session)\n",
         ),
      ],
   },
   {
      "gate": gate("test_a_shell_answer_clears_the_token"),
      "defect": "the fb_dtsg reset is dropped",
      "edits": [(WRITING, SHELL_RESET, "      return\n")],
   },
   {
      "gate": gate("test_a_write_request_cannot_depart_twice"),
      "defect": "the departed-token check is removed",
      "edits": [(PACER, "         self._refuse_a_second_departure(token)\n", "")],
   },
   {
      "gate": gate("test_write_modules_do_not_import_the_retry_helpers"),
      "defect": "a write module imports run_with_retries",
      "edits": [
         (
            WRITES_PACKAGE,
            'would have changed.\n"""\n',
            'would have changed.\n"""\n\nfrom dumpstagram._core.pacer import run_with_retries\n',
         )
      ],
   },
   {
      "gate": gate("test_a_throttled_write_holds_the_account_and_does_not_resend"),
      "defect": "hold is replaced with hold_for and a resend",
      "edits": [
         (WRITING, PACER_IMPORT, REBUILD_IMPORTS + PACER_IMPORT),
         (
            WRITING,
            RECORD_WHEN_DEPARTED,
            "      if isinstance(failure, RateLimited):\n"
            "         await sender.pacer.hold_for(failure.retry_after or 0.0)\n\n"
            f"         return {RESEND}\n\n" + RECORD_WHEN_DEPARTED,
         ),
      ],
   },
   {
      "gate": gate("test_writes_are_spaced_by_the_write_floor_and_reads_are_not"),
      "defect": "the write floor is set to zero",
      "edits": [
         (
            BEHAVIOR,
            "write_spacing: Spacing = Spacing(floor_seconds=30.0, mean_jitter_seconds=5.0)",
            "write_spacing: Spacing = Spacing(floor_seconds=0.0, mean_jitter_seconds=5.0)",
         )
      ],
   },
   {
      "gate": gate("test_zero_write_spacing_leaves_the_budget_and_the_stop"),
      "defect": "zero spacing disables the whole write policy",
      "edits": [
         (
            CLIENT,
            "def write_policy_for(behavior: Behavior) -> WritePolicy:\n",
            "def write_policy_for(behavior: Behavior) -> WritePolicy:\n"
            "   if behavior.write_spacing.floor_seconds == 0:\n"
            "      return WritePolicy(\n"
            "         spacing=PacingPolicy(floor_seconds=0.0, mean_jitter_seconds=0.0),\n"
            "         budget_per_hour=None,\n"
            "         stop_after_unrecognised_rejection=False,\n"
            "      )\n\n",
         )
      ],
   },
   {
      "gate": gate("test_the_write_budget_refuses_without_sending"),
      "defect": "the budget check is dropped",
      "edits": [(PACER, "      self._refuse_past_the_budget(writes, record, now)\n", "")],
   },
   {
      "gate": gate("test_an_unrecognised_write_rejection_stops_later_writes_and_not_reads"),
      "defect": "the stop flag is dropped",
      "edits": [(PACER, "      self._writes_stopped = True\n", "      return\n")],
   },
   {
      "gate": gate("test_every_public_error_has_its_own_exit_code", CLI_GATES),
      "defect": "OutcomeUnknown is mapped to the generic code",
      "edits": [(EXITS, "   OutcomeUnknown: 11,\n", "   OutcomeUnknown: 1,\n")],
   },
   {
      "gate": gate("test_a_shell_answer_does_not_stop_later_writes"),
      "defect": "the shell is counted as an unrecognised rejection",
      "edits": [(WRITING, SHELL_RESET, "      session.fb_dtsg = None\n")],
   },
   {
      "gate": gate("test_a_refused_write_leaves_the_account_unheld"),
      "defect": "the pacer's own refusal is recorded as the upstream's answer",
      "edits": [
         (
            WRITING,
            "      if sender.pacer.write_departed(write.token):\n",
            "      if True:\n",
         )
      ],
   },
   {
      "gate": gate("test_the_write_stop_can_be_turned_off"),
      "defect": "the stop ignores the policy",
      "edits": [
         (
            PACER,
            "is_stopped = account_is_stopped and writes.stop_after_unrecognised_rejection",
            "is_stopped = account_is_stopped",
         )
      ],
   },
   {
      "gate": gate("test_the_fast_preset_keeps_the_budget_and_the_stop"),
      "defect": "the fast preset also drops the write budget",
      "edits": [
         (
            BEHAVIOR,
            "   write_spacing=Spacing(floor_seconds=0.0, mean_jitter_seconds=0.0),\n)",
            "   write_spacing=Spacing(floor_seconds=0.0, mean_jitter_seconds=0.0),\n"
            "   write_budget_per_hour=None,\n)",
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
   log_path = LOG_DIR / f"mutation-write-safety-{stamp}.json"
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
