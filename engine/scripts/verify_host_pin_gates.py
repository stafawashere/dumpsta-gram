"""Break the host pin and the cookieless transport, watch each gate go red, restore.

Same harness and same rule as ``verify_parity_gates.py``: one mutation per gate, only the gate
that should catch it is run, and every file is restored from an in-memory copy in a
``finally`` so an interrupted run cannot leave a mutation behind.

Run from ``engine/`` with ``uv run python scripts/verify_host_pin_gates.py``. Writes its
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


TRANSPORT = "dumpstagram/_private/transport.py"
CLIENT = "dumpstagram/aio.py"
TRANSPORT_GATES = "tests/test_transport.py"
CLIENT_GATES = "tests/test_client.py"

MUTATIONS: list[dict[str, object]] = [
   {
      "gate": f"{TRANSPORT_GATES}::test_a_pinned_transport_refuses_another_host",
      "defect": "the pin lets every host through",
      "edits": [(TRANSPORT, "is_other_host = host != self._allowed_host", "is_other_host = False")],
   },
   {
      "gate": f"{TRANSPORT_GATES}::test_a_pinned_transport_refuses_a_redirect_to_another_host",
      "defect": "the pin checks the first hop only and a redirect walks past it",
      "edits": [
         (TRANSPORT, "      if self._allowed_host is None:\n         return\n", "      return\n"),
         (
            TRANSPORT,
            "      names_a_cookie = any(",
            "      first_hop = httpx.URL(request.url).host\n"
            "      if self._allowed_host is not None and first_hop != self._allowed_host:\n"
            '         raise TransportFailure("refused")\n\n'
            "      names_a_cookie = any(",
         ),
      ],
   },
   {
      "gate": f"{TRANSPORT_GATES}::test_a_cookieless_transport_neither_stores_nor_sends_a_cookie",
      "defect": "the cookieless jar stores what a response sets",
      "edits": [
         (
            TRANSPORT,
            "return CookieJar(policy=DefaultCookiePolicy(allowed_domains=[]))",
            "return CookieJar()",
         )
      ],
   },
   {
      "gate": f"{TRANSPORT_GATES}::test_an_owned_cookieless_transport_stores_no_cookie",
      "defect": "the transport's own client gets an ordinary jar",
      "edits": [
         (
            TRANSPORT,
            "_refusing_jar() if cookieless else dict(cookies or {})",
            "dict(cookies or {})",
         )
      ],
   },
   {
      "gate": f"{TRANSPORT_GATES}::test_a_cookieless_transport_refuses_a_cookie_header",
      "defect": "a cookie header written by a request builder goes out",
      "edits": [
         (
            TRANSPORT,
            "is_cookie_on_cookieless = self._cookieless and names_a_cookie",
            "is_cookie_on_cookieless = False",
         )
      ],
   },
   {
      "gate": f"{TRANSPORT_GATES}::test_a_cookieless_transport_does_not_follow_a_redirect",
      "defect": "the cookieless transport follows redirects",
      "edits": [
         (
            TRANSPORT,
            "follow_redirects=request.follow_redirects and not self._cookieless,",
            "follow_redirects=request.follow_redirects,",
         )
      ],
   },
   {
      "gate": f"{TRANSPORT_GATES}::test_a_cookieless_transport_refuses_cookies",
      "defect": "a cookieless transport accepts a cookie jar",
      "edits": [(TRANSPORT, "if cookieless and cookies:", "if False:")],
   },
   {
      "gate": f"{CLIENT_GATES}::test_the_cookie_carrying_transport_refuses_facebook",
      "defect": "the client builds its instagram transport unpinned",
      "edits": [(CLIENT, "         allowed_host=INSTAGRAM_HOST,\n", "")],
   },
   {
      "gate": f"{CLIENT_GATES}::test_the_cookie_carrying_transport_refuses_facebook",
      "defect": "a transport that owns its client never installs the pin",
      "edits": [(TRANSPORT, "      )\n      self._pin(self._client)\n", "      )\n")],
   },
   {
      "gate": f"{CLIENT_GATES}::test_the_facebook_transport_is_cookieless_and_pinned",
      "defect": "the facebook transport is handed the account's cookie jar",
      "edits": [
         (CLIENT, "         cookieless=True,\n", "         cookies=cookies_for(session),\n")
      ],
   },
   {
      "gate": f"{CLIENT_GATES}::test_closing_the_client_closes_the_facebook_pool",
      "defect": "the facebook pool is never closed",
      "edits": [(CLIENT, "            await self._facebook.aclose()\n", "            pass\n")],
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
   log_path = LOG_DIR / f"mutation-host-pin-{stamp}.json"
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
