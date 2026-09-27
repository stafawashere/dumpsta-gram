"""Turn the E2 batch 11a captures into the pseudonymised fixtures its gates replay.

The inputs are local and outside git, under the skill's ``var/captures/``: the answers
``probes/e2_capture_replays.py --stage profile`` kept on 2026-09-27, and the browser's first
following page with the ``show_many`` answer sent after it, from the capture night of
``run-2026-09-27-131354``. The outputs are the six files under
``tests/fixtures/profile_tabs_more/``, which are committed, so nothing of a third party may
survive into them. The rules are by key, and a value no rule keeps is replaced:

- ``status``, ``__typename`` and ``product_type`` are kept verbatim, since the mappers read them
  and none is content, and so are booleans and nulls
- every identifier is replaced by a synthetic one of the same length, consistently across all six
  files and in the keys of ``friendship_statuses`` too, so a status still names the row it belongs
  to and a row's ``pk`` still equals its ``id``
- ``next_max_id`` stays a number as a string, since on this list it is an offset and not a token,
  and the cursors and ``follow_ranking_token`` become synthetic tokens of the same length
- the integers the mappers read as shapes are kept (``page_size``, ``media_type``,
  ``carousel_media_count``, the sizes, ``hidden_following_account_count``), and every other
  integer becomes zero
- every other string becomes a placeholder of the same length, and a URL a URL on a reserved
  domain

The browser capture redacted each row's ``pk`` and ``pk_id`` and kept ``id``. Every row of the
four engine pages carried the three equal, so the builder restores both from ``id`` before
anything is replaced, and says so in its report.

The script then checks its own output: no replaced value of four characters or more may appear
in any file written, and it reports how many it checked, which is the control that the check
ran against something.

Run from ``engine/`` with ``uv run python scripts/build_profile_tabs_more_fixtures.py``. Writes a
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
FIXTURE_DIR = ENGINE / "tests" / "fixtures" / "profile_tabs_more"
CAPTURES = ENGINE.parent / "skills" / "reverse-engineer" / "var" / "captures"
PROFILE_STAGE = "e2-capture-replays-2026-09-27-151200"
BROWSER_FOLLOWING = "run-2026-09-27-131354-b10-following-open.jsonl"

VERBATIM_KEYS = frozenset({"status", "__typename", "product_type"})

KEPT_INTEGER_KEYS = frozenset(
   {
      "page_size",
      "media_type",
      "carousel_media_count",
      "original_width",
      "original_height",
      "width",
      "height",
      "hidden_following_account_count",
   }
)

OFFSET_KEYS = frozenset({"next_max_id"})

CURSOR_KEYS = frozenset({"cursor", "end_cursor", "start_cursor", "follow_ranking_token"})

KEYED_BY_ACCOUNT = "friendship_statuses"

MINIMUM_CHECKED_LENGTH = 4

COMPOUND_ID = re.compile(r"([0-9]+)_([0-9]+)")

REPLAYED = {
   "reels_tab.json": f"{PROFILE_STAGE}-03-profile-reels-tab-1.json",
   "tagged_tab.json": f"{PROFILE_STAGE}-05-profile-tagged-tab-1.json",
   "following_first_page.json": f"{PROFILE_STAGE}-07-following-first-page-1.json",
   "following_next_page.json": f"{PROFILE_STAGE}-09-following-next-page-1.json",
}

BROWSER = {
   "following_browser_page.json": "/following/",
   "following_statuses.json": "/show_many/",
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

      is_an_offset = key in OFFSET_KEYS and value.isdigit()

      if is_an_offset:
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


def browser_answers() -> dict[str, Any]:
   """The first following page and the statuses the browser sent after it, in capture order."""

   found: dict[str, Any] = {}

   for line in (CAPTURES / BROWSER_FOLLOWING).read_text().splitlines():
      entry = json.loads(line)

      for name, path_part in BROWSER.items():
         is_the_first_of_its_kind = path_part in entry.get("url", "") and name not in found

         if is_the_first_of_its_kind:
            found[name] = json.loads(entry["response_body"])

   return found


def restore_redacted_ids(page: dict[str, Any]) -> int:
   restored = 0

   for user in page["users"]:
      user["pk"] = user["id"]
      user["pk_id"] = user["id"]
      restored += 1

   return restored


def main() -> int:
   inputs = {name: json.loads((CAPTURES / source).read_text()) for name, source in REPLAYED.items()}
   inputs.update(browser_answers())
   rows_restored = restore_redacted_ids(inputs["following_browser_page.json"])

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
      "browser_rows_with_pk_restored_from_id": rows_restored,
      "values_replaced": len(pseudonymiser.replacements),
      "values_checked_absent": len(checked),
      "files_with_a_survivor": sorted(set(survivors)),
   }

   LOG_DIR.mkdir(parents=True, exist_ok=True)
   stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
   log_path = LOG_DIR / f"profile-tabs-more-fixtures-{stamp}.json"
   log_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
   print(json.dumps(report, indent=2))
   print(f"log written to {log_path}")

   has_a_survivor = bool(survivors)
   checked_nothing = not checked
   missed_a_browser_answer = len(inputs) != len(REPLAYED) + len(BROWSER)

   return 1 if has_a_survivor or checked_nothing or missed_a_browser_answer else 0


if __name__ == "__main__":
   sys.exit(main())
