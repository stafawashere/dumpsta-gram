"""Read only. At most ten Instagram API requests and two CDN fetches, twelve in all.

``--stage post-detail`` spends three API requests and no CDN fetch instead: the first feed page,
then the first video and the first carousel on it read again by shortcode through the post query,
recording the same key union for the post query's item, so the post read's model is extended only
as far as its own payload carries the same keys. It writes ``post_detail_video_item.json`` and
``post_detail_carousel_item.json`` beside the others under ``--write-fixtures``.

The feed page count is at most six with ``--until video-child`` and stops at the first page
holding both kinds otherwise, and ``--fetch image`` spends one CDN fetch rather than two.

E1 item 6 of the web parity plan, the complete media model. The model carried image crops only,
because the one measured feed page held photos and photo carousels and nothing else. This probe
reads home timeline pages through the pagination query until it has seen at least one video
item and one carousel, or until eight feed pages have been read, and records:

- the key union of every video node, every carousel node and every carousel child, walked to
  depth six, with types, presence and null counts, string and list lengths, the numeric range of
  dimension and duration keys, and the values of enum-like keys only;
- which host family every URL string on those nodes sits on, by its last two labels;
- per video node, what its DASH manifest carries: the root attribute names, the
  ``mediaPresentationDuration`` value, and counts of representations, audio adaptation sets and
  base URLs, never a URL;
- then one CDN fetch of the smallest image rendition of a carousel child with no cookie and no
  header but the user agent, and one CDN fetch of the smallest video rendition with no cookie and
  the header set a download sends (user agent, referer, accept). Each records the status, the
  header names, the content length against the bytes received, the content type and the host.

Nothing else is written: no caption, no username, no full name, no URL. A host name is recorded
because it is where a fetch went, and it is not a URL.

``--write-fixtures`` also writes one video node, one carousel node and, when one was seen, one
carousel holding a video child to ``tests/fixtures/media/``, pseudonymised: every URL becomes a
fixture URL, every id a synthetic one of the same length with equality kept, every other string a
placeholder, and dimensions, durations, counts, flags and enum values kept.

The API reads go through the library's own request builder, classifier and paced sender at the
2850 ms probe spacing, and a checkpoint or a throttle stops the run with nothing retried.

Credentials come from the saved session, which ``adopt_and_save.py`` wrote from the root ``.env``.

Run it from `engine/` with:

   uv run python probes/media_shape.py --write-fixtures
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from _probe_support import ENGINE_ROOT, SESSION_PATH, load_env, report_run

from dumpstagram._core.pacer import Pacer, PacingPolicy
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.tokens import with_token_recovery
from dumpstagram._private.transport import HttpxTransport, Request, Response, Sender, cookies_for
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, INSTAGRAM_HOST, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.requests.feed import build_feed_page_request
from dumpstagram._private.web.requests.media import build_post_request
from dumpstagram.errors import DumpstagramError
from dumpstagram.session import Session

NON_CREDENTIAL_KEYS = ("IG_USER_AGENT", "IG_SESSION_FILE")

API_REQUEST_CAP = 10
FEED_PAGE_CAP = 6
CDN_FETCH_CAP = 2
CDN_BODY_CAP = 40 * 1024 * 1024
PROBE_SPACING = PacingPolicy(floor_seconds=2.5, mean_jitter_seconds=0.35)
CDN_GAP_SECONDS = 2.85

MANIFEST_DURATION = re.compile(r'mediaPresentationDuration="([^"]*)"')
MANIFEST_ROOT = re.compile(r"<MPD\b([^>]*)>")
ATTRIBUTE_NAME = re.compile(r"([A-Za-z_:][\w:.-]*)=")

POST_ITEMS_PATH = ("data", "xdt_api__v1__media__shortcode__web_info", "items")
POST_DETAIL_REQUEST_CAP = 3

CONNECTION_PATH = ("data", "xdt_api__v1__feed__timeline__connection")
FIXTURE_DIR = ENGINE_ROOT / "tests" / "fixtures" / "media"

VIDEO_MEDIA_TYPE = 2
CAROUSEL_MEDIA_TYPE = 8
MAX_DEPTH = 6

QUOTABLE_KEYS = (
   "__typename",
   "media_type",
   "product_type",
   "audio_type",
   "type",
   "audio_asset_start_time_in_ms",
   "clips_creation_entry_point",
)
"""Keys whose values are enumerations rather than someone's content."""

