"""Read only. Ran 2026-09-27, 3 requests. Three requests, none conditional.

E2 batch 11c, the first engine replay of the blocked accounts list, finding
``read-the-blocked-accounts-list``, a hypothesis the browser captured three times in run
``run-2026-09-27-135628``. The settings page ``/accounts/blocked_accounts/`` loads the list in two
Bloks fetches, and this probe sends both, as the page sent them on load:

   1  the inbox document, for fresh tokens and the Bloks version id (the bootstrap)
   1  the settings screen's Bloks app, ``appid``
      ``com.instagram.portable_settings.privacy.blocked_accounts_v2``, ``type`` app, ``params``
      ``{}``, about 5.6 KB
   1  the list's Bloks action, ``appid``
      ``com.instagram.portable_settings.blocked_accounts.blocked_accounts_reloader``, ``type``
      action, ``params`` ``{"container_id_of_list":<n>,"container_id_of_rows":<n + 1>}``, the
      answer that carries the accounts, about 57 KB

The two container ids are not constants: they differed on each capture (1188780462 and
1602110462), and each time they were the two ``bk.action.i32.Const`` values the app's own answer
passes to ``AsyncActionWithDataManifest`` for the reloader. The probe reads them out of the first
answer the same way, with the engine's Bloks reader, and does not send the action when it cannot
find exactly one such call.

Both requests carry what the page's carried, as the capture recorded them: the comet form
``__d``, ``__user``, ``__a``, ``__req``, ``__hs``, ``dpr``, ``__ccg``, ``__rev``, ``__hsi``,
``__comet_req`` 7, ``fb_dtsg``, ``jazoest``, ``lsd``, ``__spin_r``, ``__spin_b``, ``__spin_t``,
``__crn`` ``comet.igweb.PolarisBlockedAccountsSettingsRoute`` and ``params``, without the fields the
engine has never produced (``__s``, ``__dyn``, ``__csr``, ``__hsdp``, ``__hblp``, ``__sjsp``), the
subset the close friends fetch sent and was answered on, and the header set the page's wire
headers carried, no ``x-`` header among them, with the blocked accounts page as referer. The
page's other requests, the settings side menu query and the route definitions, are not sent.

Whether the reloader action changes anything is not observed. By its name and by the page sending
it on every load with no click, it re-reads the list (INFERENCE); it is the only way the list was
seen to arrive. Nothing else is sent, and no account is blocked or unblocked.

Both answers are kept under the skill's ``var/captures/``, as every E2 probe keeps its bodies,
because the list carries other accounts' usernames. The log records sizes, key names and counts:
how many rows the list's data entry holds and which keys a row carries, never a value.

Run it from ``engine/`` with:

   uv run python probes/e2_blocked_list_replay.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any
from urllib.parse import urlencode

from _e2_support import E2Replay, dig, run_probe

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import ORIGIN
from dumpstagram._private.web.parse.bloks import (
   BloksAtom,
   BloksCall,
   BloksValue,
   read_bloks_script,
)
from dumpstagram._private.web.requests.common import jazoest_for
from dumpstagram.errors import SchemaChanged

KIND = "e2-blocked-list-replay"
PLANNED = 3
CONDITIONAL = 0

BLOKS_FETCH_URL = f"{ORIGIN}/async/wbloks/fetch/"
BLOCKED_PAGE = f"{ORIGIN}/accounts/blocked_accounts/"
BLOCKED_ROUTE = "comet.igweb.PolarisBlockedAccountsSettingsRoute"
SCREEN_APP_ID = "com.instagram.portable_settings.privacy.blocked_accounts_v2"
RELOADER_APP_ID = "com.instagram.portable_settings.blocked_accounts.blocked_accounts_reloader"
RELOADER_KEYS = ("container_id_of_list", "container_id_of_rows")


def build_bloks_request(replay: E2Replay, app_id: str, kind: str, params: str) -> Request:
   session = replay.session
   spin = session.spin
   revision = (spin.revision if spin is not None else None) or ""
   fb_dtsg = session.fb_dtsg or ""
   query = urlencode({"appid": app_id, "type": kind, "__bkv": session.bloks_version_id or ""})
   form = {
      "__d": "www",
      "__user": "0",
      "__a": "1",
      "__req": "1",
      "__hs": session.haste_session or "",
      "dpr": "2",
      "__ccg": "EXCELLENT",
      "__rev": revision,
      "__hsi": session.hsi or "",
      "__comet_req": "7",
      "fb_dtsg": fb_dtsg,
      "jazoest": jazoest_for(fb_dtsg),
      "lsd": session.lsd or "",
      "__spin_r": revision,
      "__spin_b": (spin.branch if spin is not None else None) or "",
      "__spin_t": (spin.timestamp if spin is not None else None) or "",
      "__crn": BLOCKED_ROUTE,
      "params": params,
   }
   headers = {
      "accept": "*/*",
      "accept-language": "en-US,en;q=0.9",
      "content-type": "application/x-www-form-urlencoded",
      "origin": ORIGIN,
      "referer": BLOCKED_PAGE,
      "sec-fetch-dest": "empty",
      "sec-fetch-mode": "cors",
      "sec-fetch-site": "same-origin",
      "user-agent": replay.user_agent,
   }

   return Request(
      method="POST",
      url=f"{BLOKS_FETCH_URL}?{query}",
      headers=headers,
      content=urlencode(form).encode("ascii"),
      follow_redirects=False,
   )


def scripts_in(value: Any) -> list[str]:
   found: list[str] = []

   if isinstance(value, dict):
      for inner in value.values():
         found.extend(scripts_in(inner))
   elif isinstance(value, list):
      for inner in value:
         found.extend(scripts_in(inner))
   elif isinstance(value, str) and value.startswith("("):
      found.append(value)

   return found


def calls_in(value: BloksValue) -> list[BloksCall]:
   if not isinstance(value, BloksCall):
      return []

   found = [value]

   for argument in value.arguments:
      found.extend(calls_in(argument))

   return found


def integer_constant(value: BloksValue) -> int | None:
   is_a_constant = isinstance(value, BloksCall) and value.name in (
      "bk.action.i32.Const",
      "bk.action.i64.Const",
   )

   if not is_a_constant or len(value.arguments) != 1:
      return None

   atom = value.arguments[0]

   return int(atom.text) if isinstance(atom, BloksAtom) and atom.text.isdigit() else None


def reloader_params(screen: Any) -> list[dict[str, int]]:
   """Every params object the screen's scripts pass to the reloader action."""

   found: list[dict[str, int]] = []

   for script in scripts_in(dig(screen, "payload", "layout", "bloks_payload")):
      if RELOADER_APP_ID not in script:
         continue

      try:
         parsed = read_bloks_script(script, "<screen>")
      except SchemaChanged:
         continue

      for call in calls_in(parsed):
         names_the_reloader = (
            call.name == "bk.action.bloks.AsyncActionWithDataManifest"
            and len(call.arguments) >= 2
            and call.arguments[0] == RELOADER_APP_ID
         )
         mapping = call.arguments[1] if names_the_reloader else None
         pair = mapping.arguments if isinstance(mapping, BloksCall) else ()
         keys = pair[0] if len(pair) == 2 else None
         values = pair[1] if len(pair) == 2 else None
         is_the_pair = (
            isinstance(keys, BloksCall)
            and isinstance(values, BloksCall)
            and keys.arguments == RELOADER_KEYS
         )

         if not is_the_pair:
            continue

         numbers = [integer_constant(value) for value in values.arguments]

         if len(numbers) == 2 and all(number is not None for number in numbers):
            found.append(dict(zip(RELOADER_KEYS, numbers, strict=True)))

   return found


