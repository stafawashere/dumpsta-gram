"""Read a query result the upstream preloaded into a page, instead of asking for it.

A browser loading the home page sends no GraphQL request for the first feed page. The server
runs the query while it renders and streams the result into the document, inside one of the
``<script type="application/json" data-sjs>`` tags, as a ``RelayPrefetchedStreamCache``
``next`` call keyed by a preloader id. The result carries the same ``data`` object the
pagination query answers with, so the mapper that reads a pagination page reads this too.

Every script tag of that kind is one JSON object, and the call sits some levels down inside
``ScheduledServerJS`` bootstrap arrays whose nesting is not stable enough to hard code. So the
reader walks each object for the call rather than following a path.

A preloaded result that is missing, or present but not ``complete``, raises
:class:`~dumpstagram.errors.SchemaChanged`. Both measured loads carried one ``next`` call with
``complete`` true. A result streamed across several calls has not been observed, and guessing
how the chunks join would be worse than refusing.

Finding: ``skills/reverse-engineer/knowledge/endpoints/home-timeline-first-page-preloader.md``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from dumpstagram.errors import SchemaChanged

__all__ = [
   "FEED_TIMELINE_PRELOADER",
   "HOME_DOCUMENT_URL",
   "read_iris_device_id",
   "read_preloaded_result",
   "read_profile_id",
]

HOME_DOCUMENT_URL = "https://www.instagram.com/"

FEED_TIMELINE_PRELOADER = "adp_PolarisFeedTimelineRootV2QueryRelayPreloader_"
"""The prefix of the preloader id the first feed page arrives under.

The suffix changes on every load, so only the prefix identifies the query.
"""

STREAM_CACHE = "RelayPrefetchedStreamCache"

_PROFILE_ID = re.compile(r'"page_id":"profilePage_(\d+)","profile_id":"(\d+)"')

_IRIS_DEVICE_ID = re.compile(r'\["IGDMqttWebDeviceID",\[\],\{"clientId":"([0-9a-f-]{36})"\}')

_DATA_SCRIPT = re.compile(r"<script type=\"application/json\"[^>]*data-sjs>(.*?)</script>", re.S)


def _stream_calls(value: Any, found: list[list[Any]]) -> None:
   if isinstance(value, list):
      is_a_stream_call = len(value) >= 4 and value[0] == STREAM_CACHE

      if is_a_stream_call:
         found.append(value)

      for element in value:
         _stream_calls(element, found)

      return

   if isinstance(value, dict):
      for element in value.values():
         _stream_calls(element, found)


def _preloaded_boxes(html: str, preloader_prefix: str) -> list[Any]:
   boxes: list[Any] = []

   for script_text in _DATA_SCRIPT.findall(html):
      try:
         parsed = json.loads(script_text)
      except ValueError:
         continue

      calls: list[list[Any]] = []
      _stream_calls(parsed, calls)

      for call in calls:
         arguments = call[3]
         has_an_id_and_a_box = isinstance(arguments, list) and len(arguments) >= 2

         if not has_an_id_and_a_box:
            continue

         preloader_id = arguments[0]
         is_the_wanted_query = isinstance(preloader_id, str) and preloader_id.startswith(
            preloader_prefix
         )

         if is_the_wanted_query:
            boxes.append(arguments[1])

   return boxes


def read_preloaded_result(html: str, preloader_prefix: str) -> dict[str, Any]:
   """The ``result`` object the page preloaded under ``preloader_prefix``.

   Raises :class:`~dumpstagram.errors.SchemaChanged` when the document holds no such result,
   holds more than one, or holds one the upstream has not marked complete.
   """

   boxes = _preloaded_boxes(html, preloader_prefix)

   if not boxes:
      raise SchemaChanged(
         f"the document carries no preloaded result for {preloader_prefix}", path=preloader_prefix
      )

   if len(boxes) > 1:
      raise SchemaChanged(
         f"the document carries {len(boxes)} preloaded chunks for {preloader_prefix}, and "
         "joining streamed chunks has never been observed",
         path=preloader_prefix,
      )

   box = boxes[0].get("__bbox") if isinstance(boxes[0], dict) else None
   path = f"{preloader_prefix}.__bbox"

   if not isinstance(box, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

   if box.get("complete") is not True:
      raise SchemaChanged(f"{path}.complete is not true", path=f"{path}.complete")

   result = box.get("result")

   if not isinstance(result, dict):
      raise SchemaChanged(f"{path}.result is not an object", path=f"{path}.result")

   return result


def read_profile_id(html: str) -> str | None:
   """The account id a profile page document is about, or ``None`` when it is about no one.

   Both measured profile documents carried it twice as ``"profile_id"``, right after a
   ``"page_id"`` of ``profilePage_`` and the same digits. The pair is matched rather than the
   key alone, so an id belonging to some other part of the page cannot be read by accident,
   and two pairs that disagree raise rather than one being picked.

   A document for a username nobody holds came back on 2026-09-23 as HTTP 200 with page tokens
   and no pair at all, which is what ``None`` stands for.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/profile-page-document.md``.
   """

   account_ids = set()

   for page_digits, profile_id in _PROFILE_ID.findall(html):
      if page_digits != profile_id:
         raise SchemaChanged(
            "a profile document names one account in page_id and another in profile_id",
            path="profile_id",
         )

      account_ids.add(profile_id)

   if len(account_ids) > 1:
      raise SchemaChanged("a profile document names more than one account", path="profile_id")

   return account_ids.pop() if account_ids else None


def read_iris_device_id(html: str) -> str | None:
   """The ``clientId`` of ``IGDMqttWebDeviceID`` in a page document, or ``None``.

   The badge count and chat tabs queries a page load sends are keyed on it. It is a uuid4 that
   differed on every captured load, so it belongs to one document and is never stored.
   ``None`` means the document stopped carrying it, and the caller leaves out the queries that
   need it rather than sending a value no page issued.

   Findings: ``page-load-direct-badge-count`` and ``page-load-chat-tabs-jewel``.
   """

   match = _IRIS_DEVICE_ID.search(html)

   return match.group(1) if match is not None else None