RANGED_KEYS = (
   "width",
   "height",
   "original_width",
   "original_height",
   "video_duration",
   "duration_in_ms",
   "number_of_qualities",
   "carousel_media_count",
   "media_type",
   "type",
   "bandwidth",
   "taken_at",
)
"""Numeric keys whose range is a dimension, a duration or an enumeration, never an id."""

KEPT_FIXTURE_STRINGS = QUOTABLE_KEYS
"""String values a fixture keeps as sent, because they are enumerations."""


class CountingTransport:
   """Counts every API request and refuses one past the cap."""

   def __init__(self, inner: Sender, cap: int) -> None:
      self.inner = inner
      self.cap = cap
      self.sent: list[dict[str, object]] = []

   async def send(self, request: Request) -> Response:
      if len(self.sent) >= self.cap:
         raise RuntimeError(f"refusing API request {len(self.sent) + 1}, the cap is {self.cap}")

      entry: dict[str, object] = {"name": request.headers.get("x-fb-friendly-name", "document")}
      self.sent.append(entry)

      response = await self.inner.send(request)
      entry["status"] = response.status_code
      entry["length"] = len(response.content)

      return response

   async def aclose(self) -> None:
      closer = getattr(self.inner, "aclose", None)

      if closer is not None:
         await closer()


def _shape_of(value: Any) -> str:
   if value is None:
      return "null"

   if isinstance(value, bool):
      return "bool"

   if isinstance(value, int):
      return "int"

   if isinstance(value, float):
      return "float"

   if isinstance(value, str):
      return "str"

   if isinstance(value, list):
      return "list"

   if isinstance(value, dict):
      return "object"

   return type(value).__name__


def _record(report: dict[str, Any], path: str, key: str, value: Any) -> None:
   entry = report.setdefault(
      path,
      {"present_on": 0, "null_on": 0, "types": set(), "values": set()},
   )

   entry["present_on"] += 1
   entry["types"].add(_shape_of(value))

   if value is None:
      entry["null_on"] += 1

      return

   if isinstance(value, str):
      entry.setdefault("str_lengths", set()).add(len(value))

      is_quotable_text = key in QUOTABLE_KEYS and len(value) <= 40

      if is_quotable_text:
         entry["values"].add(value)

   if isinstance(value, list):
      entry.setdefault("list_lengths", set()).add(len(value))

   is_number = isinstance(value, int | float) and not isinstance(value, bool)
   is_ranged_number = is_number and key in RANGED_KEYS

   if is_ranged_number:
      entry.setdefault("numbers", set()).add(value)

   is_quotable_number = is_number and key in QUOTABLE_KEYS and isinstance(value, int)

   if is_quotable_number:
      entry["values"].add(str(value))


def _walk(report: dict[str, Any], node: Any, prefix: str, depth: int) -> None:
   if depth > MAX_DEPTH:
      return

   if isinstance(node, dict):
      for key, value in node.items():
         path = f"{prefix}.{key}" if prefix else key
         _record(report, path, key, value)
         _walk(report, value, path, depth + 1)

      return

   if isinstance(node, list):
      for element in node:
         _walk(report, element, f"{prefix}[]", depth + 1)


def _finalize(report: dict[str, Any]) -> dict[str, Any]:
   finalized: dict[str, Any] = {}

   for path, entry in sorted(report.items()):
      rendered: dict[str, Any] = {
         "present_on": entry["present_on"],
         "null_on": entry["null_on"],
         "types": sorted(entry["types"]),
      }

      if entry["values"]:
         rendered["distinct_values"] = sorted(entry["values"])

      for size_key in ("str_lengths", "list_lengths", "numbers"):
         sizes = entry.get(size_key)

         if sizes:
            rendered[size_key] = [min(sizes), max(sizes)]

      finalized[path] = rendered

   return finalized


def _urls_in(node: Any) -> list[str]:
   found: list[str] = []

   if isinstance(node, dict):
      for value in node.values():
         found.extend(_urls_in(value))

   if isinstance(node, list):
      for element in node:
         found.extend(_urls_in(element))

   is_url = isinstance(node, str) and node.startswith("https://")

   if is_url:
      found.append(node)

   return found


def _host_family(url: str) -> str:
   host = urlsplit(url).hostname or ""

   return ".".join(host.split(".")[-2:])


