"""Gates for credential redaction in formatted text.

The defect this layer produces is silent and permanent: a cookie written into a log file or a
crash report, where deleting it later does not unwrite it. Each absence assertion below is
paired with a positive control, because a redaction test that passes on text containing no
secret proves nothing at all.
"""

from __future__ import annotations

import logging

from dumpstagram._core.redaction import REDACTED, RedactingFormatter, redact

SECRET = "71234567%3AabcdefGHIJKL%3A17"


def test_redacts_a_session_cookie_assignment() -> None:
   """Catches the plain case, a cookie printed as `key=value` in a repr or a request body."""

   redacted = redact(f"sessionid={SECRET}; ds_user_id=71234567")

   assert SECRET not in redacted
   assert REDACTED in redacted


def test_the_scan_finds_the_value_when_redaction_is_not_applied() -> None:
   """Positive control. Without it, every absence assertion here is satisfied by empty text."""

   assert SECRET in f"sessionid={SECRET}; ds_user_id=71234567"


def test_redacts_a_whole_cookie_header() -> None:
   """Catches a header line that carries several credentials the key scan does not enumerate."""

   redacted = redact(f"cookie: sessionid={SECRET}; csrftoken=abc123; unknown_future_token=xyz")

   assert SECRET not in redacted
   assert "abc123" not in redacted
   assert "xyz" not in redacted


def test_keeps_the_account_identifier() -> None:
   """`ds_user_id` is an identifier, not a credential, and a log that cannot name the account
   cannot answer which account was rate limited."""

   assert "71234567" in redact("ds_user_id=71234567")


def test_redacts_the_token_names_the_request_builder_sends() -> None:
   """Catches a bootstrap token reaching a log, which is the second credential class here."""

   redacted = redact("fb_dtsg=NAcPtoken1 lsd=AVqlsdvalue x-csrftoken: csrfvalue")

   assert "NAcPtoken1" not in redacted
   assert "AVqlsdvalue" not in redacted
   assert "csrfvalue" not in redacted


def test_redacts_a_token_under_a_quoted_key() -> None:
   """Catches the JSON form, where a closing quote sits between the key and the colon.

   A session file, a dict repr and a JSON body all print keys that way, and the pattern once
   required the separator straight after the key.
   """

   json_text = '{"fb_dtsg": "NAcPtoken1", "lsd":"AVqlsdvalue"}'
   dict_repr = "{'sessionid': '" + SECRET + "'}"

   assert "NAcPtoken1" in json_text, "positive control: the value is in the input"
   assert SECRET in dict_repr, "positive control: the value is in the input"
   assert "NAcPtoken1" not in redact(json_text)
   assert "AVqlsdvalue" not in redact(json_text)
   assert SECRET not in redact(dict_repr)


def test_redacts_the_fr_value() -> None:
   """Catches `fr` missing from the secret keys, since it rides with the cookie sync."""

   fr_value = "1AbCdEfGhIjKlMnOp.frvalue"
   assignment = f"fr={fr_value}"
   json_text = f'{{"fr": "{fr_value}"}}'

   assert fr_value in assignment, "positive control: the value is in the input"
   assert fr_value in json_text, "positive control: the value is in the input"
   assert fr_value not in redact(assignment)
   assert fr_value not in redact(json_text)


def test_the_formatter_redacts_a_formatted_traceback() -> None:
   """Catches the case nobody writes a log statement for.

   An exception message built from a request body reaches the log through the traceback the
   handler renders, not through the call site, so redaction has to sit in the formatter.
   """

   formatter = RedactingFormatter("%(message)s")

   try:
      raise ValueError(f"upstream rejected the request with sessionid={SECRET}")
   except ValueError as failure:
      record = logging.LogRecord(
         name="dumpstagram",
         level=logging.ERROR,
         pathname=__file__,
         lineno=1,
         msg="request failed",
         args=(),
         exc_info=(type(failure), failure, failure.__traceback__),
      )

   formatted = formatter.format(record)

   assert SECRET not in formatted
   assert REDACTED in formatted


def test_a_plain_formatter_leaks_the_same_traceback() -> None:
   """Positive control for the formatter gate, proving the traceback carried the value."""

   formatter = logging.Formatter("%(message)s")

   try:
      raise ValueError(f"upstream rejected the request with sessionid={SECRET}")
   except ValueError as failure:
      record = logging.LogRecord(
         name="dumpstagram",
         level=logging.ERROR,
         pathname=__file__,
         lineno=1,
         msg="request failed",
         args=(),
         exc_info=(type(failure), failure, failure.__traceback__),
      )

   assert SECRET in formatter.format(record)
