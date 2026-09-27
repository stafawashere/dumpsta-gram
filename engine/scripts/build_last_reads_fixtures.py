"""Turn the E2 batch 11e captures into the pseudonymised fixtures the explore next page, audio page
and mutual followers gates replay.

The inputs are local and outside git: the bodies ``probes/e2_last_reads_replay.py`` kept under the
skill's ``var/captures/`` on 2026-09-27, run ``run-2026-09-27-183420``, and the browser captures
of run ``run-2026-09-27-182013``, one JSON object per request with the answer in
``response_body``. The outputs are the files under ``tests/fixtures/last_reads/``, which are
committed, so nothing of a third party may survive into them. The rules are those of
``scripts/build_discovery_search_fixtures.py``, by key, and a value no rule keeps is replaced:

- enum-like values (``__typename``, ``product_type``, ``status``, ``feed_type`` and
  ``layout_type``) are kept verbatim, and so are booleans and nulls
- every identifier is replaced by a synthetic one of the same length, consistently across all
  files, including both parts of a ``<pk>_<author id>``, and a key naming an account in
  ``friendship_statuses`` is replaced the same way
- every ``taken_at`` is shifted by one constant, so order and spacing survive and the date does
  not
- a DASH manifest becomes a one-element manifest carrying only its duration
- every cursor (``max_id``, ``next_max_id``, ``session_paging_token``, ``rank_token``) becomes a
  synthetic token of the same length
- ``media_type``, widths, heights, ``clips_count`` and ``photos_count`` are kept, and every other
  integer becomes zero
- every other string becomes a placeholder of the same length, and a URL a URL on a reserved
  domain

Trimmed, to keep the files small: the explore next page to its first two sections, one with its
large tile last and one with it first; the song's first page to three reels, the reel with
collaborators among them; the song's second page to two reels. The original sound's two pages,
the mutual followers answer and its statuses are kept whole, and so is a reels feed next page the
replayed on 2026-09-27 at 19:12 by ``probes/e2_capture_replays.py --stage reels``, whose third
reel is tagged at a place sent with only ``name`` and ``pk`` (W120). The ``for (;;);`` prefix is
dropped from the audio answers, since the tests serve them as JSON.

The script then checks its own output: no replaced value of four characters or more may appear
in any file written, and it reports how many it checked, the control that the check ran. A
replaced value that is part of a key name or a kept enum somewhere in the inputs, such as
``clips`` or ``comment``, is not checked, since it survives inside that name; the report lists
every such word so a reader can see none is a name.

Run from ``engine/`` with ``uv run python scripts/build_last_reads_fixtures.py``. Writes a report
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
FIXTURE_DIR = ENGINE / "tests" / "fixtures" / "last_reads"
CAPTURES = ENGINE.parent / "skills" / "reverse-engineer" / "var" / "captures"
EXPLORE = "e2-last-reads-replay-2026-09-27-183421"
AUDIO = "e2-last-reads-replay-2026-09-27-183446"
BROWSER = "run-2026-09-27-182013"
REELS = "e2-capture-replays-2026-09-27-191243"

SHIFTED_EPOCH_SECONDS = 1_577_836_800
"""2020-01-01T00:00:00Z. The oldest time in the inputs lands here."""

VERBATIM_KEYS = frozenset({"__typename", "product_type", "status", "feed_type", "layout_type"})

KEPT_INTEGER_KEYS = frozenset(
   {
      "media_type",
      "type",
      "carousel_media_count",
      "width",
      "height",
      "original_width",
      "original_height",
      "clips_count",
      "photos_count",
   }
)

SHIFTED_TIME_KEYS = frozenset({"taken_at"})

CURSOR_KEYS = frozenset({"max_id", "next_max_id", "session_paging_token", "rank_token"})

ACCOUNT_KEYED_OBJECTS = frozenset({"friendship_statuses"})

MINIMUM_CHECKED_LENGTH = 4

JSONP_PREFIX = "for (;;);"

MANIFEST_DURATION = re.compile(r'\bmediaPresentationDuration="([^"]*)"')

COMPOUND_ID = re.compile(r"([0-9]+)_([0-9]+)")

KEPT_EXPLORE_SECTIONS = 2

KEPT_SONG_FIRST_PAGE_ITEMS = (0, 1, 6)

KEPT_SONG_SECOND_PAGE_ITEMS = 2


class Pseudonymiser:
   def __init__(self, offset_seconds: int) -> None:
      self.offset_seconds = offset_seconds
      self.replacements: dict[str, str] = {}
      self.structural: set[str] = set()
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

   def is_structural(self, original: str) -> bool:
      """Whether ``original`` is part of a key name or a kept enum, where it survives as that."""

      return any(original in word for word in self.structural)

   def _manifest(self, manifest: str) -> str:
      duration = MANIFEST_DURATION.search(manifest)
      duration_attribute = (
         f' mediaPresentationDuration="{duration.group(1)}"' if duration is not None else ""
      )

      return f'<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static"{duration_attribute}/>'

   def string(self, key: str, value: str) -> str:
      if key in VERBATIM_KEYS:
         self.structural.add(value)

         return value

      if key in ("video_dash_manifest", "dash_manifest"):
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
         renames_its_keys = key in ACCOUNT_KEYED_OBJECTS

         if not renames_its_keys:
            self.structural.update(value)

         return {
            (self.string("", inner_key) if renames_its_keys else inner_key): self.walk(
               inner, inner_key
            )
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
         return 0.0

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


def _answer_text(text: str) -> Any:
   body = text[len(JSONP_PREFIX) :] if text.startswith(JSONP_PREFIX) else text

   return json.loads(body)


def _kept(name: str) -> Any:
   return _answer_text((CAPTURES / name).read_text(encoding="utf-8"))


def _browser_answers(window: str, url_part: str) -> list[Any]:
   answers = []

   for line in (CAPTURES / f"{BROWSER}-{window}.jsonl").read_text(encoding="utf-8").splitlines():
      record = json.loads(line)

      if url_part in record["url"]:
         answers.append(_answer_text(record["response_body"]))

   return answers


def _with_items(answer: dict[str, Any], indexes: tuple[int, ...]) -> dict[str, Any]:
   payload = answer["payload"]
   items = [payload["items"][index] for index in indexes]

   return {**answer, "payload": {**payload, "items": items}}


def main() -> int:
   explore_next = _kept(f"{EXPLORE}-03-explore-grid-next-page-1.json")
   explore_next["sectional_items"] = explore_next["sectional_items"][:KEPT_EXPLORE_SECTIONS]
   song_pages = _browser_answers("audio-page-music-scroll", "/clips/music/")
   mutual_answers = _browser_answers("mutual-followers-open", "/mutual_followers/")
   statuses_answers = _browser_answers("mutual-followers-open", "/show_many/")

   inputs = {
      "explore_next_page.json": explore_next,
      "audio_song_first_page.json": _with_items(song_pages[0], KEPT_SONG_FIRST_PAGE_ITEMS),
      "audio_song_second_page.json": _with_items(
         song_pages[1], tuple(range(KEPT_SONG_SECOND_PAGE_ITEMS))
      ),
      "audio_original_first_page.json": _kept(f"{AUDIO}-04-audio-page-1.json"),
      "audio_original_second_page.json": _kept(f"{AUDIO}-06-audio-page-next-page-1.json"),
      "mutual_followers.json": mutual_answers[0],
      "mutual_statuses.json": statuses_answers[0],
      "reels_thin_location_page.json": _kept(f"{REELS}-04-reels-feed-next-page-1.json"),
   }
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
      if len(original) >= MINIMUM_CHECKED_LENGTH
      and original != synthetic
      and not pseudonymiser.is_structural(original)
   ]
   structural_words = sorted(
      original for original in pseudonymiser.replacements if pseudonymiser.is_structural(original)
   )
   survivors = [name for name, text in texts.items() for original in checked if original in text]
   report = {
      "fixtures": sorted(texts),
      "bytes": {name: len(text) for name, text in texts.items()},
      "values_replaced": len(pseudonymiser.replacements),
      "values_checked_absent": len(checked),
      "not_checked_as_key_names_or_kept_enums": structural_words,
      "files_with_a_survivor": sorted(set(survivors)),
   }

   LOG_DIR.mkdir(parents=True, exist_ok=True)
   stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
   log_path = LOG_DIR / f"last-reads-fixtures-{stamp}.json"
   log_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
   print(json.dumps(report, indent=2))
   print(f"log written to {log_path}")

   has_a_survivor = bool(survivors)
   checked_nothing = not checked

   return 1 if has_a_survivor or checked_nothing else 0


if __name__ == "__main__":
   sys.exit(main())