def _host_families(nodes: list[dict[str, Any]]) -> dict[str, int]:
   counts: dict[str, int] = {}

   for node in nodes:
      for url in _urls_in(node):
         family = _host_family(url)
         counts[family] = counts.get(family, 0) + 1

   return dict(sorted(counts.items()))


def _smallest(candidates: Any) -> dict[str, Any] | None:
   if not isinstance(candidates, list):
      return None

   usable = [
      entry
      for entry in candidates
      if isinstance(entry, dict)
      and isinstance(entry.get("url"), str)
      and isinstance(entry.get("width"), int)
      and isinstance(entry.get("height"), int)
   ]

   if not usable:
      return None

   return min(usable, key=lambda entry: entry["width"] * entry["height"])


async def _cdn_fetch(url: str, headers: dict[str, str], proxy: str | None) -> dict[str, object]:
   """One cookieless GET, redirects not followed, the body counted and dropped."""

   host = urlsplit(url).hostname or ""
   started_at = time.monotonic()
   outcome: dict[str, object] = {
      "host": host,
      "host_family": _host_family(url),
      "request_header_names": sorted(headers),
      "cookies_sent": False,
   }

   async with httpx.AsyncClient(
      follow_redirects=False,
      verify=True,
      proxy=proxy,
      timeout=httpx.Timeout(30.0),
   ) as client:
      async with client.stream("GET", url, headers=headers) as response:
         received = 0

         async for chunk in response.aiter_raw():
            received += len(chunk)

            if received > CDN_BODY_CAP:
               outcome["stopped_at_body_cap"] = True

               break

         declared = response.headers.get("content-length")
         location = response.headers.get("location")

         outcome.update(
            {
               "status": response.status_code,
               "http_version": response.http_version,
               "response_header_names": sorted({name.lower() for name in response.headers}),
               "content_length": int(declared) if declared is not None else None,
               "received_bytes": received,
               "length_matches": declared is not None and int(declared) == received,
               "content_type": response.headers.get("content-type"),
               "content_encoding": response.headers.get("content-encoding"),
               "accept_ranges": response.headers.get("accept-ranges"),
               "set_cookie_present": "set-cookie" in response.headers,
               "redirect_host": urlsplit(location).hostname if location else None,
               "elapsed_ms": int((time.monotonic() - started_at) * 1000),
            }
         )

   return outcome


class Pseudonymiser:
   """Replaces everything identifying in a node while keeping its shape and its numbers."""

   def __init__(self) -> None:
      self.ids: dict[str, str] = {}
      self.url_count = 0

   def fake_digits(self, real: str) -> str:
      if real not in self.ids:
         serial = len(self.ids) + 1
         width = len(real)
         self.ids[real] = str(10 ** (width - 1) + serial) if width > 1 else str(serial % 10)

      return self.ids[real]

   def fake_url(self, key: str, real: str) -> str:
      self.url_count += 1
      path = urlsplit(real).path
      extension = path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else "bin"

      return f"https://scontent.fixture.cdninstagram.com/v/fixture-{self.url_count}.{extension}"

   def string(self, key: str, value: str) -> str:
      if key in KEPT_FIXTURE_STRINGS:
         return value

      if value.startswith("http://") or value.startswith("https://"):
         return self.fake_url(key, value)

      if value.isdigit():
         return self.fake_digits(value)

      parts = value.split("_")
      is_compound_id = len(parts) > 1 and all(part.isdigit() for part in parts)

      if is_compound_id:
         return "_".join(self.fake_digits(part) for part in parts)

      if key == "video_dash_manifest":
         duration = MANIFEST_DURATION.search(value)
         duration_attribute = (
            f' mediaPresentationDuration="{duration.group(1)}"' if duration is not None else ""
         )

         return f'<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static"{duration_attribute}/>'

      if value == "":
         return ""

      return f"fixture {key}"

   def number(self, key: str, value: int) -> int:
      is_kept = key in RANGED_KEYS or abs(value) < 10**6

      if is_kept:
         return value

      return int(self.fake_digits(str(abs(value))))

   def node(self, value: Any, key: str = "") -> Any:
      if isinstance(value, dict):
         return {name: self.node(inner, name) for name, inner in value.items()}

      if isinstance(value, list):
         return [self.node(element, key) for element in value]

      if isinstance(value, bool) or value is None:
         return value

      if isinstance(value, float):
         return value if key in RANGED_KEYS else 0.0

      if isinstance(value, int):
         return self.number(key, value)

      if isinstance(value, str):
         return self.string(key, value)

      return value


