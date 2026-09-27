"""Turn the E2 batch 5 captures into the pseudonymised fixtures the stories gates replay.

The inputs are local and outside git: the bodies ``probes/e2_stories.py`` kept under the skill's
``var/captures/`` on 2026-09-27. The outputs are the three files under ``tests/fixtures/stories/``,
which are committed, so nothing of a third party may survive into them. The rules are by key,
and a value no rule keeps is replaced:

- enum-like values (``__typename``, ``product_type``, ``reel_type``, ``audience``,
  ``gen_ai_detection_method``) are kept verbatim, and so are booleans and nulls
- every identifier is replaced by a synthetic one of the same length, consistently across all
  three files, including both parts of a ``<pk>_<owner id>`` and the number in a
  ``highlight:<number>``, so an item still names its owner and a tray row's id is still its
  owner's
- every time (``taken_at``, ``expiring_at``, ``latest_reel_media``, ``seen`` and the rest) is
  shifted by one constant, so order and spacing survive and the date does not, except a zero,
  which the tray sends for a reel never seen and which stays zero
- ``media_type``, a rendition's ``type``, the tray's two positions, widths and heights and a
  video's duration are kept, since none of them names anyone, and every other integer becomes
  zero
- every other string becomes a placeholder of the same length, and a URL a URL on a reserved
  domain
- the ``extensions`` block is dropped

The script then checks its own output: no replaced value of four characters or more may appear
in any file written, and it reports how many it checked, which is the control that the check
ran against something.

Run from ``engine/`` with ``uv run python scripts/build_stories_fixtures.py``. Writes a report to
``engine/logs/``.
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
FIXTURE_DIR = ENGINE / "tests" / "fixtures" / "stories"
CAPTURES = ENGINE.parent / "skills" / "reverse-engineer" / "var" / "captures"
STORIES = "e2-stories-2026-09-27-013639"

SHIFTED_EPOCH_SECONDS = 1_577_836_800
"""2020-01-01T00:00:00Z. The oldest time in the inputs lands here."""

VERBATIM_KEYS = frozenset(
   {"__typename", "product_type", "reel_type", "audience", "gen_ai_detection_method"}
)

KEPT_INTEGER_KEYS = frozenset(
   {
      "media_type",
      "type",
      "ranked_position",
      "seen_ranked_position",
      "width",
      "height",
      "original_width",
      "original_height",
   }
)

KEPT_FLOAT_KEYS = frozenset({"video_duration"})

SHIFTED_TIME_KEYS = frozenset(
   {
      "taken_at",
      "expiring_at",
      "latest_reel_media",
      "seen",
      "latest_besties_reel_media",
      "reel_media_seen_timestamp",
   }
)

MINIMUM_CHECKED_LENGTH = 4

COMPOUND_ID = re.compile(r"([0-9]+)_([0-9]+)")

HIGHLIGHT_ID = re.compile(r"highlight:([0-9]+)")

OUTPUTS = {
   "stories_tray.json": f"{STORIES}-02-page-load-stories-tray.json",
   "highlight.json": f"{STORIES}-04-own-highlight-1.json",
   "own_reel_empty.json": f"{STORIES}-06-own-reel.json",
}


class Pseudonymiser:
   def __init__(self, offset_seconds: int) -> None:
      self.offset_seconds = offset_seconds
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

      compound = COMPOUND_ID.fullmatch(value)

      if compound is not None:
         media, owner = compound.groups()

         return f"{self._synthetic(media, 'digits')}_{self._synthetic(owner, 'digits')}"

      highlight = HIGHLIGHT_ID.fullmatch(value)

      if highlight is not None:
         return f"highlight:{self._synthetic(highlight.group(1), 'digits')}"

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
         is_a_time = key in SHIFTED_TIME_KEYS and value != 0

         if is_a_time:
            return value - self.offset_seconds

         return value if key in KEPT_INTEGER_KEYS else 0

      if isinstance(value, float):
         return value if key in KEPT_FLOAT_KEYS else 0.0

      if isinstance(value, str):
         return self.string(key, value)

      return value


def _times(value: Any) -> list[int]:
   found: list[int] = []

   if isinstance(value, dict):
      for key, inner in value.items():
         is_a_time = key in SHIFTED_TIME_KEYS and isinstance(inner, int) and inner != 0

         if is_a_time:
            found.append(inner)
         else:
            found.extend(_times(inner))
   elif isinstance(value, list):
      for inner in value:
         found.extend(_times(inner))

   return found


def main() -> int:
   inputs = {name: json.loads((CAPTURES / source).read_text()) for name, source in OUTPUTS.items()}
   every_time = [stamp for payload in inputs.values() for stamp in _times(payload)]
   offset_seconds = min(every_time) - SHIFTED_EPOCH_SECONDS
   pseudonymiser = Pseudonymiser(offset_seconds)
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
   log_path = LOG_DIR / f"stories-fixtures-{stamp}.json"
   log_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
   print(json.dumps(report, indent=2))
   print(f"log written to {log_path}")

   has_a_survivor = bool(survivors)
   checked_nothing = not checked

   return 1 if has_a_survivor or checked_nothing else 0


if __name__ == "__main__":
   sys.exit(main())
