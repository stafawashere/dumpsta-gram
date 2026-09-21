"""The one place a response becomes a success or a failure.

The transport has no status-code branch, because every observed failure on this upstream
arrives as HTTP 200 carrying an error envelope. Classification therefore reads the body, and
:func:`classify` is the only function allowed to decide the outcome of a request.

Checkpoint detection is ordered rather than thorough, and the order is the whole point. The
response URL and any ``Location`` header are scanned first, because user content cannot appear
there. The body is scanned only once the envelope checks have already established that it is
not a successful data payload, because a real checkpoint never arrives inside one. The prior
project scanned the first 4000 bytes of every body, and a single serialised message was about
4734 bytes, so its scan window was user content. A message quoting ``/challenge/`` would have
reported a challenge that never happened, and since a checkpoint is never retried, every
resume would have aborted at the same page.
"""

from __future__ import annotations

import json
from typing import Any

from dumpstagram._private.transport import Response
from dumpstagram.errors import CheckpointRequired, SchemaChanged, UpstreamRejected

__all__ = ["classify", "classify_checkpoint_only"]

_JSONP_PREFIX = "for (;;);"

_HTML_PREFIXES = ("<!doctype", "<html")

_CHECKPOINT_URL_MARKERS = ("/challenge/", "/checkpoint/")

_CHECKPOINT_BODY_MARKERS = (
   "challenge_required",
   "checkpoint_required",
   "/challenge/",
   "/checkpoint/",
)


def classify(response: Response) -> Any:
   """Return the parsed payload, or raise the error the response actually describes.

   The status code is never read. A 500 carrying a valid payload is a success, and a 200
   carrying an envelope is a failure.
   """
   _raise_if_the_location_says_checkpoint(response)

   raw = response.text
   body = raw[len(_JSONP_PREFIX) :] if raw.startswith(_JSONP_PREFIX) else raw
   stripped = body.lstrip()

   is_app_shell = stripped[:20].lower().startswith(_HTML_PREFIXES)
   if is_app_shell:
      _raise_if_the_body_says_checkpoint(stripped)
      raise UpstreamRejected(
         "upstream returned the HTML application shell instead of a payload, "
         "which is what a missing content-type header produces",
         code="html_app_shell",
      )

   try:
      parsed = json.loads(body)
   except json.JSONDecodeError as exc:
      raise SchemaChanged(
         "response was expected to be JSON and could not be parsed", path="<body>"
      ) from exc

   if not isinstance(parsed, dict):
      return parsed

   envelope_code = _envelope_code(parsed)
   if envelope_code is None:
      return parsed

   _raise_if_the_body_says_checkpoint(body)

   raise UpstreamRejected("upstream rejected the request", code=envelope_code)


def classify_checkpoint_only(response: Response) -> None:
   """Raise when the response is a challenge, and say nothing about anything else.

   The bootstrap page is HTML by design, so it cannot go through :func:`classify`, which
   treats HTML as the application shell. Without this check a challenge redirect reaches the
   token scraper, comes back with no ``fb_dtsg``, and is reported as bad credentials. A
   challenge and a dead session need different things from the user.
   """
   _raise_if_the_location_says_checkpoint(response)


def _envelope_code(parsed: dict[str, Any]) -> str | None:
   """Return the upstream code when the payload carries an error envelope.

   Three markers were observed: a top-level ``errors`` array, an ``error`` field, and an
   ``errorSummary`` field. A falsy ``error`` field is not an envelope, because the upstream
   sends ``"error": null`` beside a valid payload.
   """
   errors = parsed.get("errors")
   if isinstance(errors, list) and errors:
      first = errors[0]
      code = first.get("code") if isinstance(first, dict) else None

      return str(code) if code is not None else "errors"

   error_field = parsed.get("error")
   if error_field:
      return str(error_field)

   error_summary = parsed.get("errorSummary")
   if error_summary:
      return "errorSummary"

   return None


def _raise_if_the_location_says_checkpoint(response: Response) -> None:
   """Scan the places a checkpoint announces itself and user content cannot reach."""
   candidates = [response.final_url, *response.history_urls]

   location = response.headers.get("location")
   if location is not None:
      candidates.append(location)

   for candidate in candidates:
      lowered = candidate.lower()
      for marker in _CHECKPOINT_URL_MARKERS:
         if marker in lowered:
            raise CheckpointRequired(
               "the account is in a challenge or checkpoint",
               required_action="open Instagram in a browser and clear the challenge",
            )


def _raise_if_the_body_says_checkpoint(body: str) -> None:
   """Scan the body, which is only reachable once the body is known not to be a payload."""
   lowered = body.lower()

   for marker in _CHECKPOINT_BODY_MARKERS:
      if marker in lowered:
         raise CheckpointRequired(
            "the account is in a challenge or checkpoint",
            required_action="open Instagram in a browser and clear the challenge",
         )