def _manifest_summary(videos: list[dict[str, Any]]) -> list[dict[str, object]]:
   summaries: list[dict[str, object]] = []

   for node in videos:
      manifest = node.get("video_dash_manifest")

      if not isinstance(manifest, str):
         summaries.append({"manifest_type": _shape_of(manifest)})

         continue

      root = MANIFEST_ROOT.search(manifest)
      duration = MANIFEST_DURATION.search(manifest)

      summaries.append(
         {
            "length": len(manifest),
            "root_attribute_names": sorted(ATTRIBUTE_NAME.findall(root.group(1))) if root else None,
            "media_presentation_duration": duration.group(1) if duration else None,
            "representations": manifest.count("<Representation"),
            "audio_adaptation_sets": manifest.count('contentType="audio"'),
            "audio_mime_types": manifest.count('mimeType="audio/'),
            "base_urls": manifest.count("<BaseURL"),
         }
      )

   return summaries


def _media_nodes(parsed: Any) -> tuple[list[dict[str, Any]], bool, str | None]:
   current: Any = parsed

   for key in CONNECTION_PATH:
      current = current.get(key) if isinstance(current, dict) else None

   if not isinstance(current, dict):
      raise RuntimeError("the feed connection was not at its path")

   edges = [edge for edge in (current.get("edges") or []) if isinstance(edge, dict)]
   nodes = [edge.get("node") for edge in edges]
   media = [node["media"] for node in nodes if isinstance(node, dict) and node.get("media")]
   page_info = current.get("page_info") or {}

   return media, bool(page_info.get("has_next_page")), page_info.get("end_cursor")


def _is_video(node: dict[str, Any]) -> bool:
   return node.get("media_type") == VIDEO_MEDIA_TYPE


def _is_carousel(node: dict[str, Any]) -> bool:
   return node.get("media_type") == CAROUSEL_MEDIA_TYPE


def _has_video_child(node: dict[str, Any]) -> bool:
   children = node.get("carousel_media") or []

   return any(isinstance(child, dict) and _is_video(child) for child in children)


