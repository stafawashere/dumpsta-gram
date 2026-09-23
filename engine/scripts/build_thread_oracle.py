"""Turn a raw thread capture into the local, pseudonymised test oracle.

Two inputs, both local and both outside git. The raw capture written by
``probes/capture_thread_oracle.py`` under ``engine/exports/``, and the export the prior
project's ``ghost`` tool made of the same thread on 2026-09-21. The second one is what makes
this an oracle rather than a recording: a different implementation read the same connection a
day earlier, so a message this library drops, duplicates or misdates disagrees with something
it did not produce.

Two outputs under ``tests/fixtures/thread_oracle/``, which is gitignored: pseudonymised or
not, the fixtures are the shape of a private conversation with a third party. ``pages.json.gz``
holds every raw page in the order it was read, with the cursor it was requested with.
``independent_export.json`` holds the ghost export reduced to four fields per message, inside
the window ghost covered.

Nothing leaves this script as it arrived except the shape. The rules are by key, and a key
this script has no rule for loses its value rather than keeping it:

- enum-like values the mapper and the tests read (`__typename`, `content_type` and the like)
  are kept verbatim, and so is a reaction's emoji
- every identifier is replaced by a synthetic one, consistently across both inputs, so a
  reply still points at the message it replies to and a sender is still the same sender
- every timestamp is shifted by one constant, so order and spacing survive and the date does
  not
- every cursor becomes an opaque synthetic token, consistently between an edge and a page
- the two token fields the upstream echoes into every page are replaced outright
- every other string becomes a placeholder of the same length, an empty string stays empty,
  and a URL becomes a URL on a reserved domain

Run from ``engine/`` with ``uv run python scripts/build_thread_oracle.py``, or pass
``--capture`` and ``--independent`` to point at other inputs. Writes a report to
``engine/logs/``.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ENGINE = Path(__file__).resolve().parents[1]
LOG_DIR = ENGINE / "logs"
FIXTURE_DIR = ENGINE / "tests" / "fixtures" / "thread_oracle"
EXPORT_ROOT = ENGINE / "exports"

GHOST_EXPORT = Path(
   "/Users/mahfujm/Documents/dumpsta-js/ghost/exports/"
   "ghost-17945046917948992-2026-09-21-00-24-36/scrape.json"
)

SHIFTED_EPOCH_MS = 1_577_836_800_000
"""2020-01-01T00:00:00Z. The oldest message in the capture lands here."""

VERBATIM_KEYS = frozenset(
   {
      "__typename",
      "__isSlideMessageContent",
      "__isSlideMessageRavenContent",
      "__isSlideMessagingMediaAttachment",
      "content_type",
      "preview_image_decoration_type",
      "preview_layout_type",
      "title_icon_type",
      "verified_type",
      "reaction",
   }
)

IDENTIFIER_KEYS = frozenset(
   {
      "id",
      "igid",
      "message_id",
      "replied_to_message_id",
      "sender_fbid",
      "sender_igid",
      "thread_fbid",
      "offline_threading_id",
      "attachment_fbid",
      "target_id",
      "audio_asset_id",
      "media_content_fbid",
      "interop_messaging_user_fbid",
   }
)

TIMESTAMP_KEYS = frozenset(
   {
      "timestamp_ms",
      "expiration_timestamp_ms",
      "view_expiration_timestamp_ms",
      "request_start_time_ms",
      "time_at_flush_ms",
   }
)

CURSOR_KEYS = frozenset({"cursor", "end_cursor", "start_cursor"})

TOKEN_KEYS = frozenset({"dtsg_token", "__token"})

PLACEHOLDER_TEXT = "lorem ipsum dolor sit amet "


class Pseudonymiser:
   def __init__(self, offset_ms: int) -> None:
      self.offset_ms = offset_ms
      self.identifiers: dict[str, str] = {}
      self.cursors: dict[str, str] = {}
      self.urls = 0

   def identifier(self, real: str) -> str:
      known = self.identifiers.get(real)

      if known is not None:
         return known

      serial = len(self.identifiers) + 1
      is_message_id = real.startswith("mid.")

      if is_message_id:
         synthetic = f"mid.$oracle{serial:08d}"
      else:
         width = max(len(real), 9)
         synthetic = str(10 ** (width - 1) + serial)

      self.identifiers[real] = synthetic

      return synthetic

   def cursor(self, real: str) -> str:
      known = self.cursors.get(real)

      if known is None:
         known = f"oracle-cursor-{len(self.cursors) + 1:06d}"
         self.cursors[real] = known

      return known

   def timestamp(self, real: Any) -> Any:
      if isinstance(real, bool) or real is None:
         return real

      if isinstance(real, int):
         return real - self.offset_ms

      is_digit_string = isinstance(real, str) and real.isdigit()

      if is_digit_string:
         return str(int(real) - self.offset_ms)

      return self.placeholder(real)

   def placeholder(self, real: Any) -> Any:
      if not isinstance(real, str) or real == "":
         return real

      if real.startswith(("http://", "https://")):
         self.urls += 1

         return f"https://oracle.invalid/{self.urls}"

      repeats = len(real) // len(PLACEHOLDER_TEXT) + 1

      return (PLACEHOLDER_TEXT * repeats)[: len(real)]

   def value(self, key: str, real: Any) -> Any:
      if isinstance(real, dict):
         return {child: self.value(child, value) for child, value in real.items()}

      if isinstance(real, list):
         return [self.value(key, element) for element in real]

      is_scalar_non_string = not isinstance(real, str)

      if key in TIMESTAMP_KEYS:
         return self.timestamp(real)

      if is_scalar_non_string:
         return real

      if key in VERBATIM_KEYS:
         return real

      if key in TOKEN_KEYS:
         return "redacted"

      if key in CURSOR_KEYS:
         return self.cursor(real)

      looks_like_an_identifier = real.isdigit() or real.startswith("mid.")

      if key in IDENTIFIER_KEYS and looks_like_an_identifier:
         return self.identifier(real)

      return self.placeholder(real)


def strings_in(value: Any, key: str = "") -> set[str]:
   """Every string that is not an enum-like value, which is what the leak scan looks for."""

   if isinstance(value, dict):
      return set().union(*(strings_in(child, name) for name, child in value.items()))

   if isinstance(value, list):
      return set().union(*(strings_in(element, key) for element in value))

   is_long_enough_to_mean_something = isinstance(value, str) and len(value) >= 4

   if is_long_enough_to_mean_something and key not in VERBATIM_KEYS:
      return {value}

   return set()


def credential_values(raw_pages: list[Any]) -> list[str]:
   """The session's own secrets, plus the token the upstream echoed into every page.

   The echoed token is not the one the stored session holds, so without it the scan would be
   looking for four values the raw pages never contained and its control would read zero.
   """

   echoed: set[str] = set()

   for page in raw_pages:
      echoed.add(page["extensions"]["dtsg_token"])
      echoed.add(page["data"]["fetch__SlideThread"]["__token"])

   session_path = ENGINE / "state" / "session.json"
   stored = json.loads(session_path.read_text(encoding="utf-8")) if session_path.exists() else {}
   names = ("sessionid", "csrftoken", "fb_dtsg", "lsd")
   from_session = {stored[name] for name in names if stored.get(name)}

   return sorted(value for value in echoed | from_session if value)


def leak_scan(
   real: set[str], credentials: list[str], written: Any, raw_text: str
) -> dict[str, int]:
   """Count real values in the output, beside the same count over the raw input.

   The raw count is the positive control. A scan that finds nothing in the output only means
   something when the same scan finds the same values in the input it was built from.
   """

   written_strings = strings_in(written)
   written_text = json.dumps(written)

   return {
      "real_values_scanned_for": len(real),
      "real_values_found_in_output": len(real & written_strings),
      "credentials_scanned_for": len(credentials),
      "credentials_found_in_output": sum(1 for value in credentials if value in written_text),
      "control_credentials_found_in_raw": sum(1 for value in credentials if value in raw_text),
      "control_real_values_found_in_raw": len(real & strings_in(json.loads(raw_text))),
   }


def latest_capture() -> Path:
   captures = sorted(EXPORT_ROOT.glob("thread-oracle-*"))

   if not captures:
      raise SystemExit(f"no capture under {EXPORT_ROOT}")

   return captures[-1]


def connection_of(payload: dict[str, Any]) -> dict[str, Any]:
   thread = payload["data"]["fetch__SlideThread"]["as_ig_direct_thread"]
   connection: dict[str, Any] = thread["slide_messages"]

   return connection


def main() -> int:
   parser = argparse.ArgumentParser()
   parser.add_argument("--capture", type=Path, default=None)
   parser.add_argument("--independent", type=Path, default=GHOST_EXPORT)
   arguments = parser.parse_args()

   capture_dir = (arguments.capture or latest_capture()).resolve()
   manifest = json.loads((capture_dir / "manifest.json").read_text(encoding="utf-8"))

   if not manifest["finished"]:
      raise SystemExit("the capture did not reach has_next_page false, refusing to build")

   raw_pages = [
      json.loads((capture_dir / "pages" / page["file"]).read_text(encoding="utf-8"))
      for page in manifest["pages"]
   ]

   captured_nodes = [edge["node"] for page in raw_pages for edge in connection_of(page)["edges"]]
   oldest_ms = min(int(node["timestamp_ms"]) for node in captured_nodes)

   pseudonymiser = Pseudonymiser(offset_ms=oldest_ms - SHIFTED_EPOCH_MS)

   recorded_pages = []

   for page, raw in zip(manifest["pages"], raw_pages, strict=True):
      requested_after = page["after"]

      recorded_pages.append(
         {
            "after": None if requested_after is None else pseudonymiser.cursor(requested_after),
            "payload": pseudonymiser.value("", raw),
         }
      )

   ghost = json.loads(arguments.independent.read_text(encoding="utf-8"))
   ghost_records = [message["storeMessage"] for message in ghost["messages"]]
   window_low = min(int(record["timestamp_ms"]) for record in ghost_records)
   window_high = max(int(record["timestamp_ms"]) for record in ghost_records)

   independent = [
      {
         "id": pseudonymiser.identifier(record["id"]),
         "timestamp_ms": pseudonymiser.timestamp(record["timestamp_ms"]),
         "sender_fbid": pseudonymiser.identifier(record["sender_fbid"]),
         "content_type": record["content_type"],
      }
      for record in ghost_records
   ]

   thread_fbid = pseudonymiser.identifier(captured_nodes[0]["thread_fbid"])

   captured_ids = {node["id"] for node in captured_nodes}
   captured_in_window = {
      node["id"]
      for node in captured_nodes
      if window_low <= int(node["timestamp_ms"]) <= window_high
   }
   ghost_ids = {record["id"] for record in ghost_records}
   absent_from_capture = sorted(pseudonymiser.identifier(real) for real in ghost_ids - captured_ids)

   FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

   pages_path = FIXTURE_DIR / "pages.json.gz"
   pages_bytes = json.dumps(recorded_pages, separators=(",", ":"), sort_keys=True).encode()

   with gzip.GzipFile(pages_path, "wb", mtime=0) as compressed:
      compressed.write(pages_bytes)

   independent_path = FIXTURE_DIR / "independent_export.json"
   independent_path.write_text(
      json.dumps(
         {
            "source": "ghost 2026-09-21, a separate Node implementation of the same read",
            "thread_fbid": thread_fbid,
            "window_ms": [
               pseudonymiser.timestamp(window_low),
               pseudonymiser.timestamp(window_high),
            ],
            "absent_from_capture": absent_from_capture,
            "absent_from_capture_note": (
               "Messages the independent export holds and the raw capture pages do not. The "
               "upstream did not send them on 2026-09-22, so no mapper could have read them. "
               "INFERENCE: unsent between the two reads. Computed from the raw pages, never "
               "from the mapper."
            ),
            "messages": sorted(independent, key=lambda record: record["timestamp_ms"]),
         },
         indent=1,
      )
      + "\n",
      encoding="utf-8",
   )

   real_values = strings_in(raw_pages) | strings_in(ghost_records)
   written = {"pages": recorded_pages, "independent": independent}
   leaks = leak_scan(real_values, credential_values(raw_pages), written, json.dumps(raw_pages))

   leaked = leaks["real_values_found_in_output"] + leaks["credentials_found_in_output"]

   if leaked:
      pages_path.unlink()
      independent_path.unlink()

   report: dict[str, Any] = {
      "capture_dir": str(capture_dir),
      "independent_export": str(arguments.independent),
      "pages": len(recorded_pages),
      "captured_messages": len(captured_nodes),
      "captured_distinct": len(captured_ids),
      "captured_in_window": len(captured_in_window),
      "independent_messages": len(ghost_records),
      "independent_distinct": len(ghost_ids),
      "only_in_capture_within_window": len(captured_in_window - ghost_ids),
      "only_in_independent": len(ghost_ids - captured_ids),
      "identifiers_mapped": len(pseudonymiser.identifiers),
      "cursors_mapped": len(pseudonymiser.cursors),
      "urls_replaced": pseudonymiser.urls,
      "pages_bytes_uncompressed": len(pages_bytes),
      "pages_bytes_compressed": len(gzip.compress(pages_bytes, mtime=0)),
      "leak_scan": leaks,
      "fixtures_written": not leaked,
   }

   LOG_DIR.mkdir(parents=True, exist_ok=True)
   stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
   log_path = LOG_DIR / f"thread-oracle-build-{stamp}.json"
   log_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

   print(json.dumps(report, indent=2))
   print(f"log written to {log_path}")

   return 1 if leaked else 0


if __name__ == "__main__":
   sys.exit(main())
