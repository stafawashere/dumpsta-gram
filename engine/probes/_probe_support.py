"""Shared plumbing for the probes: `.env` loading, log writing, and page counting.

Not a library module and not importable from the package. It sits here because the probes
under Step 9 need the same three helpers `end_to_end_read.py` already had, and a third copy
of them is a third place for the `.env` path bug of 2026-09-21 to hide.

`end_to_end_read.py` keeps its own copies deliberately. It is the verified Step 8 evidence,
its last run is quoted in the project profile, and rewriting it to import from here would
cost two live requests to re-establish a claim that is already established.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ENGINE_ROOT / "logs"
ENV_PATH = ENGINE_ROOT.parent / ".env"

SESSION_PATH = ENGINE_ROOT / "state" / "session.json"
"""Where the adopted session is persisted between the two Step 9 probes.

`state/` is gitignored at the repository root, which matters: the file holds a `sessionid`,
and a `sessionid` is a full account takeover token with no second factor.
"""

THREAD_FBID = "17945046917948992"
"""The thread the measured runs used, overridable with `IG_THREAD_FBID`.

The thread's `fbid`, which is one of the three ids the same thread has. The other two return
an empty page rather than an error.
"""

REQUIRED_CREDENTIAL_KEYS = ("IG_SESSIONID", "IG_DS_USER_ID", "IG_CSRFTOKEN")


def load_env(path: Path = ENV_PATH) -> dict[str, str]:
   values: dict[str, str] = {}

   for raw_line in path.read_text(encoding="utf-8").splitlines():
      line = raw_line.strip()

      is_comment = line.startswith("#")
      has_assignment = "=" in line

      if line and not is_comment and has_assignment:
         key, _, value = line.partition("=")
         values[key.strip()] = value.strip().strip('"').strip("'")

   return values


def write_log(kind: str, payload: dict[str, object]) -> Path:
   LOG_DIR.mkdir(parents=True, exist_ok=True)
   stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
   path = LOG_DIR / f"{kind}-{stamp}.json"

   path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")

   return path


def report_run(kind: str, report: dict[str, object]) -> Path:
   log_path = write_log(kind, report)

   print(json.dumps(report, indent=2, default=str))
   print(f"log written to {log_path}")

   return log_path


def describe_page(parsed: object) -> dict[str, object]:
   """Count what came back without recording any of it.

   The traversal is written out rather than imported, because no parser exists yet and Step 8
   deliberately did not add one. A path that stops resolving is reported as absent rather than
   raising, so the probe still produces a log.
   """

   if not isinstance(parsed, dict):
      return {"payload_is_an_object": False}

   data = parsed.get("data")
   thread_field = data.get("fetch__SlideThread") if isinstance(data, dict) else None
   thread = thread_field.get("as_ig_direct_thread") if isinstance(thread_field, dict) else None
   messages = thread.get("slide_messages") if isinstance(thread, dict) else None

   if not isinstance(messages, dict):
      return {
         "payload_is_an_object": True,
         "top_level_keys": sorted(parsed.keys()),
         "canonical_path_present": False,
      }

   edges = messages.get("edges") or []
   page_info = messages.get("page_info") or {}
   end_cursor = page_info.get("end_cursor")

   return {
      "payload_is_an_object": True,
      "top_level_keys": sorted(parsed.keys()),
      "canonical_path_present": True,
      "edge_count": len(edges),
      "has_next_page": page_info.get("has_next_page"),
      "end_cursor_length": len(end_cursor) if end_cursor else None,
   }