async def read_pages(
   sender: PacedSender,
   session: Session,
   user_agent: str,
   report: dict[str, object],
   until: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
   videos: list[dict[str, Any]] = []
   carousels: list[dict[str, Any]] = []
   after: str | None = None
   pages: list[dict[str, object]] = []
   report["pages"] = pages

   for _ in range(FEED_PAGE_CAP):
      cursor = after

      async def attempt(cursor: str | None = cursor) -> object:
         if not session.fb_dtsg:
            await bootstrap(sender, session, user_agent=user_agent)

         request = build_feed_page_request(session, after=cursor, user_agent=user_agent)

         return classify(await sender.send(request))

      parsed = await with_token_recovery(attempt, sender=sender, session=session)
      media, has_next_page, end_cursor = _media_nodes(parsed)

      page_videos = [node for node in media if _is_video(node)]
      page_carousels = [node for node in media if _is_carousel(node)]
      videos.extend(page_videos)
      carousels.extend(page_carousels)

      pages.append(
         {
            "media_nodes": len(media),
            "videos": len(page_videos),
            "carousels": len(page_carousels),
            "carousels_with_a_video_child": sum(_has_video_child(node) for node in page_carousels),
            "media_types": sorted({str(node.get("media_type")) for node in media}),
            "product_types": sorted({str(node.get("product_type")) for node in media}),
            "has_next_page": has_next_page,
         }
      )

      have_both = bool(videos) and bool(carousels)
      have_video_child = any(_has_video_child(node) for node in carousels)
      wants_video_child = until == "video-child"
      found_enough = have_both and (have_video_child or not wants_video_child)
      cannot_continue = not has_next_page or not end_cursor

      if found_enough or cannot_continue:
         break

      after = end_cursor

   return videos, carousels


def write_fixtures(
   videos: list[dict[str, Any]], carousels: list[dict[str, Any]]
) -> dict[str, object]:
   pseudonymiser = Pseudonymiser()
   FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
   written: dict[str, object] = {}

   with_music = [node for node in videos if (node.get("clips_metadata") or {}).get("music_info")]
   with_original_sound = [
      node for node in videos if (node.get("clips_metadata") or {}).get("original_sound_info")
   ]
   chosen = {"video_node.json": with_original_sound[0] if with_original_sound else None}
   chosen["video_with_music_node.json"] = with_music[0] if with_music else None
   chosen["carousel_node.json"] = carousels[0] if carousels else None
   with_video_child = [node for node in carousels if _has_video_child(node)]
   chosen["carousel_with_video_child_node.json"] = with_video_child[0] if with_video_child else None

   for name, node in chosen.items():
      if node is None:
         continue

      path = FIXTURE_DIR / name
      path.write_text(
         json.dumps(pseudonymiser.node(node), indent=1, sort_keys=True) + "\n", encoding="utf-8"
      )
      written[name] = path.stat().st_size

   written["synthetic_ids"] = len(pseudonymiser.ids)
   written["fixture_urls"] = pseudonymiser.url_count

   return written


async def run(write: bool, until: str, fetch: str) -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}
   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT") or DEFAULT_USER_AGENT
   kind = "media-shape"

   report: dict[str, object] = {
      "api_request_cap": API_REQUEST_CAP,
      "cdn_fetch_cap": CDN_FETCH_CAP,
      "credentials_read_from_env": False,
   }

   if not session_path.exists():
      report["failed_with"] = "no session file, run probes/adopt_and_save.py first"
      report_run(f"{kind}-failed", report)

      return 2

   session = Session.load(session_path)
   inner = HttpxTransport(
      cookies=cookies_for(session), proxy=session.proxy, allowed_host=INSTAGRAM_HOST
   )
   counting = CountingTransport(inner, API_REQUEST_CAP)
   report["api_requests"] = counting.sent
   cdn_fetches: list[dict[str, object]] = []
   report["cdn_fetches"] = cdn_fetches

   try:
      async with PacedSender(counting, Pacer(), PROBE_SPACING) as sender:
         videos, carousels = await read_pages(sender, session, user_agent, report, until)
   except (DumpstagramError, RuntimeError) as failure:
      report["failed_with"] = type(failure).__name__
      report["failure_text"] = str(failure)[:200]
      report["api_requests_spent"] = len(counting.sent)
      report_run(f"{kind}-failed", report)

      return 3

   report["api_requests_spent"] = len(counting.sent)
   children = [
      child
      for node in carousels
      for child in (node.get("carousel_media") or [])
      if isinstance(child, dict)
   ]

   video_shape: dict[str, Any] = {}
   carousel_shape: dict[str, Any] = {}
   child_shape: dict[str, Any] = {}

   for node in videos:
      _walk(video_shape, node, "", 0)

   for node in carousels:
      _walk(carousel_shape, {k: v for k, v in node.items() if k != "carousel_media"}, "", 0)

   for child in children:
      _walk(child_shape, child, "", 0)

   report["counts"] = {
      "videos": len(videos),
      "carousels": len(carousels),
      "carousel_children": len(children),
      "video_children": sum(_is_video(child) for child in children),
      "image_children": sum(child.get("media_type") == 1 for child in children),
      "videos_with_clips_metadata": sum(bool(node.get("clips_metadata")) for node in videos),
      "videos_with_has_audio_true": sum(node.get("has_audio") is True for node in videos),
   }
   report["manifests"] = _manifest_summary(videos)
   report["host_families"] = _host_families([*videos, *carousels])
   report["video_node_keys"] = _finalize(video_shape)
   report["carousel_node_keys"] = _finalize(carousel_shape)
   report["carousel_child_keys"] = _finalize(child_shape)

   download_headers = {
      "user-agent": user_agent,
      "referer": "https://www.instagram.com/",
      "accept": "*/*",
   }
   image_headers = download_headers if fetch == "image" else {"user-agent": user_agent}
   image_target = _smallest(
      ((children[0].get("image_versions2") or {}).get("candidates")) if children else None
   )
   video_target = _smallest(videos[0].get("video_versions")) if videos else None
   proxy = session.proxy.url if session.proxy is not None else None

   try:
      if image_target is not None:
         outcome = await _cdn_fetch(image_target["url"], image_headers, proxy)
         outcome["rendition"] = "smallest image candidate of the first carousel child"
         outcome["rendition_width"] = image_target["width"]
         outcome["rendition_height"] = image_target["height"]
         cdn_fetches.append(outcome)

      wants_video_fetch = fetch == "both"

      if wants_video_fetch:
         if video_target is not None:
            await asyncio.sleep(CDN_GAP_SECONDS)
            outcome = await _cdn_fetch(video_target["url"], download_headers, proxy)
            outcome["rendition"] = "smallest video rendition of the first video item"
            outcome["rendition_width"] = video_target["width"]
            outcome["rendition_height"] = video_target["height"]
            cdn_fetches.append(outcome)
   except httpx.HTTPError as failure:
      report["cdn_failed_with"] = type(failure).__name__

   if write:
      report["fixtures_written"] = write_fixtures(videos, carousels)

   have_both = bool(videos) and bool(carousels)
   report["found_video_and_carousel"] = have_both
   report_run(kind if have_both else f"{kind}-incomplete", report)

   return 0 if have_both else 4


