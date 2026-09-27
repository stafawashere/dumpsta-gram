"""Turn the E2 batch 3 captures into the pseudonymised fixtures the follow list gates replay.

The inputs are local and outside git: the bodies ``probes/e2_follow_lists.py`` kept under the
skill's ``var/captures/`` on its second run of 2026-09-27. The outputs are the three files under
``tests/fixtures/follow_lists/``, which are committed, so nothing of a third party may survive
into them. The rules are by key, and a value no rule keeps is replaced:

- ``status`` and ``status_code`` are kept verbatim, since the mappers read the first and neither
  is content, and so are booleans and nulls
- every identifier is replaced by a synthetic one of the same length, consistently across all
  three files and in the keys of ``friendship_statuses`` too, so a status still names the row it
  belongs to and a row's ``pk`` still equals its ``id``
- ``next_max_id`` and ``follow_ranking_token`` become synthetic tokens of the same length
- ``page_size`` is kept, since it is the upstream's count of the page and not content, and every
  other integer becomes zero
- every other string becomes a placeholder of the same length, and a URL a URL on a reserved
  domain

The script then checks its own output: no replaced value of four characters or more may appear
in any file written, and it reports how many it checked, which is the control that the check
ran against something.

Run from ``engine/`` with ``uv run python scripts/build_follow_lists_fixtures.py``. Writes a
report to ``engine/logs/``.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ENGINE = Path(__file__).resolve().parents[1]
LOG_DIR = ENGINE / "logs"
FIXTURE_DIR = ENGINE / "tests" / "fixtures" / "follow_lists"
CAPTURES = ENGINE.parent / "skills" / "reverse-engineer" / "var" / "captures"
FOLLOW_LISTS = "e2-follow-lists-2026-09-27-014434"

VERBATIM_KEYS = frozenset({"status", "status_code"})

KEPT_INTEGER_KEYS = frozenset({"page_size"})

CURSOR_KEYS = frozenset({"next_max_id", "follow_ranking_token"})

KEYED_BY_ACCOUNT = "friendship_statuses"

MINIMUM_CHECKED_LENGTH = 4

COMPOUND_ID = re.compile(r"([0-9]+)_([0-9]+)")

OUTPUTS = {
   "followers_first_page.json": f"{FOLLOW_LISTS}-03-followers-page-1.json",
   "followers_next_page.json": f"{FOLLOW_LISTS}-05-followers-page-two,-max_id-inference.json",
   "friendship_statuses.json": f"{FOLLOW_LISTS}-06-show_many-1.json",
}


class Pseudonymiser:
   def __init__(self) -> None:
      self.replacements: dict[str, str] = {}
      self.counter = 0

   def _synthetic(self, original: str, kind: str) -> str:
      if original in self.replacements:
         return self.replacements[original]

      self.counter += 1
      number = self.counter
      length = len(original)

      if kind == "digits":
         body = str(number).rjust(length - 1, "0")
         synthetic = ("9" + body)[:length] if length > 1 else str(number % 10)
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

      if key in CURSOR_KEYS:
         return self._synthetic(value, "cursor") if value else value

      if value.startswith("http"):
         return self._synthetic(value, "url")

      if value.isdigit():
         return self._synthetic(value, "digits")

      compound = COMPOUND_ID.fullmatch(value)

      if compound is not None:
         first, second = compound.groups()

         return f"{self._synthetic(first, 'digits')}_{self._synthetic(second, 'digits')}"

      return self._synthetic(value, "text")

   def walk(self, value: Any, key: str = "") -> Any:
      if isinstance(value, dict):
         is_keyed_by_account = key == KEYED_BY_ACCOUNT

         return {
            (self._synthetic(inner_key, "digits") if is_keyed_by_account else inner_key): self.walk(
               inner, inner_key
            )
            for inner_key, inner in value.items()
         }

      if isinstance(value, list):
         return [self.walk(inner, key) for inner in value]

      if isinstance(value, bool) or value is None:
         return value

      if isinstance(value, int):
         return value if key in KEPT_INTEGER_KEYS else 0

      if isinstance(value, float):
         return 0.0

      if isinstance(value, str):
         return self.string(key, value)

      return value


def main() -> int:
   inputs = {name: json.loads((CAPTURES / source).read_text()) for name, source in OUTPUTS.items()}
   pseudonymiser = Pseudonymiser()
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
   log_path = LOG_DIR / f"follow-lists-fixtures-{stamp}.json"
   log_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
   print(json.dumps(report, indent=2))
   print(f"log written to {log_path}")

   has_a_survivor = bool(survivors)
   checked_nothing = not checked

   return 1 if has_a_survivor or checked_nothing else 0


if __name__ == "__main__":
   sys.exit(main())
