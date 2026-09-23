"""Where the CLI is allowed to read cookie material from.

Two sources, both deliberate. The process environment, and a file of `key=value` lines. A
command line is not one of them: `argv` is readable by every process on the machine through
`ps`, it lands in shell history, and a `sessionid` is a full account takeover token with no
second factor. A gate asserts the parser defines no option that takes one.

This is the adoption path ADR-0008 describes, and it populates the same `Session` a login
would populate later.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from dumpstagram.errors import AuthenticationFailed
from dumpstagram.session import Session

__all__ = ["REQUIRED_KEYS", "read_cookie_file", "session_from"]

REQUIRED_KEYS = ("IG_SESSIONID", "IG_DS_USER_ID", "IG_CSRFTOKEN")
OPTIONAL_COOKIE_KEYS: Mapping[str, str] = {"IG_MID": "mid"}
"""Cookies the measured browser request carried that are not required to construct a session.

`mid` is sent when it is available because the request builders reproduce a full browser
request, and a minimal request is a fingerprint.
"""

FR_KEY = "IG_FR"
"""The `fr` value from the browser's `localStorage`, optional and never a cookie.

Copied beside the cookies so the first page load sends what the browser last stored, which is
the branch of the cookie sync every capture recorded. Without it the session starts with none.
"""


def read_cookie_file(path: Path) -> dict[str, str]:
   """Parse a file of `KEY=value` lines, ignoring blanks and `#` comments.

   The same shape a shell `.env` file has, so material already sitting in one works without
   being reformatted. Surrounding quotes are stripped because a shell would have stripped
   them.
   """

   values: dict[str, str] = {}

   for raw_line in path.read_text(encoding="utf-8").splitlines():
      line = raw_line.strip()

      is_comment = line.startswith("#")
      has_assignment = "=" in line

      if line and not is_comment and has_assignment:
         key, _, value = line.partition("=")
         values[key.strip()] = value.strip().strip('"').strip("'")

   return values


def session_from(source: Mapping[str, str]) -> Session:
   """Build a `Session` out of ``source``, naming every missing key at once.

   Naming all of them matters: reporting the first one turns pasting three cookies into three
   separate runs, and a run that fails halfway has already written a file.
   """

   missing = [key for key in REQUIRED_KEYS if not source.get(key)]

   if missing:
      raise AuthenticationFailed(f"missing cookie material: {', '.join(missing)}")

   extra_cookies = {
      cookie_name: source[key]
      for key, cookie_name in OPTIONAL_COOKIE_KEYS.items()
      if source.get(key)
   }

   return Session(
      sessionid=source["IG_SESSIONID"],
      ds_user_id=source["IG_DS_USER_ID"],
      csrftoken=source["IG_CSRFTOKEN"],
      extra_cookies=extra_cookies,
      fr=source.get(FR_KEY) or None,
   )