async def run_post_detail(write: bool) -> int:
   environment = {key: value for key, value in load_env().items() if key in NON_CREDENTIAL_KEYS}
   session_path = Path(environment.get("IG_SESSION_FILE") or SESSION_PATH)
   user_agent = environment.get("IG_USER_AGENT") or DEFAULT_USER_AGENT
   kind = "media-shape-post-detail"
   report: dict[str, object] = {"api_request_cap": POST_DETAIL_REQUEST_CAP, "cdn_fetches": 0}

   session = Session.load(session_path)
   inner = HttpxTransport(
      cookies=cookies_for(session), proxy=session.proxy, allowed_host=INSTAGRAM_HOST
   )
   counting = CountingTransport(inner, POST_DETAIL_REQUEST_CAP)
   report["api_requests"] = counting.sent
   items: dict[str, dict[str, Any]] = {}

   try:
      async with PacedSender(counting, Pacer(), PROBE_SPACING) as sender:

         async def read(request_for: Any) -> object:
            async def attempt() -> object:
               if not session.fb_dtsg:
                  await bootstrap(sender, session, user_agent=user_agent)

               return classify(await sender.send(request_for()))

            return await with_token_recovery(attempt, sender=sender, session=session)

         parsed = await read(lambda: build_feed_page_request(session, user_agent=user_agent))
         media, _, _ = _media_nodes(parsed)
         videos = [node for node in media if _is_video(node)]
         carousels = [node for node in media if _is_carousel(node)]
         chosen = {"video": videos[:1], "carousel": carousels[:1]}

         for label, nodes in chosen.items():
            if not nodes:
               continue

            code = nodes[0]["code"]
            answer = await read(
               lambda code=code: build_post_request(session, code, user_agent=user_agent)
            )
            current: Any = answer

            for key in POST_ITEMS_PATH:
               current = current.get(key) if isinstance(current, dict) else None

            is_item_list = isinstance(current, list) and bool(current)
            has_item = is_item_list and isinstance(current[0], dict)

            if has_item:
               items[label] = current[0]
   except (DumpstagramError, RuntimeError) as failure:
      report["failed_with"] = type(failure).__name__
      report["failure_text"] = str(failure)[:200]
      report["api_requests_spent"] = len(counting.sent)
      report_run(f"{kind}-failed", report)

      return 3

   report["api_requests_spent"] = len(counting.sent)

   for label, item in items.items():
      shape: dict[str, Any] = {}
      _walk(shape, item, "", 0)
      report[f"{label}_item_keys"] = _finalize(shape)

   if "video" in items:
      report["video_item_manifest"] = _manifest_summary([items["video"]])

   if write:
      pseudonymiser = Pseudonymiser()
      written: dict[str, object] = {}

      for label, item in items.items():
         path = FIXTURE_DIR / f"post_detail_{label}_item.json"
         path.write_text(
            json.dumps(pseudonymiser.node(item), indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
         )
         written[path.name] = path.stat().st_size

      report["fixtures_written"] = written

   found_both = len(items) == 2
   report["read_both_items"] = found_both
   report_run(kind if found_both else f"{kind}-incomplete", report)

   return 0 if found_both else 4


def main() -> int:
   parser = argparse.ArgumentParser()
   parser.add_argument("--write-fixtures", action="store_true")
   parser.add_argument("--until", choices=("both", "video-child"), default="both")
   parser.add_argument("--fetch", choices=("both", "image"), default="both")
   parser.add_argument("--stage", choices=("feed", "post-detail"), default="feed")
   arguments = parser.parse_args()

   if arguments.stage == "post-detail":
      return asyncio.run(run_post_detail(arguments.write_fixtures))

   return asyncio.run(run(arguments.write_fixtures, arguments.until, arguments.fetch))


if __name__ == "__main__":
   sys.exit(main())