def describe_list(answer: Any) -> dict[str, Any]:
   """Counts and key names of every data entry whose script is an array of maps, never a value."""

   entries = dig(answer, "payload", "layout", "bloks_payload", "data") or []
   lists = []

   for entry in entries:
      script = dig(entry, "data", "initial_lispy")

      if not isinstance(script, str):
         continue

      try:
         parsed = read_bloks_script(script, "<list>")
      except SchemaChanged:
         lists.append({"unreadable": True, "chars": len(script)})
         continue

      rows = parsed.arguments if isinstance(parsed, BloksCall) else ()
      maps = [
         row for row in rows if isinstance(row, BloksCall) and row.name == "bk.action.map.Make"
      ]
      key_sets = {
         tuple(key for key in row.arguments[0].arguments if isinstance(key, str))
         for row in maps
         if row.arguments and isinstance(row.arguments[0], BloksCall)
      }
      lists.append(
         {
            "rows": len(maps),
            "row_key_sets": [list(keys) for keys in sorted(key_sets)],
            "chars": len(script),
         }
      )

   return {
      "data_entries": len(entries),
      "lists": [entry for entry in lists if entry.get("rows") or entry.get("unreadable")],
      "tree_roots": sorted(dig(answer, "payload", "layout", "bloks_payload", "tree") or {}),
      "embedded_payloads": len(
         dig(answer, "payload", "layout", "bloks_payload", "embedded_payloads") or []
      ),
   }


async def body(replay: E2Replay) -> None:
   await replay.bootstrap()

   if not replay.session.bloks_version_id:
      replay.record("stopped_because", "the bootstrap carried no Bloks version id")

      return

   screen = await replay.send(
      "blocked accounts screen", build_bloks_request(replay, SCREEN_APP_ID, "app", "{}")
   )
   found = reloader_params(screen)
   replay.record(
      "screen",
      {
         "answered": screen is not None,
         "bytes": len(json.dumps(screen)) if screen is not None else None,
         "reloader_calls": len(found),
         "container_ids_are_consecutive": [
            params["container_id_of_rows"] - params["container_id_of_list"] == 1 for params in found
         ],
      },
   )

   if len(found) != 1:
      replay.record("stopped_because", "the screen did not name exactly one reloader call")

      return

   params = json.dumps(found[0], separators=(",", ":"))
   answer = await replay.send(
      "blocked accounts list", build_bloks_request(replay, RELOADER_APP_ID, "action", params)
   )
   replay.record(
      "list",
      {"answered": answer is not None, **(describe_list(answer) if answer is not None else {})},
   )


def main() -> int:
   return asyncio.run(run_probe(KIND, PLANNED, CONDITIONAL, body))


if __name__ == "__main__":
   sys.exit(main())
