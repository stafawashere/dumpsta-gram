"""Turn the E2 batch 8 captures into the pseudonymised fixtures the search gates replay.

The inputs are local and outside git: the bodies ``probes/e2_search.py`` kept under the skill's
``var/captures/`` on 2026-09-27. The outputs are the three files under
``tests/fixtures/search/``, which are committed, so nothing of a third party, and none of the
viewer's own search terms, may survive into them. The rules are by key, and a value no rule keeps
is replaced:

- enum-like values (``__typename`` and ``search_social_context_snippet_type``) are kept
  verbatim, and so are booleans and nulls
- every identifier is replaced by a synthetic one of the same length, consistently across all
  three files, so an account's ``pk`` and ``id`` stay equal
- every integer becomes zero, since none the mappers read is a count
- every other string becomes a placeholder of the same length, and a URL a URL on a reserved
  domain, which covers usernames, full names, the searched keywords and the social context line
- the ``extensions`` block is dropped

Nothing is trimmed: the recent searches carry 15 entries and the typeahead 18 accounts, and the
gates count both.

The script then checks its own output: no replaced value of four characters or more may appear
in any file written, and it reports how many it checked, which is the control that the check
ran against something.

Run from ``engine/`` with ``uv run python scripts/build_search_fixtures.py``. Writes a report to
``engine/logs/``.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ENGINE = Path(__file__).resolve().parents[1]
LOG_DIR = ENGINE / "logs"
FIXTURE_DIR = ENGINE / "tests" / "fixtures" / "search"
CAPTURES = ENGINE.parent / "skills" / "reverse-engineer" / "var" / "captures"
SEARCH = "e2-search-2026-09-27-013849"

VERBATIM_KEYS = frozenset({"__typename", "search_social_context_snippet_type"})

MINIMUM_CHECKED_LENGTH = 4

OUTPUTS = {
   "recent_searches.json": f"{SEARCH}-02-recent-searches-1.json",
   "non_personalised_typeahead.json": f"{SEARCH}-04-non-personalised-typeahead-1.json",
   "hashtag_header.json": f"{SEARCH}-06-hashtag-header-1.json",
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
      elif kind == "url":
         synthetic = f"https://example.invalid/{number}"
      else:
         synthetic = ("p" + str(number)).ljust(length, "x")[:length] if length else ""

      self.replacements[original] = synthetic

      return synthetic

   def string(self, key: str, value: str) -> str:
      if key in VERBATIM_KEYS:
         return value

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
         return 0

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
   log_path = LOG_DIR / f"search-fixtures-{stamp}.json"
   log_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
   print(json.dumps(report, indent=2))
   print(f"log written to {log_path}")

   has_a_survivor = bool(survivors)
   checked_nothing = not checked

   return 1 if has_a_survivor or checked_nothing else 0


if __name__ == "__main__":
   sys.exit(main())
