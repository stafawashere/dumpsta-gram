"""Turn the E2 batch 6 captures into the pseudonymised fixtures the account gates replay.

The inputs are local and outside git: the bodies ``probes/e2_own_account.py`` kept under the
skill's ``var/captures/`` on 2026-09-27. The outputs are the two files under
``tests/fixtures/account/``, which are committed, so nothing of a third party may survive into
them. The activity feed names other accounts inside its text and quotes comments, so an item's
text is rebuilt rather than walked:

- inside each span a link marks, the linked account's pseudonymous username, of the same
  length, so ``text[start:end]`` still equals the link's ``username``
- outside the spans, every letter and digit becomes ``x``, which keeps the length, the spaces
  and the punctuation and drops the words, a quoted comment's included
- ``rich_text`` is rebuilt the same way, each markup's name and route pseudonymised and its two
  middle fields kept, so stripping the markup still gives ``text``

Everything else goes by key, and a value no rule keeps is replaced:

- ``status``, ``notif_name``, ``aggregation_type``, ``netego_type``, ``comment_notif_type``,
  an indicator's ``name``,
  ``extra_actions``, a link's ``type`` and the section ``headers`` are kept verbatim, since they
  are the upstream's own labels and not content, and so are booleans and nulls
- the integers the mappers read as values, ``story_type``, ``type``, a link's ``start`` and
  ``end``, the section ``indices``, the feed's ``counts``, ``page_size``,
  ``truncate_follow_requests_at_index`` and ``continuation_token``, are kept, and every other
  integer becomes zero
- every time is moved back by one fixed offset, which keeps the order and the gaps
- a username becomes a synthetic one of the same length, wherever it appears, in a row, a
  link, a profile name or a route's ``username`` parameter
- every identifier becomes a synthetic one of the same length, consistently across both files,
  inside ``<pk>_<owner>`` pairs and inside the app routes too
- every URL becomes one on a reserved domain, and every other string a placeholder of the same
  length

The script then checks its own output: no replaced value of four characters or more may appear
in any file written, and it reports how many it checked, which is the control that the check
ran against something.

Run from ``engine/`` with ``uv run python scripts/build_account_fixtures.py``. Writes a report
to ``engine/logs/``.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode

ENGINE = Path(__file__).resolve().parents[1]
LOG_DIR = ENGINE / "logs"
FIXTURE_DIR = ENGINE / "tests" / "fixtures" / "account"
CAPTURES = ENGINE.parent / "skills" / "reverse-engineer" / "var" / "captures"
OWN_ACCOUNT = "e2-own-account-2026-09-27-013721"

VERBATIM_KEYS = frozenset(
   {
      "status",
      "notif_name",
      "aggregation_type",
      "netego_type",
      "comment_notif_type",
      "name",
      "extra_actions",
      "headers",
      "type",
   }
)

KEPT_INTEGER_KEYS = frozenset(
   {
      "story_type",
      "type",
      "start",
      "end",
      "indices",
      "page_size",
      "truncate_follow_requests_at_index",
      "continuation_token",
   }
)

KEPT_WHOLE_KEYS = frozenset({"counts"})

USERNAME_KEYS = frozenset({"username", "profile_name"})

ROUTE_KEYS = frozenset({"destination", "dest", "media_destination", "profile_image_destination"})

TEXT_KEYS = frozenset({"text", "rich_text"})

TIME_OFFSET_SECONDS = 100_000_000.0

MINIMUM_CHECKED_LENGTH = 4

DIGIT_RUN = re.compile(r"[0-9]{4,}")

MARKUP = re.compile(r"\{([^|{}]+)\|([^|{}]*)\|([^|{}]*)\|([^{}]*)\}")

OUTPUTS = {
   "follow_requests.json": f"{OWN_ACCOUNT}-02-pending-follow-requests-1.json",
   "activity_feed.json": f"{OWN_ACCOUNT}-04-activity-feed-1.json",
}


def masked(text: str) -> str:
   return "".join("x" if character.isalnum() else character for character in text)


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
      elif kind == "username":
         synthetic = ("u" + str(number)).ljust(length, "u")[:length]
      elif kind == "url":
         synthetic = f"https://example.invalid/{number}"
      else:
         synthetic = ("p" + str(number)).ljust(length, "x")[:length] if length else ""

      self.replacements[original] = synthetic

      return synthetic

   def username(self, value: str) -> str:
      return self._synthetic(value, "username")

   def digit_runs(self, value: str) -> str:
      return DIGIT_RUN.sub(lambda run: self._synthetic(run.group(0), "digits"), value)

   def route(self, value: str) -> str:
      """An app route, ``<screen>?<query>``, with every identifying parameter replaced."""

      screen, _, query = value.partition("?")
      parameters = []

      for name, parameter in parse_qsl(query, keep_blank_values=True):
         if name == "username":
            parameters.append((name, self.username(parameter)))
         elif name == "url":
            parameters.append((name, self._synthetic(parameter, "url")))
         else:
            parameters.append((name, self.digit_runs(parameter)))

      if not query:
         return screen

      return f"{screen}?{urlencode(parameters, quote_via=quote)}"

   def item_text(self, args: dict[str, Any]) -> tuple[str, str]:
      """The item's ``text`` and ``rich_text``, rebuilt from its links and masked elsewhere."""

      text = args["text"]
      links = args.get("links") or []
      rebuilt = list(masked(text))

      for link in links:
         pseudonym = self.username(link["username"])
         rebuilt[link["start"] : link["end"]] = list(pseudonym)

      rich_parts = []
      position = 0

      for markup in MARKUP.finditer(args["rich_text"]):
         rich_parts.append(masked(args["rich_text"][position : markup.start()]))
         name, first, second, route = markup.groups()
         is_a_user_route = route.startswith("user?")
         shown = self.username(name) if is_a_user_route else masked(name)
         rich_parts.append(f"{{{shown}|{first}|{second}|{self.route(route)}}}")
         position = markup.end()

      rich_parts.append(masked(args["rich_text"][position:]))

      return "".join(rebuilt), "".join(rich_parts)

   def string(self, key: str, value: str) -> str:
      if key in VERBATIM_KEYS:
         return value

      if key in USERNAME_KEYS:
         return self.username(value)

      if key in ROUTE_KEYS:
         return self.route(value)

      if value.startswith("http"):
         return self._synthetic(value, "url")

      if value.isdigit():
         return self._synthetic(value, "digits")

      compound = re.fullmatch(r"([0-9]+)_([0-9]+)", value)

      if compound is not None:
         first, second = compound.groups()

         return f"{self._synthetic(first, 'digits')}_{self._synthetic(second, 'digits')}"

      return self._synthetic(value, "text")

   def walk(self, value: Any, key: str = "") -> Any:
      if key in KEPT_WHOLE_KEYS and isinstance(value, dict):
         return {inner_key: self.walk(inner, "counts_entry") for inner_key, inner in value.items()}

      if isinstance(value, dict):
         carries_item_text = "text" in value and "rich_text" in value
         walked = {
            inner_key: self.walk(inner, inner_key)
            for inner_key, inner in value.items()
            if not (carries_item_text and inner_key in TEXT_KEYS)
         }

         if carries_item_text:
            walked["text"], walked["rich_text"] = self.item_text(value)

         return {inner_key: walked[inner_key] for inner_key in value}

      if isinstance(value, list):
         return [self.walk(inner, key) for inner in value]

      if isinstance(value, bool) or value is None:
         return value

      if isinstance(value, int):
         keeps_the_integer = key in KEPT_INTEGER_KEYS or key == "counts_entry"

         return value if keeps_the_integer else 0

      if isinstance(value, float):
         return value - TIME_OFFSET_SECONDS

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
   log_path = LOG_DIR / f"account-fixtures-{stamp}.json"
   log_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
   print(json.dumps(report, indent=2))
   print(f"log written to {log_path}")

   has_a_survivor = bool(survivors)
   checked_nothing = not checked

   return 1 if has_a_survivor or checked_nothing else 0


if __name__ == "__main__":
   sys.exit(main())
