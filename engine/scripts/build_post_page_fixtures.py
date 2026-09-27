"""Turn the E2 batch 11d captures into the pseudonymised fixtures the post page and blocked list
gates replay.

The inputs are local and outside git, under the skill's ``var/captures/``, all kept on
2026-09-27:

- the five results the post page document preloaded, as ``probes/e2_capture_replays.py
  --stage post`` read them out of its first document load, run ``run-2026-09-27-151121``
- the first comments container answer ``probes/e2_page_models.py`` kept, the only answer of that
  query read with comments in it, run ``run-2026-09-27-014102``
- the blocked accounts screen and the reloader's list, from the first run of
  ``probes/e2_blocked_list_replay.py``

The outputs are the four files under ``tests/fixtures/post_page/``, which are committed. The JSON
answers follow the batch 11c builder's rules, which this script imports: enum-like values kept,
every identifier a synthetic one of the same length and consistent across the files, times
shifted by one constant, a DASH manifest reduced to its duration, every other string a
placeholder of the same length and every URL one on a reserved domain.

The blocked list is a Bloks script. Its one data entry is rewritten row by row: the id becomes
synthetic digits of the same length, the username and the secondary text placeholders, an empty
secondary text staying empty, and the picture a reserved URL, both flags kept. It keeps the first
:data:`KEPT_AUTOMATIC_ROWS` of the 41 rows blocked automatically, whose secondary text is one
interface line, and all 11 rows blocked by hand, whose secondary texts all differ, the empty one
among them. The screen carries only the page's own interface text and the
reloader's container ids, which are kept, since the list answer names the same container. The
envelopes' request ids, logging ids and version ids are replaced.

The script then checks its own output the way the batch 11c builder does, the values of the rows
it dropped included, and reports how many values it checked, the control that the check ran.

Run from ``engine/`` with ``uv run python scripts/build_post_page_fixtures.py``. Writes a report
to ``engine/logs/``.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from build_own_account_more_fixtures import (
   MINIMUM_CHECKED_LENGTH,
   REPLACED_ENVELOPE_KEYS,
   SHIFTED_EPOCH_SECONDS,
   Pseudonymiser,
   _times,
   survives,
   write_bloks,
)

from dumpstagram._private.web.parse.bloks import BloksAtom, BloksCall, read_bloks_script

ENGINE = Path(__file__).resolve().parents[1]
LOG_DIR = ENGINE / "logs"
FIXTURE_DIR = ENGINE / "tests" / "fixtures" / "post_page"
CAPTURES = ENGINE.parent / "skills" / "reverse-engineer" / "var" / "captures"
POST_PAGE = "e2-capture-replays-2026-09-27-151424-04-post-page-document-1-preloads.json"
FIRST_COMMENTS = "e2-page-models-2026-09-27-013927-03-post-page-first-comments-1.json"
BLOCKED_SCREEN = "e2-blocked-list-replay-2026-09-27-174542-02-blocked-accounts-screen.json"
BLOCKED_LIST = "e2-blocked-list-replay-2026-09-27-174542-03-blocked-accounts-list.json"

KEPT_AUTOMATIC_ROWS = 3


def kept_rows(rows: tuple[Any, ...]) -> list[BloksCall]:
   """The first :data:`KEPT_AUTOMATIC_ROWS` rows blocked automatically and every row blocked by
   hand, in the list's order."""

   kept = []
   automatic_kept = 0

   for row in rows:
      assert isinstance(row, BloksCall)
      values = row.arguments[1]
      assert isinstance(values, BloksCall)
      flag = values.arguments[5]
      is_automatic = isinstance(flag, BloksCall) and flag.arguments == (BloksAtom("true"),)

      if not is_automatic:
         kept.append(row)
      elif automatic_kept < KEPT_AUTOMATIC_ROWS:
         kept.append(row)
         automatic_kept += 1

   return kept


def pseudonymous_blocked_row(row: BloksCall, pseudonymiser: Pseudonymiser) -> BloksCall:
   keys, values = row.arguments
   assert isinstance(values, BloksCall)
   user_id, username, secondary, verified, picture, auto_blocked = values.arguments
   assert isinstance(user_id, str)
   assert isinstance(username, str)
   assert isinstance(secondary, str)
   assert isinstance(picture, str)
   synthetic_values = BloksCall(
      name=values.name,
      arguments=(
         pseudonymiser.synthetic(user_id, "digits"),
         pseudonymiser.synthetic(username, "text"),
         pseudonymiser.synthetic(secondary, "text") if secondary else secondary,
         verified,
         pseudonymiser.synthetic(picture, "url"),
         auto_blocked,
      ),
   )

   return BloksCall(name=row.name, arguments=(keys, synthetic_values))


