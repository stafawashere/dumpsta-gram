"""Turn the E2 batch 7 captures into the pseudonymised fixtures the discovery gates replay.

The inputs are local and outside git: the bodies ``probes/e2_discovery_feeds.py`` kept under the
skill's ``var/captures/`` on 2026-09-27. The outputs are the five files under
``tests/fixtures/discovery/``, which are committed, so nothing of a third party may survive into
them. The rules are by key, and a value no rule keeps is replaced:

- enum-like values (``__typename``, ``product_type``, ``feed_type``, ``layout_type`` and the
  eleven more in :data:`VERBATIM_KEYS`, whose values are words such as ``default`` or
  ``licensed_music`` that a key name also spells) and the answer's own ``status`` are kept
  verbatim, and so are booleans and nulls
- every identifier is replaced by a synthetic one of the same length, consistently across all
  five files, including both parts of a ``<pk>_<author id>``
- every ``taken_at`` is shifted by one constant, so order and spacing survive and the date does
  not
- a DASH manifest becomes a one-element manifest carrying only its duration, which the mapper
  reads
- every cursor becomes a synthetic token of the same length
- ``media_type``, a rendition's ``type``, ``carousel_media_count``, a place's ``media_count``
  and ``price_range``, widths and heights are kept, since none of them names anyone, and every
  other integer becomes zero
- ``video_duration`` is kept, since the explore grid's own copy of a reel's length is what the
  duration gate compares the manifest against, and every other float becomes zero, which covers
  coordinates
- every other string becomes a placeholder of the same length, and a URL a URL on a reserved
  domain
- the ``extensions`` block is dropped

The two explore answers are about a megabyte each, so each is trimmed through this script: the
first answer to its first section, whose five posts hold a photo and a reel tagged at a place,
and the second to its second section with only its featured reel and the one carousel of both
answers. The place's grid is trimmed to its first four edges, keeping its own ``page_info``.

The script then checks its own output: no replaced value of four characters or more may appear
in any file written, and it reports how many it checked, which is the control that the check
ran against something.

Run from ``engine/`` with ``uv run python scripts/build_discovery_fixtures.py``. Writes a report
to ``engine/logs/``.
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
FIXTURE_DIR = ENGINE / "tests" / "fixtures" / "discovery"
CAPTURES = ENGINE.parent / "skills" / "reverse-engineer" / "var" / "captures"
DISCOVERY = "e2-discovery-feeds-2026-09-27-013758"

SHIFTED_EPOCH_SECONDS = 1_577_836_800
"""2020-01-01T00:00:00Z. The oldest time in the inputs lands here."""

VERBATIM_KEYS = frozenset(
   {
      "__typename",
      "product_type",
      "feed_type",
      "layout_type",
      "status",
      "action_type",
      "audio_type",
      "clips_creation_entry_point",
      "confirmation_style",
      "content_source",
      "content_type",
      "external_source",
      "integrity_review_decision",
      "open_carousel_submission_state",
      "original_audio_subtype",
      "undo_style",
   }
)

KEPT_INTEGER_KEYS = frozenset(
   {
      "media_type",
      "type",
      "carousel_media_count",
      "media_count",
      "price_range",
      "width",
      "height",
      "original_width",
      "original_height",
   }
)

KEPT_FLOAT_KEYS = frozenset({"video_duration"})

SHIFTED_TIME_KEYS = frozenset({"taken_at"})

CURSOR_KEYS = frozenset({"cursor", "end_cursor", "start_cursor"})

MINIMUM_CHECKED_LENGTH = 4

TAB_ROOT = "xdt_location_get_web_info_tab"

LOCATION_POSTS_EDGES = 4

CAROUSEL_MEDIA_TYPE = 8

MANIFEST_DURATION = re.compile(r'\bmediaPresentationDuration="([^"]*)"')

COMPOUND_ID = re.compile(r"([0-9]+)_([0-9]+)")

OUTPUTS = {
   "explore_grid.json": f"{DISCOVERY}-02-explore-grid-1.json",
   "explore_carousel.json": f"{DISCOVERY}-03-explore-grid-2.json",
   "location_info.json": f"{DISCOVERY}-04-location-header-1.json",
   "location_posts.json": f"{DISCOVERY}-06-location-grid-1.json",
   "new_feed_posts.json": f"{DISCOVERY}-10-new-feed-posts-check-1.json",
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
      elif kind == "cursor":
         synthetic = ("C" + str(number).rjust(6, "0")).ljust(length, "c")[:length]
      elif kind == "url":
         synthetic = f"https://example.invalid/{number}"
      else:
         synthetic = ("p" + str(number)).ljust(length, "x")[:length] if length else ""

      self.replacements[original] = synthetic

      return synthetic

   def _manifest(self, manifest: str) -> str:
      duration = MANIFEST_DURATION.search(manifest)
      duration_attribute = (
         f' mediaPresentationDuration="{duration.group(1)}"' if duration is not None else ""
      )

      return f'<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static"{duration_attribute}/>'

   def string(self, key: str, value: str) -> str:
      if key in VERBATIM_KEYS:
         return value

      if key == "video_dash_manifest":
         return self._manifest(value)

      if key in CURSOR_KEYS:
         return self._synthetic(value, "cursor") if value else value

      if value.startswith("http"):
         return self._synthetic(value, "url")

      if value.isdigit():
         return self._synthetic(value, "digits")

      compound = COMPOUND_ID.fullmatch(value)

      if compound is not None:
         media, author = compound.groups()

         return f"{self._synthetic(media, 'digits')}_{self._synthetic(author, 'digits')}"

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
         if key in SHIFTED_TIME_KEYS:
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
         is_a_time = key in SHIFTED_TIME_KEYS and isinstance(inner, int)

         if is_a_time:
            found.append(inner)
         else:
            found.extend(_times(inner))
   elif isinstance(value, list):
      for inner in value:
         found.extend(_times(inner))

   return found


def _first_section(grid: dict[str, Any]) -> dict[str, Any]:
   return {**grid, "sectional_items": grid["sectional_items"][:1]}


def _carousel_section(grid: dict[str, Any]) -> dict[str, Any]:
   section = grid["sectional_items"][1]
   content = section["layout_content"]
   carousels = [
      entry
      for entry in content["fill_items"]
      if entry["media"]["media_type"] == CAROUSEL_MEDIA_TYPE
   ]
   trimmed = {**section, "layout_content": {**content, "fill_items": carousels}}

   return {**grid, "sectional_items": [trimmed]}


def _first_edges(page: dict[str, Any], count: int) -> dict[str, Any]:
   connection = page["data"][TAB_ROOT]

   return {**page, "data": {TAB_ROOT: {**connection, "edges": connection["edges"][:count]}}}


def main() -> int:
   inputs = {name: json.loads((CAPTURES / source).read_text()) for name, source in OUTPUTS.items()}
   inputs["explore_grid.json"] = _first_section(inputs["explore_grid.json"])
   inputs["explore_carousel.json"] = _carousel_section(inputs["explore_carousel.json"])
   inputs["location_posts.json"] = _first_edges(inputs["location_posts.json"], LOCATION_POSTS_EDGES)
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
   log_path = LOG_DIR / f"discovery-fixtures-{stamp}.json"
   log_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
   print(json.dumps(report, indent=2))
   print(f"log written to {log_path}")

   has_a_survivor = bool(survivors)
   checked_nothing = not checked

   return 1 if has_a_survivor or checked_nothing else 0


if __name__ == "__main__":
   sys.exit(main())
