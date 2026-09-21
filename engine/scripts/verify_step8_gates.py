"""Break the source, watch each Step 8 gate go red, restore.

A gate that has never been seen to fail is a gate nobody has tested. This applies one
mutation per gate, runs only the gate that should catch it, and asserts the run failed. Every
file it touches is restored from an in-memory copy in a ``finally``, so an interrupted run
cannot leave a mutation behind.

Run from ``engine/`` with ``uv run python scripts/verify_step8_gates.py``. Writes its result
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

REQUESTING = "dumpstagram/_core/requesting.py"
SMOKE = "dumpstagram/_core/smoke.py"
# The stale-token judgement moved here when the first capability arrived and two
# call sites started needing it.
TOKENS = "dumpstagram/_core/tokens.py"
TRANSPORT = "dumpstagram/_private/transport.py"
ERRORS = "dumpstagram/errors.py"

PACED_SEND_BODY = """      async with self.pacer.slot():
         return await self._sender.send(request)"""

BYPASS_THE_PACER = "      return await self._sender.send(request)"

ACLOSE_GUARD = """      closer = getattr(self._sender, "aclose", None)

      if closer is not None:
         await closer()"""

ACLOSE_UNGUARDED = "      await self._sender.aclose()  # type: ignore[attr-defined]"

CONDITIONAL_BOOTSTRAP = """      if not session.fb_dtsg:
         await bootstrap(sender, session, user_agent=user_agent)"""

UNCONDITIONAL_BOOTSTRAP = "      await bootstrap(sender, session, user_agent=user_agent)"

STALE_TOKEN_CHECK = """   if isinstance(failure, AuthenticationFailed):
      return True"""

STALE_TOKEN_NEVER = """   if isinstance(failure, AuthenticationFailed):
      return False

   return False"""

RETRYABLE_WITHOUT_CHECKPOINT = (
   "RETRYABLE: tuple[type[DumpstagramError], ...] = (TransportFailure, RateLimited)"
)

RETRYABLE_WITH_CHECKPOINT = """RETRYABLE: tuple[type[DumpstagramError], ...] = (
   TransportFailure,
   RateLimited,
   CheckpointRequired,
)"""

REQUIRED_COOKIES_LAST = """   jar = dict(session.extra_cookies)

   jar["sessionid"] = session.sessionid
   jar["ds_user_id"] = session.ds_user_id
   jar["csrftoken"] = session.csrftoken"""

REQUIRED_COOKIES_FIRST = """   jar = {
      "sessionid": session.sessionid,
      "ds_user_id": session.ds_user_id,
      "csrftoken": session.csrftoken,
   }

   jar.update(session.extra_cookies)"""

MUTATIONS = [
   {
      "gate": "tests/test_requesting.py::test_the_paced_sender_is_a_sender",
      "defect": "the wrapper stops satisfying Sender, so callers must unwrap it to send",
      "file": REQUESTING,
      "find": "   async def send(self, request: Request) -> Response:",
      "replace": "   async def dispatch(self, request: Request) -> Response:",
   },
   {
      "gate": "tests/test_requesting.py::test_every_outbound_request_is_spaced_at_the_transport",
      "defect": "a bypass around the pacer",
      "file": REQUESTING,
      "find": PACED_SEND_BODY,
      "replace": BYPASS_THE_PACER,
   },
   {
      "gate": "tests/test_requesting.py::test_concurrent_callers_cannot_depart_together",
      "defect": "two tasks departing at the same instant",
      "file": REQUESTING,
      "find": PACED_SEND_BODY,
      "replace": BYPASS_THE_PACER,
   },
   {
      "gate": "tests/test_requesting.py::test_closing_the_paced_sender_closes_the_transport",
      "defect": "the wrapped connection pool is leaked",
      "file": REQUESTING,
      "find": "      if closer is not None:\n         await closer()",
      "replace": "      if closer is None:\n         await closer()",
   },
   {
      "gate": "tests/test_requesting.py::test_a_sender_without_aclose_is_not_an_error",
      "defect": "the wrapper demands more of Sender than the protocol states",
      "file": REQUESTING,
      "find": ACLOSE_GUARD,
      "replace": ACLOSE_UNGUARDED,
   },
   {
      "gate": "tests/test_smoke.py::test_an_unbootstrapped_session_costs_two_requests",
      "defect": "the read skips the bootstrap and sends an empty token",
      "file": SMOKE,
      "find": CONDITIONAL_BOOTSTRAP,
      "replace": "      pass",
   },
   {
      "gate": "tests/test_smoke.py::test_a_bootstrapped_session_costs_one_request",
      "defect": "a bootstrap on every call, doubling the live cost of every operation",
      "file": SMOKE,
      "find": CONDITIONAL_BOOTSTRAP,
      "replace": UNCONDITIONAL_BOOTSTRAP,
   },
   {
      "gate": "tests/test_smoke.py::test_both_requests_pass_the_pacer",
      "defect": "the composition reaches an unpaced transport",
      "file": REQUESTING,
      "find": PACED_SEND_BODY,
      "replace": BYPASS_THE_PACER,
   },
   {
      "gate": "tests/test_smoke.py::test_a_stale_token_is_re_bootstrapped_once",
      "defect": "the read gives up on the one failure a fresh token fixes",
      "file": TOKENS,
      "find": STALE_TOKEN_CHECK,
      "replace": STALE_TOKEN_NEVER,
   },
   {
      "gate": "tests/test_smoke.py::test_a_freshly_fetched_token_is_not_re_bootstrapped",
      "defect": "a re-bootstrap loop, one live request per attempt",
      "file": TOKENS,
      "find": "      if not used_a_token_it_had_not_just_fetched:\n         raise",
      "replace": "      pass",
   },
   {
      "gate": "tests/test_smoke.py::test_a_challenge_stops_the_read_immediately",
      "defect": "a challenge reaching the retry path",
      "file": ERRORS,
      "find": RETRYABLE_WITHOUT_CHECKPOINT,
      "replace": RETRYABLE_WITH_CHECKPOINT,
   },
   {
      "gate": "tests/test_transport.py::test_the_required_cookies_cannot_be_shadowed_by_extras",
      "defect": "a stale cookie in extra_cookies answers for the session's own credential",
      "file": TRANSPORT,
      "find": REQUIRED_COOKIES_LAST,
      "replace": REQUIRED_COOKIES_FIRST,
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

   if mutation["find"] not in original:
      raise SystemExit(f"mutation anchor not found in {mutation['file']} for {mutation['gate']}")

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

   every_gate_fired = all(
      entry["red_under_mutation"] and entry["green_after_restore"] for entry in results
   )

   LOG_DIR.mkdir(parents=True, exist_ok=True)
   stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
   log_path = LOG_DIR / f"mutation-step8-{stamp}.json"
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
