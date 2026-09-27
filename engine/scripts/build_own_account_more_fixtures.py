"""Turn the E2 batch 11c captures into the pseudonymised fixtures the saved posts, saved
collections and close friends gates replay.

The inputs are local and outside git: the bodies ``probes/e2_capture_replays.py`` kept under the
skill's ``var/captures/`` on 2026-09-27 for its ``saved`` and ``close-friends`` stages, run
``run-2026-09-27-151121``. The outputs are the three files under
``tests/fixtures/own_account_more/``, which are committed, so nothing of a third party and
nothing of the viewer's own may survive into them.

The saved posts and the saved tab are JSON and follow the rules of the batch 11b builder, by key:

- ``__typename``, ``product_type``, ``status``, and the saved tab's ``collection_id`` and
  ``collection_name``, which are the upstream's constant names of its two automatic collections,
  are kept verbatim, and so are booleans and nulls
- every identifier is replaced by a synthetic one of the same length, consistently across the
  files, including both parts of a ``<pk>_<author id>``
- every ``taken_at`` is shifted by one constant, so order and spacing survive and the date does
  not
- a DASH manifest becomes a one-element manifest carrying only its duration
- ``next_max_id`` becomes a synthetic token of the same length
- ``media_type``, a rendition's ``type``, widths, heights and ``collection_media_count`` are kept,
  and every other integer becomes zero
- every other string becomes a placeholder of the same length, and a URL a URL on a reserved
  domain

The saved posts are trimmed to their first three items, two reels and the saved advertisement,
which lacks ``like_and_view_counts_disabled`` and ``clips_metadata``.

The close friends answer is a Bloks tree. Its data entries that hold accounts are rewritten row by
row: the id becomes synthetic digits of the same length under the same 32 or 64 bit constant, the
username and name placeholders, and the picture a reserved URL. The close friends list keeps all
seven rows and the list of accounts offered to add keeps its first three of 114. The rest of the
tree, which is the screen's own interface text, icons and bindings, is kept, and the answer's
request ids, logging id and version id are replaced.

The script then checks its own output: no replaced value of eight characters or more may appear
anywhere in a file written, and none of four to seven may appear as a whole string value, since a
short value such as ``default`` is also part of many key names and is a key name itself. A value
also kept verbatim under an enum-like key, such as ``clips``, is not checked. The ids, usernames
and pictures of the rows dropped from the close friends answer are checked the same way. It
reports how many it checked, which is the control that the check ran against something.

Run from ``engine/`` with ``uv run python scripts/build_own_account_more_fixtures.py``. Writes a
report to ``engine/logs/``.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dumpstagram._private.web.parse.bloks import (
   BloksAtom,
   BloksCall,
   BloksValue,
   read_bloks_script,
)

ENGINE = Path(__file__).resolve().parents[1]
LOG_DIR = ENGINE / "logs"
FIXTURE_DIR = ENGINE / "tests" / "fixtures" / "own_account_more"
CAPTURES = ENGINE.parent / "skills" / "reverse-engineer" / "var" / "captures"
SAVED = "e2-capture-replays-2026-09-27-151324"
CLOSE_FRIENDS = "e2-capture-replays-2026-09-27-151359"

SHIFTED_EPOCH_SECONDS = 1_577_836_800
"""2020-01-01T00:00:00Z. The oldest time in the inputs lands here."""

VERBATIM_KEYS = frozenset(
   {"__typename", "__isXDTSavedCollectionItem", "product_type", "status", "collection_id"}
)

VERBATIM_COLLECTION_NAMES = frozenset({"All posts", "Audio"})

KEPT_INTEGER_KEYS = frozenset(
   {
      "media_type",
      "type",
      "width",
      "height",
      "original_width",
      "original_height",
      "carousel_media_count",
      "collection_media_count",
   }
)

SHIFTED_TIME_KEYS = frozenset({"taken_at"})

CURSOR_KEYS = frozenset({"next_max_id", "cursor", "end_cursor"})

REPLACED_ENVELOPE_KEYS = frozenset({"rid", "lid", "logging_id", "source_map_id", "versioning_id"})

MINIMUM_CHECKED_LENGTH = 4

SUBSTRING_CHECKED_LENGTH = 8

KEPT_SAVED_ITEMS = 3

KEPT_OFFERED_ROWS = 3

ACCOUNT_ROW_KEYS = ("user_id", "username", "name", "profile_pic_url", "is_verified")

MANIFEST_DURATION = re.compile(r'\bmediaPresentationDuration="([^"]*)"')

COMPOUND_ID = re.compile(r"([0-9]+)_([0-9]+)")


class Pseudonymiser:
   def __init__(self, offset_seconds: int) -> None:
      self.offset_seconds = offset_seconds
      self.replacements: dict[str, str] = {}
      self.kept_verbatim: set[str] = set()
      self.dropped: set[str] = set()
      self.counter = 0

   def synthetic(self, original: str, kind: str) -> str:
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
      is_a_constant_name = key == "collection_name" and value in VERBATIM_COLLECTION_NAMES

      if key in VERBATIM_KEYS or is_a_constant_name:
         self.kept_verbatim.add(value)

         return value

      if key == "video_dash_manifest":
         return self._manifest(value)

      if key in CURSOR_KEYS:
         return self.synthetic(value, "cursor") if value else value

      if value.startswith("http"):
         return self.synthetic(value, "url")

      if value.isdigit():
         return self.synthetic(value, "digits")

      compound = COMPOUND_ID.fullmatch(value)

      if compound is not None:
         media, author = compound.groups()

         return f"{self.synthetic(media, 'digits')}_{self.synthetic(author, 'digits')}"

      return self.synthetic(value, "text")

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
         return 0.0

      if isinstance(value, str):
         return self.string(key, value)

      return value


def write_bloks(value: BloksValue) -> str:
   if isinstance(value, BloksCall):
      parts = [value.name, *(write_bloks(argument) for argument in value.arguments)]

      return f"({', '.join(parts)})"

   if isinstance(value, BloksAtom):
      return value.text

   return json.dumps(value)


def account_rows(value: BloksValue) -> list[BloksCall] | None:
   """The rows of an array of account maps, or ``None`` when ``value`` is anything else."""

   is_an_array = isinstance(value, BloksCall) and value.name == "bk.action.array.Make"

   if not is_an_array or not value.arguments:
      return None

   rows = []

   for row in value.arguments:
      keys = row.arguments[0] if isinstance(row, BloksCall) and row.arguments else None
      is_an_account_row = (
         isinstance(row, BloksCall)
         and row.name == "bk.action.map.Make"
         and isinstance(keys, BloksCall)
         and keys.arguments == ACCOUNT_ROW_KEYS
      )

      if not is_an_account_row:
         return None

      rows.append(row)

   return rows


def dropped_values(row: BloksCall) -> list[str]:
   """The id, username and picture of a row left out of the fixture."""

   values = row.arguments[1]
   assert isinstance(values, BloksCall)
   user_id, username, _, picture, _ = values.arguments
   assert isinstance(user_id, BloksCall)
   assert isinstance(user_id.arguments[0], BloksAtom)

   return [user_id.arguments[0].text, str(username), str(picture)]


def pseudonymous_row(row: BloksCall, pseudonymiser: Pseudonymiser) -> BloksCall:
   keys, values = row.arguments
   assert isinstance(values, BloksCall)
   user_id, username, name, picture, verified = values.arguments
   assert isinstance(user_id, BloksCall)
   assert isinstance(user_id.arguments[0], BloksAtom)
   assert isinstance(username, str)
   assert isinstance(name, str)
   assert isinstance(picture, str)
   synthetic_id = BloksCall(
      name=user_id.name,
      arguments=(BloksAtom(pseudonymiser.synthetic(user_id.arguments[0].text, "digits")),),
   )
   synthetic_values = BloksCall(
      name=values.name,
      arguments=(
         synthetic_id,
         pseudonymiser.synthetic(username, "text"),
         pseudonymiser.synthetic(name, "text") if name else name,
         pseudonymiser.synthetic(picture, "url"),
         verified,
      ),
   )

   return BloksCall(name=row.name, arguments=(keys, synthetic_values))


def pseudonymous_close_friends(answer: dict[str, Any], pseudonymiser: Pseudonymiser) -> Any:
   bloks_payload = answer["payload"]["layout"]["bloks_payload"]
   account_lists = 0

   for entry in bloks_payload["data"]:
      script = entry["data"]["initial_lispy"]
      rows = account_rows(read_bloks_script(script, entry["id"]))

      if rows is None:
         continue

      account_lists += 1
      kept = rows if len(rows) < 10 else rows[:KEPT_OFFERED_ROWS]

      for row in rows[len(kept) :]:
         pseudonymiser.dropped.update(dropped_values(row))
      rewritten = BloksCall(
         name="bk.action.array.Make",
         arguments=tuple(pseudonymous_row(row, pseudonymiser) for row in kept),
      )
      entry["data"]["initial_lispy"] = write_bloks(rewritten)

   assert account_lists == 2, account_lists

   def replace_envelope(value: Any) -> Any:
      if isinstance(value, dict):
         return {
            key: (
               pseudonymiser.synthetic(inner, "text")
               if key in REPLACED_ENVELOPE_KEYS and isinstance(inner, str)
               else replace_envelope(inner)
            )
            for key, inner in value.items()
         }

      if isinstance(value, list):
         return [replace_envelope(inner) for inner in value]

      return value

   return replace_envelope(answer)


def survives(original: str, text: str) -> bool:
   """Whether ``original`` is still in ``text``: anywhere when it is long, and as a whole JSON
   string value, plain or inside a Bloks script, when it is short, since a short value such as
   ``default`` is also part of many key names and is itself a key name."""

   as_json = json.dumps(original)
   as_escaped_json = json.dumps(as_json)[1:-1]

   if len(original) >= SUBSTRING_CHECKED_LENGTH:
      return original in text or as_json[1:-1] in text

   as_a_value = re.compile(f"(?:{re.escape(as_json)}|{re.escape(as_escaped_json)})(?!\\s*:)")

   return as_a_value.search(text) is not None


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


def main() -> int:
   saved_posts = json.loads((CAPTURES / f"{SAVED}-05-all-saved-posts-1.json").read_text())
   saved_posts["items"] = saved_posts["items"][:KEPT_SAVED_ITEMS]
   collections = json.loads((CAPTURES / f"{SAVED}-03-saved-collections-tab-1.json").read_text())
   close_friends = json.loads(
      (CAPTURES / f"{CLOSE_FRIENDS}-02-close-friends-list-1.json").read_text()
   )
   offset_seconds = min(_times(saved_posts)) - SHIFTED_EPOCH_SECONDS
   pseudonymiser = Pseudonymiser(offset_seconds)
   written = {
      "saved_posts.json": pseudonymiser.walk(saved_posts),
      "saved_collections.json": pseudonymiser.walk(collections),
      "close_friends.json": pseudonymous_close_friends(close_friends, pseudonymiser),
   }

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
      and original not in pseudonymiser.kept_verbatim
   ]
   checked.extend(value for value in pseudonymiser.dropped if len(value) >= MINIMUM_CHECKED_LENGTH)
   survivors = [
      name for name, text in texts.items() for original in checked if survives(original, text)
   ]
   report = {
      "fixtures": sorted(texts),
      "bytes": {name: len(text) for name, text in texts.items()},
      "values_replaced": len(pseudonymiser.replacements),
      "values_checked_absent": len(checked),
      "files_with_a_survivor": sorted(set(survivors)),
   }

   LOG_DIR.mkdir(parents=True, exist_ok=True)
   stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
   log_path = LOG_DIR / f"own-account-more-fixtures-{stamp}.json"
   log_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
   print(json.dumps(report, indent=2))
   print(f"log written to {log_path}")

   has_a_survivor = bool(survivors)
   checked_nothing = not checked

   return 1 if has_a_survivor or checked_nothing else 0


if __name__ == "__main__":
   sys.exit(main())
