"""Turn the E2 batch 1 captures into the pseudonymised fixtures the direct read gates replay.

The inputs are local and outside git: the bodies ``probes/e2_direct_read.py`` kept under the
skill's ``var/captures/`` on 2026-09-24, and the inbox folder's unread rows from the inbox cold
load captured on 2026-09-23. The outputs are the five files under
``tests/fixtures/direct_read/``, which are committed, so nothing of a third party may survive
into them. The rules are by key, and a value no rule keeps is replaced:

- enum-like values the mapper reads (``__typename``, the folder names, ``thread_subtype``,
  ``content_type``) are kept verbatim, and so are booleans and nulls
- every identifier is replaced by a synthetic one of the same length, consistently across all
  five files, so the mailbox id still equals the viewer's messaging id and a receipt still
  names the viewer
- every timestamp is shifted by one constant, so order and spacing survive and the date does not
- every cursor becomes a synthetic token of the same length
- every integer but two enum-like ones becomes zero
- every other string becomes a placeholder of the same length, and a URL a URL on a reserved
  domain
- the ``extensions`` block is dropped

The script then checks its own output: no replaced value of four characters or more may appear
in any file written, and it reports how many it checked, which is the control that the check
ran against something.

Run from ``engine/`` with ``uv run python scripts/build_direct_read_fixtures.py``. Writes a
report to ``engine/logs/``.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

ENGINE = Path(__file__).resolve().parents[1]
LOG_DIR = ENGINE / "logs"
FIXTURE_DIR = ENGINE / "tests" / "fixtures" / "direct_read"
CAPTURES = ENGINE.parent / "skills" / "reverse-engineer" / "var" / "captures"
PROBE_STAMP = "2026-09-24-010425"
INBOX_LOAD = CAPTURES / "run-2026-09-23-045256-inbox-cold-load.jsonl"

SHIFTED_EPOCH_MS = 1_577_836_800_000
"""2020-01-01T00:00:00Z. The oldest timestamp in the inputs lands here."""

VERBATIM_KEYS = frozenset(
   {
      "__typename",
      "folder",
      "system_folder",
      "messaging_folder_tag",
      "thread_subtype",
      "content_type",
   }
)

KEPT_INTEGER_KEYS = frozenset({"input_mode", "thread_label"})

CURSOR_KEYS = frozenset({"cursor", "end_cursor"})

MINIMUM_CHECKED_LENGTH = 4

OUTPUTS = {
   "inbox_first_page.json": f"e2-direct-read-{PROBE_STAMP}-inbox-listing.json",
   "inbox_next_page.json": f"e2-direct-read-{PROBE_STAMP}-next-page-1.json",
   "message_requests.json": f"e2-direct-read-{PROBE_STAMP}-message-requests-1.json",
   "pending_unread_rows.json": f"e2-direct-read-{PROBE_STAMP}-pending-unread-rows.json",
}
INBOX_UNREAD_ROWS = "inbox_unread_rows.json"


def _is_a_timestamp_key(key: str) -> bool:
   return key.endswith("timestamp_ms")


class Pseudonymiser:
   def __init__(self, offset_ms: int) -> None:
      self.offset_ms = offset_ms
      self.replacements: dict[str, str] = {}
      self.counter = 0

   def _next(self) -> int:
      self.counter += 1

      return self.counter

   def _synthetic(self, original: str, kind: str) -> str:
      if original in self.replacements:
         return self.replacements[original]

      number = self._next()
      length = len(original)

      if kind == "digits":
         body = str(number).rjust(length - 1, "0")
         synthetic = ("9" + body)[:length] if length > 1 else str(number % 10)
      elif kind == "message":
         synthetic = ("mid.$m" + str(number).rjust(8, "0")).ljust(length, "q")[:length]
      elif kind == "cursor":
         synthetic = ("C" + str(number).rjust(6, "0")).ljust(length, "c")[:length]
      elif kind == "url":
         synthetic = f"https://example.invalid/{number}"
      else:
         synthetic = ("p" + str(number)).ljust(length, "x")[:length] if length else ""

      self.replacements[original] = synthetic

      return synthetic

   def string(self, key: str, value: str) -> str:
      if key in VERBATIM_KEYS:
         return value

      if _is_a_timestamp_key(key) and value.isdigit():
         return str(int(value) - self.offset_ms)

      if key in CURSOR_KEYS:
         return self._synthetic(value, "cursor")

      if value.startswith("mid."):
         return self._synthetic(value, "message")

      if value.startswith("http"):
         return self._synthetic(value, "url")

      if value.isdigit():
         return self._synthetic(value, "digits")

      return self._synthetic(value, "text")

   def walk(self, value: Any, key: str = "") -> Any:
      if isinstance(value, dict):
         return {
            inner_key: self.walk(inner, inner_key)
            for inner_key, inner in value.items()
            if inner_key != "extensions"
         }

      if isinstance(value, list):
         return [self.walk(inner, key) for inner in value]

      if isinstance(value, bool) or value is None:
         return value

      if isinstance(value, int):
         return value if key in KEPT_INTEGER_KEYS else 0

      if isinstance(value, str):
         return self.string(key, value)

      return value


def _timestamps(value: Any, key: str = "") -> list[int]:
   found: list[int] = []

   if isinstance(value, dict):
      for inner_key, inner in value.items():
         found.extend(_timestamps(inner, inner_key))
   elif isinstance(value, list):
      for inner in value:
         found.extend(_timestamps(inner, key))
   elif isinstance(value, str) and _is_a_timestamp_key(key) and value.isdigit():
      found.append(int(value))

   return found


def _inbox_unread_rows() -> Any:
   for line in INBOX_LOAD.read_text(encoding="utf-8").splitlines():
      record = json.loads(line)
      is_the_count_query = record.get("friendly_name") == "useIGDSystemFolderUnreadThreadCountQuery"

      if not is_the_count_query:
         continue

      variables = json.loads(parse_qs(record["request_body"])["variables"][0])
      is_the_inbox_folder = variables.get("folder") == "INBOX"

      if is_the_inbox_folder:
         return json.loads(record["response_body"].split("\n")[0])

   raise SystemExit("the inbox load carries no inbox folder unread rows")


def main() -> int:
   inputs = {name: json.loads((CAPTURES / source).read_text()) for name, source in OUTPUTS.items()}
   inputs[INBOX_UNREAD_ROWS] = _inbox_unread_rows()
   every_timestamp = [stamp for payload in inputs.values() for stamp in _timestamps(payload)]
   offset_ms = min(every_timestamp) - SHIFTED_EPOCH_MS
   pseudonymiser = Pseudonymiser(offset_ms)
   written = {name: pseudonymiser.walk(payload) for name, payload in inputs.items()}

   FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
   texts: dict[str, str] = {}

   for name, payload in written.items():
      text = json.dumps(payload, indent=1, sort_keys=False) + "\n"
      (FIXTURE_DIR / name).write_text(text, encoding="utf-8")
      texts[name] = text

   checked = [
      original
      for original, synthetic in pseudonymiser.replacements.items()
      if len(original) >= MINIMUM_CHECKED_LENGTH and original != synthetic
   ]
   survivors = [name for name, text in texts.items() for original in checked if original in text]
   report = {
      "fixtures": sorted(texts),
      "bytes": {name: len(text) for name, text in texts.items()},
      "values_replaced": len(pseudonymiser.replacements),
      "values_checked_absent": len(checked),
      "files_with_a_survivor": sorted(set(survivors)),
   }

   LOG_DIR.mkdir(parents=True, exist_ok=True)
   stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
   log_path = LOG_DIR / f"direct-read-fixtures-{stamp}.json"
   log_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
   print(json.dumps(report, indent=2))
   print(f"log written to {log_path}")

   has_a_survivor = bool(survivors)
   checked_nothing = not checked

   return 1 if has_a_survivor or checked_nothing else 0


if __name__ == "__main__":
   sys.exit(main())
