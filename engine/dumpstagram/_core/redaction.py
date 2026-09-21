"""Credential redaction for anything this library turns into text.

Redaction belongs to the formatter rather than to each call site, so a log statement nobody
reviewed cannot leak, and so the same path covers a formatted traceback. A traceback is the
one place a cookie reaches a log with nobody having written a log statement at all.

Matching is by key rather than by registered value. A registry of live secret values would be
module-level mutable state, and it would still miss the case this exists for: a frame that
prints a request body or a header map nobody enumerated.

The cost of that choice is stated plainly. A value that appears without its key, or in a
transformed form such as percent-encoded or truncated, is not matched. The credential absence
scan in the gate inventory covers the plain case and not that one.
"""

from __future__ import annotations

import logging
import re

__all__ = [
   "REDACTED",
   "RedactingFormatter",
   "redact",
]

REDACTED = "<redacted>"

SECRET_KEYS = (
   "sessionid",
   "csrftoken",
   "x-csrftoken",
   "fb_dtsg",
   "lsd",
   "jazoest",
   "authorization",
   "password",
   "ig_did",
   "datr",
   "rur",
)
"""The key names whose values never appear in text this library produces.

``ds_user_id`` is deliberately absent. It is an account identifier rather than a credential,
it already appears in ``Session.__repr__``, and a log that cannot name the account is a log
that cannot answer which account was rate limited.
"""

_KEY_ALTERNATION = "|".join(re.escape(key) for key in SECRET_KEYS)

_ASSIGNMENT = re.compile(
   rf"(?i)(?<![\w-])({_KEY_ALTERNATION})(\s*[=:]\s*)(['\"]?)([^\s;,&'\"]+)",
)

_COOKIE_HEADER = re.compile(r"(?i)(?<![\w-])(cookie)(\s*[=:]\s*)([^\n]+)")


def redact(text: str) -> str:
   """Replace every recognised credential value in ``text`` with :data:`REDACTED`.

   A whole cookie header is replaced rather than parsed, because the safe failure here is
   losing a diagnostic and the unsafe one is keeping a session token.
   """

   without_cookie_headers = _COOKIE_HEADER.sub(rf"\1\2{REDACTED}", text)

   return _ASSIGNMENT.sub(rf"\1\2\3{REDACTED}", without_cookie_headers)


class RedactingFormatter(logging.Formatter):
   """A formatter that redacts the fully rendered record, traceback text included.

   The library attaches no handler and so installs this nowhere. It is offered to a host that
   wants the guarantee, and it is what the library's own code uses whenever it formats a
   traceback itself.
   """

   def format(self, record: logging.LogRecord) -> str:
      return redact(super().format(record))