def replace_envelope(value: Any, pseudonymiser: Pseudonymiser) -> Any:
   if isinstance(value, dict):
      return {
         key: (
            pseudonymiser.synthetic(inner, "text")
            if key in REPLACED_ENVELOPE_KEYS and isinstance(inner, str)
            else replace_envelope(inner, pseudonymiser)
         )
         for key, inner in value.items()
      }

   if isinstance(value, list):
      return [replace_envelope(inner, pseudonymiser) for inner in value]

   return value


def pseudonymous_blocked_list(answer: dict[str, Any], pseudonymiser: Pseudonymiser) -> Any:
   [entry] = answer["payload"]["layout"]["bloks_payload"]["data"]
   parsed = read_bloks_script(entry["data"]["initial_lispy"], entry["id"])
   assert isinstance(parsed, BloksCall)
   kept = kept_rows(parsed.arguments)

   for row in parsed.arguments:
      if row in kept or not isinstance(row, BloksCall):
         continue

      values = row.arguments[1]
      assert isinstance(values, BloksCall)
      pseudonymiser.dropped.update(
         str(value) for value in values.arguments if not isinstance(value, BloksCall)
      )

   rewritten = BloksCall(
      name=parsed.name,
      arguments=tuple(pseudonymous_blocked_row(row, pseudonymiser) for row in kept),
   )
   entry["data"]["initial_lispy"] = write_bloks(rewritten)

   return replace_envelope(answer, pseudonymiser)


def auto_flags(answer: dict[str, Any]) -> list[bool]:
   [entry] = answer["payload"]["layout"]["bloks_payload"]["data"]
   parsed = read_bloks_script(entry["data"]["initial_lispy"], entry["id"])
   assert isinstance(parsed, BloksCall)
   flags = []

   for row in parsed.arguments:
      assert isinstance(row, BloksCall)
      values = row.arguments[1]
      assert isinstance(values, BloksCall)
      flag = values.arguments[5]
      assert isinstance(flag, BloksCall)
      atom = flag.arguments[0]
      assert isinstance(atom, BloksAtom)
      flags.append(atom.text == "true")

   return flags


def main() -> int:
   preloads = json.loads((CAPTURES / POST_PAGE).read_text())
   first_comments = json.loads((CAPTURES / FIRST_COMMENTS).read_text())
   screen = json.loads((CAPTURES / BLOCKED_SCREEN).read_text())
   blocked = json.loads((CAPTURES / BLOCKED_LIST).read_text())
   offset_seconds = min(_times(preloads) + _times(first_comments)) - SHIFTED_EPOCH_SECONDS
   pseudonymiser = Pseudonymiser(offset_seconds)
   blocked_fixture = pseudonymous_blocked_list(blocked, pseudonymiser)
   written = {
      "post_page_preloads.json": pseudonymiser.walk(preloads),
      "first_comments.json": pseudonymiser.walk(first_comments),
      "blocked_screen.json": replace_envelope(screen, pseudonymiser),
      "blocked_list.json": blocked_fixture,
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
   flags = auto_flags(blocked_fixture)
   report = {
      "fixtures": sorted(texts),
      "bytes": {name: len(text) for name, text in texts.items()},
      "blocked_rows_kept": len(flags),
      "blocked_rows_automatic": sum(flags),
      "values_replaced": len(pseudonymiser.replacements),
      "values_checked_absent": len(checked),
      "files_with_a_survivor": sorted(set(survivors)),
   }

   LOG_DIR.mkdir(parents=True, exist_ok=True)
   stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
   log_path = LOG_DIR / f"post-page-fixtures-{stamp}.json"
   log_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
   print(json.dumps(report, indent=2))
   print(f"log written to {log_path}")

   has_a_survivor = bool(survivors)
   checked_nothing = not checked
   lacks_both_flags = len(set(flags)) != 2

   return 1 if has_a_survivor or checked_nothing or lacks_both_flags else 0


if __name__ == "__main__":
   sys.exit(main())
