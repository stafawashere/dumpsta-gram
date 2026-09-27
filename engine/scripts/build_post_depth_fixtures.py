"""Turn the E2 batch 4 captures into the pseudonymised fixtures the post depth gates replay.

The inputs are local and outside git: the bodies ``probes/e2_post_depth.py``,
``probes/e2_next_pages.py`` and ``probes/e2_post_by_id_shape.py`` kept under the skill's
``var/captures/`` on 2026-09-27. The outputs are the eleven files under
``tests/fixtures/post_depth/``, which are committed, so nothing of a third party may survive
into them. The rules are by key, and a value no rule keeps is replaced:

- enum-like values (``__typename``, ``product_type``, ``profile_grid_thumbnail_fitting_style``)
  and the answer's own ``status`` are kept verbatim, and so are booleans and nulls
- an ``errors`` entry keeps its ``message``, ``severity`` and ``path`` verbatim, since none of
  them is content and the partial answer rule reads the path
- every identifier is replaced by a synthetic one of the same length, consistently across all
  eleven files, including both parts of a ``<pk>_<author id>``, so a reply still names its parent
  comment, a post's ``id`` still names its ``pk``, and the post the home page shows is the post
  the other reads were keyed on
- every ``taken_at`` and ``created_at`` is shifted by one constant, so order and spacing survive
  and the date does not
- a DASH manifest becomes a one-element manifest carrying only its duration, which the mapper
  reads
- every cursor becomes a synthetic token of the same length
- ``media_type``, a rendition's ``type``, ``carousel_media_count`` and a comment's two counts,
  ``child_comment_count`` and ``comment_like_count``, are kept, because the reply count is what
  says a comment has replies and a like count told apart from zero is what a mapping gate needs,
  and every other integer becomes zero
- every float becomes zero, which covers coordinates and tag positions
- every other string becomes a placeholder of the same length, and a URL a URL on a reserved
  domain
- the ``extensions`` block is dropped

The home timeline page is trimmed to its edges that carry a post, six of them, because the ads
and suggestions beside them are half a megabyte that no gate here reads.

The script then checks its own output: no replaced value of four characters or more may appear
in any file written, and it reports how many it checked, which is the control that the check
ran against something.

Run from ``engine/`` with ``uv run python scripts/build_post_depth_fixtures.py``. Writes a
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
FIXTURE_DIR = ENGINE / "tests" / "fixtures" / "post_depth"
CAPTURES = ENGINE.parent / "skills" / "reverse-engineer" / "var" / "captures"
POST_DEPTH = "e2-post-depth-2026-09-27-013544"
NEXT_PAGES = "e2-next-pages-2026-09-27-014233"
BY_ID_SHAPE = "e2-post-by-id-shape-2026-09-27-032711"

SHIFTED_EPOCH_SECONDS = 1_577_836_800
"""2020-01-01T00:00:00Z. The oldest time in the inputs lands here."""

VERBATIM_KEYS = frozenset(
   {"__typename", "product_type", "profile_grid_thumbnail_fitting_style", "status"}
)

KEPT_INTEGER_KEYS = frozenset(
   {"media_type", "type", "child_comment_count", "comment_like_count", "carousel_media_count"}
)

SHIFTED_TIME_KEYS = frozenset({"taken_at", "created_at"})

CURSOR_KEYS = frozenset({"cursor", "end_cursor", "start_cursor"})

VERBATIM_ERROR_KEYS = frozenset({"message", "severity", "path"})

MINIMUM_CHECKED_LENGTH = 4

HOME_ROOT = "xdt_api__v1__feed__timeline__connection"

MANIFEST_DURATION = re.compile(r'\bmediaPresentationDuration="([^"]*)"')

COMPOUND_ID = re.compile(r"([0-9]+)_([0-9]+)")

OUTPUTS = {
   "home_timeline_posts.json": f"{POST_DEPTH}-02-home-timeline-first-page.json",
   "comment_page.json": f"{POST_DEPTH}-03-first-comment-page.json",
   "replies_whole.json": f"{POST_DEPTH}-04-replies-1.json",
   "likers.json": f"{POST_DEPTH}-06-likers-1.json",
   "post_by_media_id_partial.json": f"{POST_DEPTH}-08-post-by-media-pk-1-rejected.json",
   "post_by_media_id.json": f"{POST_DEPTH}-09-post-by-media-pk-2.json",
   "more_from_author.json": f"{POST_DEPTH}-12-more-posts-from-the-account-1.json",
   "replies_first_page.json": f"{NEXT_PAGES}-08-replies-1.json",
   "replies_next_page.json": f"{NEXT_PAGES}-09-replies-next-page-1.json",
   "post_by_media_id_reel.json": f"{BY_ID_SHAPE}-03-video-post-by-media-pk-1.json",
   "post_by_media_id_reel_original_sound.json": f"{BY_ID_SHAPE}-04-video-post-by-media-pk-2.json",
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

   def error(self, entry: Any) -> Any:
      if not isinstance(entry, dict):
         return self.walk(entry)

      return {
         key: value if key in VERBATIM_ERROR_KEYS else self.walk(value, key)
         for key, value in entry.items()
      }

   def walk(self, value: Any, key: str = "") -> Any:
      if isinstance(value, dict):
         return {
            inner_key: self._inner(inner_key, inner)
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

   def _inner(self, key: str, value: Any) -> Any:
      if key == "errors" and isinstance(value, list):
         return [self.error(entry) for entry in value]

      return self.walk(value, key)


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


def _only_posts(home_page: dict[str, Any]) -> dict[str, Any]:
   connection = home_page["data"][HOME_ROOT]
   post_edges = [
      edge
      for edge in connection["edges"]
      if isinstance(edge.get("node"), dict) and isinstance(edge["node"].get("media"), dict)
   ]

   return {**home_page, "data": {HOME_ROOT: {**connection, "edges": post_edges}}}


def main() -> int:
   inputs = {name: json.loads((CAPTURES / source).read_text()) for name, source in OUTPUTS.items()}
   inputs["home_timeline_posts.json"] = _only_posts(inputs["home_timeline_posts.json"])
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
   log_path = LOG_DIR / f"post-depth-fixtures-{stamp}.json"
   log_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
   print(json.dumps(report, indent=2))
   print(f"log written to {log_path}")

   has_a_survivor = bool(survivors)
   checked_nothing = not checked

   return 1 if has_a_survivor or checked_nothing else 0


if __name__ == "__main__":
   sys.exit(main())
